# 问题定位指南（zteam 流水线）

> 配套 DFx（可诊断性设计）：`python3 scripts/statectl.py diagnose` 一键健康检查。
> 本指南是排查的唯一权威文档；症状 → 原因 → 检查 → 修复，按优先级排序。

---

## 0. 排查总原则（先命令，后猜测）

```
① 一键诊断：python3 scripts/statectl.py diagnose   ← 覆盖 80% 的问题，先跑它
② 看状态：  python3 scripts/statectl.py list / get <req_id>
③ 看调度：  hermes cron status  （gateway 是否运行、下次触发）
④ 看日志：  tail workspace/logs/pipeline.log      （状态迁移审计）
            tail workspace/logs/worker-*.log      （worker 明细，看失败原因）
            cat workspace/logs/alarms.txt         （待投递告警）
⑤ 看进程：  ps aux | grep "hermes chat"（worker 是否在跑）
⑥ 修复 → 复跑 diagnose 确认 → 收工
```

**关键认知**：流水线是"上半部（cron 脚本，秒级） + 下半部（独立 worker，分钟级）"两层。**同一症状，先判断卡在哪一层**——上半部不跑 = 调度问题；下半部失败 = worker/模型/API 问题。

## 1. 一键诊断（DFx）

```bash
cd <工作区> && python3 scripts/statectl.py diagnose
```

- 15 项检查（D1–D14）：状态文件合法性、目录完整性、条目 schema、非法状态、中间态滞留、claim 残留、引用文件缺失、归档一致性、未登记输入、状态锁、**gateway 运行**、**cron job 存在性**、worker 进程数、日志可写；
- 输出 `✅ PASS / ⚠️ WARN / ❌ FAIL / ℹ️ INFO`，**任一 FAIL → 退出码 1**（可接入告警）；
- 结论行会给出下一步方向；详细处理见下。

## 2. 症状 → 定位决策表

### S1 需求一直 `pending`，不开始分析
| 优先级 | 可能原因 | 检查 | 修复 |
|---|---|---|---|
| 1 | **gateway 未运行**（最常见） | `diagnose` D11 / `hermes cron status` | `hermes gateway start` |
| 2 | tick 脚本报错（上半部崩了） | `hermes cron run req-analyst-top` 看输出；`journalctl --user -u hermes-gateway -f` | 按报错修（多半是路径/权限），`watchdog-analyst.py` 应静默退出 0 |
| 3 | job 被暂停/删除 | `hermes cron list` 看 3 个 job 是否 `[active]` | `hermes cron resume <job_id>` / 重建（README 快速开始） |
| 4 | 文件没被识别 | 文件名是否含中文/空格/非 `.md`；是否在 `input/` 内 | 按命名规则改名/移入 `input/` |

### S2 卡在 `analyzing` / `reviewing` / `{stage}_designing` / `{stage}_reviewing` 不动
| 优先级 | 可能原因 | 检查 | 修复 |
|---|---|---|---|
| 1 | **worker 还在跑**（慢，正常） | `ps aux | grep "hermes chat"`；`diagnose` D13 | 等。`workspace/logs/pipeline.log` 会有 `SKIP ... 仍存活` |
| 2 | **worker 干完活但漏设状态**（四态 working/reviewing 超时） | `grep GUARD workspace/logs/pipeline.log` | **不用管**——巡检（guard_recovery）已按"超时 + 产物存在性 + 评审结论"自动补正（PASS→done / FAIL→重做），≤20 分钟 + 一个 tick 完成；GUARD 审计留痕 |
| 3 | **worker 已死**（崩溃/被杀） | worker 日志 `tail workspace/logs/worker-{id}-r{N}.log`；`diagnose` D5（claimed_at 超 20 分钟） | 不用管——**下个 tick 的 stale 恢复自动回滚重试**（≤5 分钟）；想立刻重试：`python3 scripts/statectl.py rollback <req_id>` |
| 4 | worker 反复秒退 | worker 日志尾部；`hermes chat -q` 是否可用（PATH/API key/模型名） | 见 S7 |
| 5 | 滞留 >24h | `diagnose` D5 会标 WARN | 人工查 worker 日志与模型/API，`rollback` 后观察 |

### S3 收到 `[BLOCKED]` 告警（连续失败 ≥2 次）
| 步骤 | 动作 |
|---|---|
| 1 | 看失败根因：`tail workspace/logs/worker-{id}-r{N}.log` + `grep {id} workspace/logs/pipeline.log` |
| 2 | 修根因（通常是 S7 的模型/API/权限问题） |
| 3 | 重投：`python3 scripts/statectl.py requeue <req_id>`（回 pending，failures 清零） |
| 4 | 复跑 `diagnose` 确认无 FAIL |

### S4 收到 `[FORCED]` 告警（达 max_rounds 强制归档）
| 步骤 | 动作 |
|---|---|
| 1 | 复核 `workspace/{项目}/artifacts/{req_id}.md` 里的"未解决意见"（含全部轮次评审历史） |
| 2 | 意见合理 → 手工补充需求/接受现状；意见是评审误判 → `requeue` 重跑并考虑放宽检查清单 |
| 3 | 若该需求反复 forced → 考虑提高 `max_rounds`（录入时在 status.json 条目里改）或审视需求原文质量 |

### S5 `approved` 但 `artifacts/` 缺失
| 检查 | 修复 |
|---|---|
| `diagnose` D8 会标出 | 归档由 `release_review` 自动生成；缺失说明归档被删/写失败 → `python3 scripts/statectl.py requeue <req_id>` 重跑一轮，或手工从 analysis/review 拼装 |

### S6 新文件放入 `input/` 后没被注册
| 优先级 | 可能原因 | 检查/修复 |
|---|---|---|
| 1 | 还没到 tick（≤5 分钟） | `hermes cron run req-analyst-top` 立即触发 |
| 2 | 命名/扩展名/位置不符 | 见 §2 S1 第 4 行；`diagnose` D9 |
| 3 | 注册过又被删（同名） | 文件名即 ID，删了文件条目还在 → `requeue` 或删条目重投 |

### S7 worker 秒退 / spawn 失败 / worker 日志为空
| 优先级 | 可能原因 | 检查 | 修复 |
|---|---|---|---|
| 1 | **模型名不存在**（最常见） | `workspace/logs/pipeline.log` 的 `SPAWN` 行看 model；worker 日志里的 API 报错 | 改 `statectl.py` 第 43–48 行常量；可用模型 `curl https://api.deepseek.com/models` |
| 2 | API key 缺失/失效 | worker 日志报 401 | 检查 `$HERMES_HOME/.env` 的 `DEEPSEEK_API_KEY` |
| 3 | `hermes` 不在 PATH（gateway 环境） | `journalctl --user -u hermes-gateway` 看 spawn 报错 | 薄壳里用绝对路径调用（当前已用 `python3` 绝对路径） |
| 4 | 配额/限流（429） | worker 日志 | 等下一轮（stale 恢复自动重试）或换模型 |

### S8 cron 列表有 job 但不自动触发
| 检查 | 修复 |
|---|---|
| `hermes cron status` 是否 "Gateway is running" | 未运行 → `hermes gateway start`（开机自启：`hermes gateway install`，linger 已启用） |
| `hermes cron list` 的 `Repeat` 是否为 ∞ | 曾用 `"5m"` 创建 → 一次性任务；`hermes cron edit <job_id> --schedule "*/5 * * * *" --repeat 0` |

### S9 `status.json` 损坏（JSON 解析失败）
| 步骤 | 动作 |
|---|---|
| 1 | 备份现场：`cp status.json status.json.bak-$(date +%s)` |
| 2 | 用 python 修复（常见：尾逗号/截断）或从 `.bak` 恢复 |
| 3 | 极端情况（无法恢复）：重建条目——**产物文件（analysis/review/artifacts）没丢**，按文件名反推注册：`register` 后手工把 `status` 置为 `analyzed`（已有分析）或 `pending` 重跑 |
| 4 | `diagnose` D1 确认恢复 |

### S10 有告警但收不到推送
| 原因 | 说明 |
|---|---|
| job 的 `deliver=local`（纯本地模式） | 告警/结果只保存不推送。install.sh 默认 `telegram`（可用 `REQREVIEW_DELIVER=local` 覆盖）；若收不到推送，先 `hermes cron list` 看 Deliver 是否为 telegram，不符则重跑 `bash install.sh` 自动校正，或手动 `hermes cron edit <job_id> --deliver telegram` |
| 上半部无活时静默是**设计** | 空 stdout = 不投递；只有 BLOCKED/FORCED/异常才输出 |

### S11 worker 进程活着但卡住不退出（2026-08-08 tetris 实测）

**症状**：需求滞留 `{stage}_designing`（四态 working）超 20 分钟，worker 进程存活（`ps` 可见），`pipeline.log` 无 `STATE` 推进，worker 日志尾部是**完整成功收尾**（产物已落盘 / 自测全绿 / set_status 审计已有）。

| 判定 | 检查 | 处理 |
|---|---|---|
| **模式 A：干完活但 hermes chat 收尾挂住**（网络/会话卡住，与 Telegram 适配器 #63309 同族） | 产物已落盘 + 日志成功收尾 + 无 OOM/kill 痕迹 | **无需人工**——巡检（guard_recovery）会在超时后按"产物存在 → 补 reviewing"自动推进（≤20 分钟 + 一个 tick）；产物无损 |
| **模式 B：真卡死在循环里**（写→跑→修无界迭代） | 产物未落盘 / 日志在反复迭代 | 等巡检兜底（超时无产物 + 进程活 → 继续等待）或 `kill <pid>` 后 `rollback <req_id>` 重试（测试开发类角色在 flash 模型下易出现，属已知行为） |

**教训**：不要一看到"卡住"就杀进程/改状态——先查产物是否已落盘；落盘了就是模式 A，巡检会自动接管。

## 3. 数据视图速查（哪里看什么）

| 位置 | 内容 | 何时看 |
|---|---|---|
| `status.json` | 状态机唯一事实来源（状态/轮次/claim/失败计数） | 一切状态的最终裁决 |
| `workspace/logs/pipeline.log` | 每步状态迁移审计（REGISTER/CLAIM/SPAWN/ANALYZE/REVIEW/STATE/ARCHIVE） | 还原"发生了什么、何时发生" |
| `workspace/logs/worker-{id}-r{N}.log` | 单个 worker 的完整执行明细 + API 报错 | worker 失败/秒退/慢 |
| `workspace/logs/alarms.txt` | 待投递告警（BLOCKED/FORCED） | 有告警未收到推送时 |
| `analysis/review/artifacts/` | 各轮产物 | 质量复核/审计 |
| `journalctl --user -u hermes-gateway -f` | gateway 自身日志（含 cron 执行、spawn 报错） | 上半部不跑/调度异常 |

## 4. 修复操作汇总

```bash
# 状态类
python3 scripts/statectl.py diagnose                 # 一键体检（先跑这个）
python3 scripts/statectl.py list                     # 看全部
python3 scripts/statectl.py get <req_id>             # 看单条（含 claim）
python3 scripts/statectl.py rollback <req_id>        # 中间态 → 可认领态（failures+1）
python3 scripts/statectl.py requeue <req_id>         # blocked/需重跑 → pending（failures 清零）

# 调度类
hermes gateway start|stop|restart                    # gateway 控制
hermes cron run <job_id>                             # 立即触发某 job（调试上半部）
hermes cron list / hermes cron status                # job 与调度状态
hermes cron edit <job_id> --schedule "*/5 * * * *" --repeat 0   # 修复一次性任务
journalctl --user -u hermes-gateway -f               # gateway 日志

# 配置类
# 模型：编辑 scripts/statectl.py 第 43–48 行（环境变量覆盖仅手动运行生效，见 README「模型配置」）
# 轮询间隔：hermes cron edit <job_id> --schedule "..."
# 轮次上限：status.json 条目里改 max_rounds
```

## 5. 修复后验证清单

```bash
python3 scripts/statectl.py diagnose    # 无 FAIL（退出码 0）
hermes cron status                      # "Gateway is running" + 下次触发时间
python3 scripts/statectl.py list        # 所有条目状态符合预期（无滞留中间态）
tail workspace/logs/pipeline.log                  # 最新审计行符合预期流转
```

## 6. 排查心法（三句话）

1. **先分层**：问题在上半部（调度/脚本）还是下半部（worker/模型/API）？`SPAWN` 审计行是分界线；
2. **先诊断后动手**：`diagnose` 的 D 编号就是定位索引，别靠猜；
3. **产物不会丢**：status.json 可以重建，analysis/review/artifacts 的轮次文件是永不覆盖的——最坏情况是重跑一轮，不是数据丢失。
