---
name: req-review-pipeline
description: 运维需求评审自动流水线（工作区见内文，原 ~/cyx/zteam）。处理任务/告警/模型/故障时使用。
---

# 需求评审自动流水线运维（方案 B：上半部/下半部）

用户有一套无人值守的"需求分析 → 多轮评审"流水线，位于 `<工作区>`（项目根目录，原 `~/cyx/zteam/`，可放任意路径）。**本文档是运维手册，详细设计以工作区 `docs/state-machine.md` 与 `README.md` 为准。**

## 架构速记

- **上半部**：cron no_agent 纯脚本（零 token），只做注册/认领/spawn，秒级。5 个 job：`req-analyst-top`（`*/5 * * * *`）、`req-reviewer-top`（`*/5 * * * *`）、`req-worker-top`（`*/5 * * * *`，阶段链 worker）、`req-weekly-audit`（每周一 9 点）、`req-result-notify`（`*/15 * * * *`，结果推送）。
- **下半部**：`setsid hermes chat -q` 独立进程，干分析/评审重活，不受 cron 3 分钟限制。
- **状态机唯一实现**：`scripts/statectl.py`（flock 串行化；claim/release/stale 恢复/告警/归档全在这里）。
- **路径模型（2026-08-08 起）**：数据层全部收进 `workspace/`（`workspace/input|analysis|review|artifacts|logs/` + `workspace/status.json`）；资产层（roles/docs/scripts）留在根目录。产物相对路径（如 `analysis/x/y-r1.md`）从 **WORKSPACE_DIR** 解析——曾出现迁移回归：release_analyze/release_review 校验、write_artifact 归档读取、diagnose D7 引用检查共 5 处误用 `os.path.join(WORKDIR, ...)` 导致所有 release 报"产物不存在"并自动回滚（failures+1），2026-08-08 已全部改为 WORKSPACE_DIR；再遇到"产物不存在"先 grep 这两处拼接。
- 状态流转：`pending → analyzing → analyzed → reviewing → needs_fix ↺ / approved / blocked`。

## 日常操作（在 <工作区> 下）

```bash
# 投放新需求：任意 .md 放进 workspace/<项目名>/input/（一个文件一个需求，项目目录不存在会自动创建），下一个 tick 自动注册并启动
# 边界行为：改内容不改文件名 → 不触发重新分析（重跑用 requeue）；删 workspace/<项目>/input/ 文件 → 状态条目保留；
#           文件名即 ID（仅 [A-Za-z0-9_-]）；完整边界表见 docs/state-machine.md §9.1
# 安装/卸载（幂等/安全，见 README「安装与卸载」）
bash install.sh        # 一键安装/修复（薄壳+5 job+zbot 注入+自检）；工作区迁移后重跑
bash install.sh --with-gateway   # 干净机器一键到位（gateway 未运行则自动安装启动；未装 Hermes 会报错并给安装命令）
bash uninstall.sh      # 卸载（移除 job+薄壳+zbot 配置，保留数据）；--full 清空数据层 workspace/（保留资产，有确认）
# 查看进度
python3 scripts/statectl.py list          # 总览
python3 scripts/statectl.py get <req_id>  # 单条详情（含 claim 字段 + 各阶段四态）
# 状态设置（所有角色共用一个入口，严格迁移校验，乱跳拒绝）——worker 干完活漏调了？巡检会兜底，不用人工补
python3 scripts/statectl.py set_status <req_id> <stage> working              # worker 启动时（第 0 步）
python3 scripts/statectl.py set_status <req_id> <stage> reviewing <产物路径>  # 产出完成 → 待评审
# 人工干预
python3 scripts/statectl.py requeue <req_id>   # blocked 后重投（回 pending、清零 failures）
python3 scripts/statectl.py rollback <req_id>  # 手动回滚中间态
python3 scripts/statectl.py resume <req_id> <stage> <designing|reviewing|gating|releasing|done>  # 人工恢复指定阶段状态
# 审计
tail workspace/logs/pipeline.log   # 状态迁移审计（含 GUARD 巡检补正行）
ls workspace/logs/worker-*.log     # 每个下半部 worker 的明细
```

## 角色与模型

- 角色定义：`roles/req-analyst.md`（**产品视角·麦肯锡方法论**：SCQA 理解、MECE 分解、金字塔表达、5W1H 澄清；主动查资料；产出需求分解文档 FR/NFR/竞品分析；**红线=只答 What/Why 绝不答 How**，禁止技术方案/选型/架构）、`roles/req-reviewer.md`（**12 项检查清单**，含 MECE 完整性、竞争力分析两项）。
- 模型绑定在 `scripts/statectl.py` **第 43–48 行**常量（改模型直接改这里，立即生效；同名环境变量覆盖**仅对手动运行生效**——gateway 是 systemd 服务，不继承交互 shell 的 export，需 `systemctl --user edit hermes-gateway` 加 `Environment=` 再 restart）：
  - 分析师/产出类（analyst、dev-plan-designer、test-plan-designer、code-developer、test-developer、releaser）= `deepseek-v4-flash`（快/便宜，产出量大）
  - 评审/门禁类（req-reviewer、dev-plan-reviewer、test-plan-reviewer、code-reviewer、test-reviewer、quality-reviewer、security-reviewer）= `deepseek-v4-pro`（强推理，把关）
- **用户 DeepSeek API 只有这两个模型**——不要写 deepseek-chat / deepseek-reasoner（不存在，会必现报错）。
- **11 角色阶段链**：需求(分析师/评审师) → plan(dev-plan-designer/reviewer) → testplan(test-plan-designer/reviewer) → code(code-developer/reviewer) → test(test-developer/reviewer) → quality(门禁) → security(门禁) → release(releaser) → released 终态。角色定义见 `roles/*.md`。
- **四态状态机**：每阶段 `claimed（tick 认领）→ working（worker 启动时 set_status）→ reviewing（产出后 set_status + 产物）→ done（评审 PASS）`；FAIL 打回 working 重做，连续 FAIL 达 max_rounds → blocked。真值存 `stages[stage].state`（status.json），顶层 status 为派生显示。
- **巡检兜底（guard_recovery）**：worker 漏设状态/卡死循环时，超时（20 分钟）后按"产物存在性 + 评审结论"自动补正（PASS→done / FAIL→重做 / 无产物→回滚），写 `GUARD` 审计——**worker 无需自觉，漏了自动兜底，不要人工补状态**。

## 告警处理

- `[BLOCKED]`：连续失败 ≥2 次，流水线停止流转等人工。**处置必须走下方标准流程，先查根因再 requeue**。
- `[FORCED]`：达 max_rounds=3 仍 FAIL，强制归档 `workspace/artifacts/<project>/<req_id>.md`（含全部轮次历史），需人工复核未解决意见。
- 告警经上半部 tick 从 `workspace/logs/alarms.txt` 消费并输出；cron 未配 deliver 时只本地保存。

## BLOCKED 根因分析标准流程（zbot 收到 BLOCKED 后必须主动完成，带结论请示；不得只问"要不要 requeue"）

触发机制：`failures ≥ 2`（stale 回滚或评审 FAIL 累计），护栏触发后停止流转。requeue 前完成下面 4 步：

1. **定位卡死点**：`statectl list` + `tail workspace/logs/pipeline.log`——找 BLOCKED 前最后一条 RECOVER/FAIL 属于哪个阶段，failures 如何累计（**stale 回滚** vs **评审 FAIL** 性质不同：前者是进程问题，后者是内容问题）；
2. **查 worker 生死**：pipeline.log 的 SPAWN/SKIP 行有 pid；`ps -p <pid>`——存活且多 tick 无进展=可能"干完活没退出"（模式 A）；已死=崩溃（模式 B）；
3. **看 worker 日志**：`tail workspace/logs/worker-<key>-r<N>.log` 最后输出 + 对比日志 mtime 与停止时间差，grep `error|traceback|timeout`；
4. **产物完整性**：`ls workspace/{stage}/{project}/{req_id}-r{N}/`——决定 requeue 后是否丢工作。

**已知模式**：
- **模式 A「干完活没退出」**（2026-08-08 tetris 实测）：worker 日志有完整成功收尾（验证全绿/产物落盘/set_status 已在 pipeline.log 留下审计）+ 进程存活但连续多 tick 无进展 + dmesg 无 OOM/kill → 判定为 **hermes chat 进程完成响应后挂住不退出**（网络/会话收尾卡住，与 Telegram 适配器挂起 #63309 同族，环境网络不稳是背景）。**产物无损 → 直接 requeue 重跑即可，无需改任何代码**；
- **模式 B「中途崩溃」**：worker 日志尾部有 traceback/API 报错（模型名不存在/限流/代码缺陷）→ 先修根因再 requeue；
- **告警送达验证**：BLOCKED 文本由上半部 tick `drain_alarms` 后经 cron deliver 推送；alarms.txt 为空**不代表没推送**（已被消费）。判断以用户是否收到为准，别用文件存在性判断。

## 部署事实与坑（全部踩过）

0. **install.sh 默认所有 job `deliver=telegram`**（结果/告警自动推 Telegram）；`REQREVIEW_DELIVER=local` 可覆盖为纯本地。**重跑 install.sh 会校正已存在 job 的 deliver 不符**（2026-08-08 修复：此前默认 local 导致 approved 结果不推送，需手动 `hermes cron edit <job_id> --deliver telegram`）。tick 脚本无活静默（只有 BLOCKED/FORCED/审计问题才输出），全量 telegram 不会刷屏。

1. **cron 脚本必须在 `$HERMES_HOME/scripts/`（默认 `~/.hermes/scripts/`）下**，且 CLI 拒绝软链逃逸 → 用 2 行 `exec python3 <工作区>/scripts/xxx.py` 薄壳（已建好：watchdog-analyst.sh / watchdog-reviewer.sh / watchdog-worker.sh / watchdog-weekly.sh / watchdog-notify.sh）。
2. **调度用 cron 表达式**（`*/5 * * * *`）；`"5m"` 会被解析为一次性任务；`--repeat 0` = 无限循环。
3. **job 只在 gateway 运行时自动触发**——已安装为用户 systemd 服务（`hermes gateway install`，linger 已启用），开机/登出均常驻；`hermes gateway status` / `hermes cron status` 查看；可用 `hermes cron run <job_id>` 手动触发某个 job（no_agent 脚本会立即执行）。
4. 脚本被软链/经别的路径调用时 `__file__` 会变 → statectl 与 watchdog 入口必须用 `os.path.realpath(__file__)` 推导路径（已内置）。
5. `os.kill(0, 0)` 会对当前进程组发信号误判存活 → `pid_alive` 对 `pid <= 0` 直接返回 False（已内置）。
6. 上半部 tick 一次只认领一个需求（最老优先），防唤醒风暴 + 规避 3 分钟限制。
7. **国内网络**：pypi.org / api.telegram.org 直连被墙。依赖用清华镜像装（`uv pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple ...`）；**Telegram 已打通（2026-08-07 实测）**：4 通道（告警/结果推送 + 聊天查询/干预/投放）全部可用，4 个 cron job `deliver=telegram`，`.env` 已配 token/`TELEGRAM_ALLOWED_USERS=6525650097`/`TELEGRAM_HOME_CHANNEL=6525650097`。**关键环境坑**：gateway drop-in（`~/.config/systemd/user/hermes-gateway.service.d/override.conf`）必须置空 `http_proxy`/`https_proxy`——适配器直连走 clash TUN（fake-IP）正常；走 7890 HTTP 代理会触发适配器挂起（卡 "attempt 1/8"，#63309 家族，可数小时恢复）。clash 节点失效时 Telegram 连接必断，恢复后适配器自动重连（慢）。`delivery_obligations` 表只记会话投递，**cron 投递不写该表**——判断 cron 推送是否成功以用户收到为准，别用台账判断。

## Telegram 交互约定（gateway 会话适用）

用户在消息平台（Telegram 等）提出需求流水线相关请求时，按以下约定处理（无需用户给命令行）：

- **投放**：用户发需求文本/文件 → 起合法 `req_id`（英文短名或拼音，仅 `[A-Za-z0-9_-]`，**避免中文文件名**）→ 写入 `workspace/input/{project}/{req_id}.md`（项目名未指定用 `default`）→ 回复"已投放 {project}/{req_id}，5 分钟内自动开始分析"；
- **查询**：回复 `statectl list` 的摘要（状态/轮次/失败数），详情用 `get <req_id>`；
- **干预**：执行 `requeue`/`rollback`/`diagnose` 并回复结果；
- **推送**：告警与结果推送由 cron（`deliver=telegram`）自动完成，agent 不需要主动发；
- **zbot 职责边界**：zbot 是流水线专属助手（严格模式），只做投放/查询/干预/汇报，其他请求一律拒绝。职责单一事实来源 = 工作区 `roles/bot.md`；改它之后要 `python3 scripts/bot_config.py install` + `systemctl --user restart hermes-gateway` 才生效（注入目标是 `$HERMES_HOME/gateway.json` 的 `platforms.telegram.channel_overrides[<chat_id>].system_prompt`，频道级追加提示词，不覆盖默认能力；uninstall.sh 自动移除）；
- **边界提醒**：投放后如用户说"改了需求"，提示"改内容不改文件名不会重跑，需要 `requeue <req_id>`"（详见 docs/state-machine.md §9.1）；
- 所有操作在 `<工作区>`（项目根目录）下执行（`cd <工作区>` 后跑 `python3 scripts/statectl.py ...`）。

## 问题定位（先跑一键诊断）

> 读取流水线产物 md（plan/testplan 等）时若 read_file 报 "Binary file"：是文件含超长行（>400 字符，如方案表格行）触发的误判，文件本身是 UTF-8——用 `iconv -f UTF-8 -t UTF-8` 转一份到 /tmp 再 read_file，或直接 `python3 -c "print(open(p,encoding='utf-8').read())"`。需求原文 input/*.md 曾出现 UTF-16 编码，同样用 iconv/xxd 先判编码。

```bash
python3 scripts/statectl.py diagnose   # 15 项健康检查，任一 FAIL → 退出码 1
```
诊断覆盖：状态文件/目录/条目 schema/非法状态/中间态滞留/claim 残留/引用文件/归档/gateway 运行/cron job/worker 进程/日志可写。**完整症状决策表见工作区 `docs/troubleshooting.md`（唯一权威）**，要点：

| 症状 | 第一检查 | 修复 |
|---|---|---|
| 一直 pending 不分析 | diagnose D11 / `hermes cron status` | 多半是 gateway 未运行 → `hermes gateway start` |
| 卡 analyzing/reviewing | `ps aux \| grep "hermes chat"`；worker 日志 | worker 还活着=慢，等（20min 后 stale 自动回滚）；死了 → 下个 tick 自动恢复或 `rollback <id>` |
| `[BLOCKED]`（失败≥2） | `tail workspace/logs/worker-*.log` 找根因 | 修根因 → `requeue <id>` |
| `[FORCED]`（超轮次强制归档） | 复核 `workspace/artifacts/<project>/<id>.md` 未解决意见 | 人工裁决；误判则 requeue 重跑 |
| worker 秒退/日志空 | pipeline.log 的 SPAWN 行看 model | **最常见：模型名不存在** → 改 statectl.py 第 43–48 行；其次 API key/限流 |
| job 不自动触发 | `hermes cron status` + Repeat 是否 ∞ | gateway 未跑 → start；`"5m"` 建的一次性任务 → `hermes cron edit --schedule "*/5 * * * *" --repeat 0` |
| workspace/status.json 损坏 | 备份 → 修复/重建条目（产物不丢） | 见 docs/troubleshooting.md §2 S9 |

**分层心法**：`SPAWN` 审计行是上下半部分界线——上半部问题看 gateway/脚本，下半部问题看 worker/模型/API；产物文件永不覆盖，最坏情况是重跑一轮而非丢数据。

## 验证

- 状态机自测（零 token）：`register` → `claim <id> analyst` → 写产物 → `release_analyze` → `claim <id> reviewer` → `release_review <id> <file> FAIL` → 检查 `needs_fix`/`approved`/强制归档分支与 `workspace/artifacts/` 生成。
- 端到端冒烟：放真实需求进 `workspace/input/<项目名>/`，手动跑 `python3 scripts/watchdog-analyst.py` → 轮询 `get` 到 `analyzed` → `python3 scripts/watchdog-reviewer.py` → 轮询到 `approved`，核对 workspace/logs/pipeline.log 与 workspace/artifacts/。
