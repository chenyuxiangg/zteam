# 需求分析与多轮评审自动流水线（方案 B）

基于 **cron + 文件消息池** 的无人值守多角色流水线。调度采用**上半部 / 下半部**架构（对应 Linux 中断处理模型）：**上半部只唤醒（秒级、零 token），下半部干活（分钟级、独立进程、不受 cron 3 分钟硬中断限制）**。

需求分析师与需求评审师是两个独立角色，各自独立绑定模型，通过共享工作区 `status.json` + 文件目录实现"自动感知"，多轮"分析 → 评审 → 修改 → 再评审"直至通过，全程无人值守。

## 覆盖的需求

| 原始诉求 | 实现 |
|----------|------|
| 分析与评审是不同角色 | `roles/analyst.md` vs `roles/reviewer.md`，两个上半部 job + 两个下半部 worker 完全分离 |
| 一次输入多个需求 | `input/` 可放任意多个 `{req_id}.md`，各自独立流转、互不阻塞 |
| 评审结论被分析者自动感知 | 分析师上半部轮询 `needs_fix` 状态并唤醒修改 worker |
| 分析完成被评审者自动感知 | 评审上半部轮询 `analyzed` 状态并唤醒评审 worker |
| 多轮自动完成 | 状态机循环直至 `approved` 或 `max_rounds` 上限，失败自动重试 + stale 恢复 |

## 架构总览

```
┌─ 上半部（cron no_agent 纯脚本，秒级，零 token，3 分钟内绰绰有余）────┐
│  watchdog-analyst.py   注册新需求 / stale 恢复 / 原子认领 / spawn 分析师 worker │
│  watchdog-reviewer.py  stale 恢复 / 原子认领 / spawn 评审 worker            │
│  watchdog-weekly.py    每周一致性巡检（只告警）                             │
│  watchdog-notify.py    每 15 分钟：有新归档才输出报告（cron deliver 推送）    │
└──────────────────────────────────────────────────────────────┬────────────┘
                          setsid hermes chat -q -m <model> &
┌──────────────────────────────────────────────────────────────▼────────────┐
│ ── 下半部（独立 Hermes 进程，分钟级，无 3 分钟限制，进程级持久）──          │
│   analyst worker → 读原文/查资料 → 按 roles/analyst.md 产出需求分解文档（FR/NFR/竞品分析）│
│                    → statectl.py release_analyze（状态落定）               │
│   reviewer worker → 读原文/分析 → 按 roles/reviewer.md 评审                │
│                    → statectl.py release_review（状态落定 + 归档）         │
└─────────────────────────────────────────────────────────────────────────────┘
       状态机：pending → analyzing → analyzed → reviewing → needs_fix ↺ / approved
       （状态机全部确定性逻辑集中在 scripts/statectl.py，flock 串行化）
```

## 目录结构

```
req-review/
├── roles/analyst.md       # 需求分析师角色定义（产品视角·麦肯锡：SCQA/MECE，含需求分解模板）
├── roles/reviewer.md      # 需求评审师角色定义 + 12 项评审检查清单
├── roles/bot.md           # zbot（Telegram bot）职责边界与人格定义（install 注入 gateway，uninstall 移除）
├── scripts/bot_config.py  # zbot 职责注入/移除（install/uninstall 子命令，写 ~/.hermes/gateway.json）
├── docs/state-machine.md  # 状态机定义（上下半部架构、状态、竞态、失败处理）
├── scripts/               # statectl.py（状态机唯一实现）+ watchdog-analyst/reviewer/weekly.py 上半部入口
├── AGENTS.md              # 流水线约定（下半部 worker 自动加载）
├── input/                 # 需求原文投放区（{req_id}.md）
├── analysis/              # 分析报告（{req_id}-r{N}.md，每轮新文件）
├── review/                # 评审意见（{req_id}-r{N}.md）
├── artifacts/             # 终版产出（含历史与意见，强制通过时 forced: true）
├── logs/                  # pipeline.log（审计）+ worker-*.log（下半部明细）
└── status.json            # 状态机（唯一事实来源）
```

## 快速开始（3 步）

1. **投放需求**：把需求原文放入 `input/req-001.md`（可一次放多个；上半部脚本会自动登记）；
2. **创建三个 cron job**（全部 `no_agent` 纯脚本，不需要模型）：

```bash
# 前提：CLI 只接受 ~/.hermes/scripts/ 下的真实文件（软链会被拒绝），
# 因此先建 2 行 exec 薄壳（本流水线已建好，逻辑唯一实现在工作区）：
#   ~/.hermes/scripts/watchdog-analyst.sh   -> exec python3 /home/zyzs/cyx/req-review/scripts/watchdog-analyst.py
#   ~/.hermes/scripts/watchdog-reviewer.sh  -> exec python3 /home/zyzs/cyx/req-review/scripts/watchdog-reviewer.py
#   ~/.hermes/scripts/watchdog-weekly.sh    -> exec python3 /home/zyzs/cyx/req-review/scripts/watchdog-weekly.py

hermes cron create "*/5 * * * *" --name req-analyst-top  --script watchdog-analyst.sh  --no-agent --repeat 0
hermes cron create "*/5 * * * *" --name req-reviewer-top --script watchdog-reviewer.sh --no-agent --repeat 0
hermes cron create "0 9 * * 1"   --name req-weekly-audit --script watchdog-weekly.sh   --no-agent --repeat 0
```

> 注意：调度请用 cron 表达式（`"5m"` 会被解析成一次性任务）；`--repeat 0` = 无限循环；**job 只有在 gateway 运行时才会自动触发**（`hermes cron status` 查看；未运行时输出仍会被保存但不投递）。

3. **查看结果**：`jq . status.json` 看流转；`ls artifacts/` 看终版；`tail logs/pipeline.log` 看审计；**有问题先跑 `python3 scripts/statectl.py diagnose`**（问题定位见 `docs/troubleshooting.md`）。

> 替代方案：**第 2 步可直接用一键脚本** `bash install.sh` 完成（幂等，可重复执行），见下节。

## 安装与卸载

```bash
bash ~/cyx/req-review/install.sh                        # 一键安装/修复（幂等）：目录骨架 + cron 薄壳 + 4 个 job + zbot 职责注入 + 自检
bash ~/cyx/req-review/install.sh --with-gateway         # 干净机器一键到位：gateway 未运行则自动安装并启动
bash ~/cyx/req-review/uninstall.sh                      # 卸载：移除 4 个 job + 薄壳 + zbot 职责配置，【保留全部数据】
bash ~/cyx/req-review/uninstall.sh --full               # 清空运行期数据（analysis/artifacts/review/logs/status.json），项目资产与 git 历史保留（交互输入 yes；agent 场景用 REQREVIEW_FULL_YES=1 免交互）
```

### 干净机器完整流程（新机器 / 迁移）

1. **安装 Hermes**（唯一前置，install.sh 不代劳——它本身就是 Hermes 上的流水线）：
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
   hermes --version    # 确认 CLI 可用
   ```
2. **拷贝工作区**：把整个 `req-review/` 目录拷到目标机任意路径（路径随意，脚本自动适配；迁移后必须重跑 install 以按新路径重建薄壳）：
   ```bash
   scp -r req-review/ user@host:~/
   ```
3. **一键安装（含 gateway 自启）**：
   ```bash
   cd req-review && bash install.sh --with-gateway
   ```
   该命令幂等完成：目录骨架 → cron 薄壳（按当前路径生成）→ 3 个 cron job → gateway 未运行则自动安装启动（用户级 systemd 服务，开机自启）→ 末尾自动 `diagnose` 自检，全绿才 exit 0。
4. **验证**：
   ```bash
   hermes cron status                    # 应见 "Gateway is running" + 3 active jobs
   python3 scripts/statectl.py diagnose  # 应见 0 严重问题 / 0 警告
   # 可选端到端验证（消耗少量 token）：投放一个测试需求并立即触发
   cp 测试需求.md input/test-install.md && hermes cron run req-analyst-top
   python3 scripts/statectl.py list      # 应见 analyzing → analyzed
   ```
5. **场景差异说明**：
   - **未装 Hermes** → install.sh 明确报错并给出第 1 步的安装命令（exit 1，无副作用）；
   - **已装但 gateway 未启动** → 不加参数会警告 + exit 1（job 照常建好但不触发）；加 `--with-gateway` 自动解决；
   - **无 systemd 环境**（WSL/Docker 等）→ `--with-gateway` 自动启动失败时会提示手动方案（`hermes gateway run` 前台 / `sudo hermes gateway install --system`），不会静默假装成功。

- **install 幂等**：重复执行只会补齐缺失项（已存在则跳过），末尾自动跑 `diagnose` 自检；**工作区迁移后重跑 install 即可**（薄壳按当前路径重新生成）；
- **uninstall 默认安全**：只拆 cron job 与 `~/.hermes/scripts/` 薄壳，`status.json`/产物/日志原样保留；`--full` 才删数据且有确认；
- 两者都**不碰 gateway**（它同时服务 Hermes 其他功能）。

## 模型配置

**绑定位置**：不在 cron 配置里，而在 `scripts/statectl.py` **第 43–48 行**的四个常量（worker spawn 时经 `hermes chat -q -m <model> --provider <provider>` 传入）。两角色天然不同模型，改模型只需改常量，无需重建 cron job。

| 常量（第 43–48 行） | 当前值 | 角色 |
|----------------------|--------|------|
| `ANALYST_MODEL` / `ANALYST_PROVIDER` | `deepseek-v4-flash` / `deepseek` | 分析师（快/便宜，产出量大） |
| `REVIEWER_MODEL` / `REVIEWER_PROVIDER` | `deepseek-v4-pro` / `deepseek` | 评审师（强推理，把关） |

**改模型两种方式**：
1. **直接改常量（推荐）**：编辑 `scripts/statectl.py` 第 43–48 行即可，立即生效；
2. **环境变量覆盖**：`ANALYST_MODEL` / `REVIEWER_MODEL` 等同名环境变量优先。⚠️ **坑**：cron job 由 gateway（systemd 服务）执行，交互 shell 里 `export` 的变量**到不了 gateway 进程**——环境变量覆盖只对手动运行（`python3 scripts/statectl.py ...`）生效；要让 gateway 场景也走环境变量，需 `systemctl --user edit hermes-gateway` 在 `[Service]` 下加 `Environment=ANALYST_MODEL=...` 再 `hermes gateway restart`。

**验证生效**：`tail logs/pipeline.log` 中 `SPAWN` 行带实际模型（`... model=deepseek-v4-flash ...`）。

> 可用模型以上游 API 实际返回为准（`curl https://api.deepseek.com/models`）；当前 API 仅有 `deepseek-v4-flash` 与 `deepseek-v4-pro`。

## 关键限制与对策

- **cron 3 分钟硬中断** → 上半部只做秒级唤醒，耗时活全部在下半部独立进程完成（`setsid` 脱离 cron 会话，进程级持久）；
- **双 job 竞态** → 中间态（analyzing/reviewing）原子认领（compare-and-swap）+ `flock` 锁；
- **worker 崩溃** → 上半部 stale 恢复（`kill -0` 存活检查 + 超时回滚 + failures 计数），2 次后 `blocked` + 告警推送；
- **模型质量上限** → 检查清单逐条可勾选，主观判断最小化。

## Gateway 与开机自启

流水线的 3 个 cron job 由 Hermes gateway 调度，**gateway 未运行时 job 不会自动触发**（`hermes cron list` 仍可见）。

- **安装与开机自启**（本机已完成）：`hermes gateway install` 安装为用户级 systemd 服务 `hermes-gateway.service`（`enabled` + `Linger=yes` → 开机自动启动，无需登录）。服务器场景：`sudo hermes gateway install --system`（boot-time 系统服务）。
- **状态确认**：`hermes gateway status`；或 `systemctl --user is-active hermes-gateway`、`loginctl show-user $(whoami) -p Linger`。
- **日志**：`journalctl --user -u hermes-gateway -f`。
- **控制**：`hermes gateway start|stop|restart`；卸载 `hermes gateway uninstall`。
- **调度确认**：`hermes cron status` 显示 "Gateway is running — cron jobs will fire automatically" 即正常；也可用 `hermes cron run <job_id>` 手动立即触发某个 job。

## Telegram 统一交互

目标：**告警、结果、查询/干预、投放**四条通道全部走 Telegram，日常不再需要碰命令行。

### 通道① 告警推送（已配置）
上半部 2 个 tick + 周巡检均已 `deliver=telegram`：`[BLOCKED]` 连续失败、`[FORCED]` 强制归档才会推送；无活静默，不刷屏。

### 通道② 结果推送（已配置）
`req-result-notify`（每 15 分钟，no_agent）：有新归档才推送，格式：
```
📋 需求评审结果（新增 1 项归档）
✅ req-003 — 第 1 轮通过（artifacts/req-003.md）
⚠️ req-004 — 第 3 轮通过 ⚠️强制归档（需人工复核）（artifacts/req-004.md）
```
首次运行只初始化标记不推送（避免历史归档全推一遍）。

### 通道③④ 查询 / 干预 / 投放（聊天即操作）
连接后直接和 bot 对话（中文即可），Hermes 会加载 `req-review-pipeline` skill 处理：
- **投放**："我有个新需求：<内容>" → 自动写入 `input/`（起合法 req_id）；
- **查询**："需求进度" / "req-003 状态" → 状态摘要回复；
- **干预**："requeue req-003" / "rollback req-003" / "跑下诊断"；
- 结果随时可问，或等通道②推送。

### zbot 职责约束（严格模式）
zbot 是**流水线专属助手**：只处理投放/查询/干预/汇报，其他请求（闲聊、通用问答、编程等）一律拒绝。
- **单一事实来源**：`roles/bot.md`（职责边界 + 人格定义）；
- **注入机制**：`install.sh` 把 `roles/bot.md` 内容写入 `~/.hermes/gateway.json` 的 `platforms.telegram.channel_overrides[<chat_id>].system_prompt`（频道级提示词，追加不覆盖默认能力；用 gateway.json 而非 config.yaml 是因为后者注释会被重写丢失）；
- **生效**：改 `roles/bot.md` 后重跑 `python3 scripts/bot_config.py install` + `systemctl --user restart hermes-gateway`；
- **卸载**：`uninstall.sh` 自动移除该配置（gateway.json 空壳自清理）；手动：`python3 scripts/bot_config.py uninstall`。

### 前置步骤（一次性，需要你操作）
1. Telegram 里找 **@BotFather** → `/newbot` → 拿到 bot token；
2. 配置（二选一）：
   - 交互式：`hermes gateway setup` 按向导填写；
   - 手动：token 写入 `~/.hermes/.env` 的 `TELEGRAM_BOT_TOKEN=`（建议同时设 `TELEGRAM_ALLOWED_USERS`（你的用户 ID，限制只响应你）与 `TELEGRAM_HOME_CHANNEL`（目标 chat id，投递落点））；
3. `hermes gateway restart`；
4. **给 bot 发一条消息**（建立会话、确认 home channel）；
5. 验证：`hermes cron run req-result-notify`——最近有归档会收到推送；无消息 = 正常（空输出不推送）。

> 新机器安装时可直接带投递目标：`REQREVIEW_DELIVER=telegram bash install.sh`。

### 当前状态（2026-08-07 实测）
- ✅ **四通道全部打通**：①告警推送 ②结果推送 ③聊天查询/干预 ④聊天投放需求——均已实证可用
- ✅ **zbot 职责约束已生效**（2026-08-07 用户实测）：严格模式——只处理流水线操作，越界请求（闲聊/通用问答等）一律拒绝；定义在 `roles/bot.md`，install/uninstall 自动注入/移除（gateway.json channel_overrides）
- ✅ 配置：`TELEGRAM_BOT_TOKEN`（有效，@zyzs_bot）、`TELEGRAM_ALLOWED_USERS=6525650097`、`TELEGRAM_HOME_CHANNEL=6525650097`（DM 落点）均在 `~/.hermes/.env`
- ✅ 4 个 cron job 均 `deliver=telegram`；notify 推送链路两次端到端实证全送达（即使执行时适配器刚经历重连，网络恢复即投递成功）
- ✅ 退出 TUI 会话后依然可用——常驻 gateway 为 systemd 服务（`hermes-gateway.service`），与终端会话无关
- ⚠️ 已知边界：Telegram 适配器（Hermes 内置）对网络波动恢复慢（首次连接可能卡 "attempt 1/8" 数分钟～数小时，#63309 家族）；期间聊天/推送可能短暂无响应，网络恢复后自动重连。clash 节点不稳定是外部根因。**不构成功能缺口**（实测推送会送达，只是可能延迟）
- ⚠️ 环境：gateway systemd drop-in（`~/.config/systemd/user/hermes-gateway.service.d/override.conf`）置空 `http_proxy`/`https_proxy`——适配器直连走 clash TUN（fake-IP），实测优于走 7890 HTTP 代理（后者会触发适配器挂起）
- 投递落点：`deliver=telegram` 在触发时解析到配置的 home channel（= 用户私聊）

## 使用注意事项

### 版本管理（git，防误删/误改）
工作区是 git 仓库（2026-08-07 初始化，首提交含全部核心资产 + 业务数据）。
- **远程备份**：`git@github.com:chenyuxiangg/zteam.git`（`origin`，SSH 免密；新机器恢复：`git clone git@github.com:chenyuxiangg/zteam.git ~/cyx/req-review`）；
- **日常提交**（推荐每次改动后）：
  ```bash
  cd ~/cyx/req-review && git add -A && git commit -m "描述改动" && git push
  ```
- **误删恢复**：`git checkout -- .`（恢复所有改动）/ `git restore <文件>`（恢复单个）；
- **回滚到某次提交**：`git log --oneline` 查版本号 → `git reset --hard <版本号>`（谨慎，丢弃之后改动）；
- **忽略项**：`logs/`、`__pycache__/`、`status.lock`（运行噪音，不入库）；`status.json`、`input/`、`analysis/`、`review/`、`artifacts/` 等业务数据全部入库；
- **教训**：2026-08-07 工作区曾被旧版 `uninstall.sh --full`（删除整个工作区）误删，靠会话 DB 重建——现 `--full` 已改为只清空运行期数据、保留项目资产；纳入 git 后即使误删也可 `git restore` 秒级恢复。


- 投放唯一入口是 `input/`；一个 `.md` = 一个需求，**文件名即需求 ID**（仅允许 `[A-Za-z0-9_-]`）；
- **改内容不改文件名不会触发重新分析**——重跑用 `python3 scripts/statectl.py requeue <req_id>`；
- 删除 `input/` 文件不会清理 `status.json` 条目（历史保留）；
- 非 `.md` 文件忽略；一个文件放多个需求会被当作一个需求处理；
- 完整边界行为表见 `docs/state-machine.md` §9.1。

## 设计文档索引

- 角色：`roles/analyst.md`（产品视角·麦肯锡方法论）、`roles/reviewer.md`（12 项检查清单）、`roles/bot.md`（zbot 职责，install/uninstall 自动注入/移除）
- 状态机（含上下半部调度架构）：`docs/state-machine.md`
- **问题定位指南（DFx）**：`docs/troubleshooting.md`
- 流水线约定（下半部加载）：`AGENTS.md`
