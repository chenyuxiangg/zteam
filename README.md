# 需求分析与多轮评审自动流水线（方案 B）

> **路径约定**（迁移友好，全文统一）：
> - `<工作区>` = 项目根目录（git clone 下来的目录，可放在任意路径，如 `~/cyx/zteam`）；
> - `$HERMES_HOME` = Hermes 配置目录（默认 `~/.hermes`）；
> - 除特殊说明外，命令均在 `<工作区>` 下执行（`cd <工作区>` 后运行）。

基于 **cron + 文件消息池** 的无人值守多角色流水线。调度采用**上半部 / 下半部**架构（对应 Linux 中断处理模型）：**上半部只唤醒（秒级、零 token），下半部干活（分钟级、独立进程、不受 cron 3 分钟硬中断限制）**。

v2 起为八角色模块中心模型（PM/SE/TE/MDE/FO/MTO/STO/QA）：需求请求 → PM 细化 → 用户评审锁定规格 → SE 版本级架构 → TE 测试方案 → 模块迭代（MDE 设计→FO TDD→MTO 模块 IT）→ STO 版本 ST → QA 发布（用户确认）→ 版本 released。规格/模块/版本状态全部由脚本固定规则守护（迁移表强制 + 巡检兜底），无人值守。

## 覆盖的需求

| 原始诉求 | 实现 |
|----------|------|
| 分析与评审是不同角色 | `roles/req-analyst.md` vs `roles/req-reviewer.md`，两个上半部 job + 两个下半部 worker 完全分离 |
| 一次输入多个需求 | `workspace/<项目>/input/` 可放任意多个 `{req_id}.md`，各自独立流转、互不阻塞 |
| 评审结论被分析者自动感知 | 分析师上半部轮询 `needs_fix` 状态并唤醒修改 worker |
| 分析完成被评审者自动感知 | 评审上半部轮询 `analyzed` 状态并唤醒评审 worker |
| 多轮自动完成 | 状态机循环直至 `approved` 或 `max_rounds` 上限，失败自动重试 + stale 恢复 + 巡检兜底（漏设状态自动补正） |

## 架构总览

```
┌─ 上半部（cron no_agent 纯脚本，秒级，零 token，3 分钟内绰绰有余）────┐
│  watchdog-analyst.py   注册新需求 / stale 恢复 / 原子认领 / spawn 分析师 worker │
│  watchdog-reviewer.py  stale 恢复 / 原子认领 / spawn 评审 worker            │
│  watchdog-worker.py    主调度：stale 恢复 + 巡检兜底 + 阶段链认领+spawn      │
│  watchdog-weekly.py    每周一致性巡检（只告警）                             │
│  watchdog-notify.py    每 15 分钟：有新归档才输出报告（cron deliver 推送）    │
└──────────────────────────────────────────────────────────────┬────────────┘
                          setsid hermes chat -q -m <model> &
┌──────────────────────────────────────────────────────────────▼────────────┐
│ ── 下半部（独立 Hermes 进程，分钟级，无 3 分钟限制，进程级持久）──          │
│   需求阶段：analyst → req-analyst.md 产出需求分解文档 → set_status reviewing │
│             reviewer → req-reviewer.md 评审 → release_review（PASS→阶段链） │
│   阶段链：  方案设计→方案评审→测试方案→测试方案评审→代码→代码评审→          │
│             测试开发→测试评审→质量门禁→安全门禁→发布（released 完整交付）    │
│   每阶段四态：claimed（认领）→ working（启动）→ reviewing（产出）→ done（PASS）│
│             状态变更全部经 set_status/release_*（严格迁移校验）；           │
│             漏设状态由上半部巡检（guard_recovery）自动补正（GUARD 审计）     │
└─────────────────────────────────────────────────────────────────────────────┘
       状态机：pending → analyzing → analyzed → reviewing → approved
       → plan → testplan → code → test → quality → security → released（终态）
      （状态机全部确定性逻辑集中在 scripts/statectl.py，flock 串行化）
```

## 目录结构

```
zteam/                      # 资产层（git 跟踪，uninstall --full 保留）
├── roles/pm.md se.md te.md mde.md fo.md mto.md sto.md qa.md  # v2 八角色
├── roles/bot.md                     # zbot 职责（gateway 注入）
├── roles/req-reviewer.md      # 需求评审师角色定义 + 12 项评审检查清单
├── roles/bot.md               # zbot（Telegram bot）职责边界与人格定义（install 注入 gateway，uninstall 移除）
├── scripts/                   # statectl.py（状态机唯一实现）+ bot_config.py + watchdog-*.py 上半部入口
├── docs/                      # state-machine.md（状态机定义）+ troubleshooting.md（问题定位）
├── AGENTS.md                  # 流水线约定（下半部 worker 自动加载）
└── workspace/                 # 数据层（按项目分层；uninstall --full 清空对象）
    ├── <项目名>/              # 每个项目一个文件夹（首次投放需求时自动创建）
    │   ├── status.json        # 该项目状态机（唯一事实来源；key = <项目>/<req_id>）
    │   ├── status.lock        # 该项目 flock 锁（项目间并发、同项目串行）
    │   ├── input/             # 该项目需求投放区（一个文件一个需求）
    │   ├── analysis/ review/  # 需求分析与评审（只留最新轮，历史进 archive/）
    │   ├── plans/ testplans/ code/ tests/   # 阶段链产物（代码/测试为文件集目录）
    │   ├── quality/ security/ release/      # 门禁结论 / 交付包（发布说明+指南+tar.gz+校验和）
    │   ├── artifacts/         # 归档（结论摘要 + 各阶段终版 + 评审历史）
    │   ├── archive/           # 历史轮次归档
    │   └── logs/              # 该项目 worker 日志
    └── logs/                  # 全局日志（pipeline.log 审计流 + alarms.txt）
```

## 快速开始（3 步）

1. **投放需求**：把需求原文放入 `workspace/<项目名>/input/req-001.md`（项目目录不存在会自动创建；可一次放多个；上半部脚本会自动登记）；
2. **创建 cron job**（全部 `no_agent` 纯脚本，不需要模型；**推荐直接用 `bash install.sh` 一键创建，见下节**）：

```bash
# 前提：CLI 只接受 $HERMES_HOME/scripts/（默认 ~/.hermes/scripts/）下的真实文件（软链会被拒绝），
# 因此先建 2 行 exec 薄壳（本流水线已建好，逻辑唯一实现在工作区）：
#   $HERMES_HOME/scripts/watchdog-analyst.sh   -> exec python3 <工作区>/scripts/watchdog-analyst.py
#   $HERMES_HOME/scripts/watchdog-reviewer.sh  -> exec python3 <工作区>/scripts/watchdog-reviewer.py
#   $HERMES_HOME/scripts/watchdog-worker.sh    -> exec python3 <工作区>/scripts/watchdog-worker.py
#   $HERMES_HOME/scripts/watchdog-weekly.sh    -> exec python3 <工作区>/scripts/watchdog-weekly.py
#   $HERMES_HOME/scripts/watchdog-notify.sh    -> exec python3 <工作区>/scripts/watchdog-notify.py

hermes cron create "*/5 * * * *" --name req-analyst-top  --script watchdog-analyst.sh  --no-agent --repeat 0
hermes cron create "*/5 * * * *" --name req-reviewer-top --script watchdog-reviewer.sh --no-agent --repeat 0
hermes cron create "0 9 * * 1"   --name req-weekly-audit --script watchdog-weekly.sh   --no-agent --repeat 0
```

> 注意：调度请用 cron 表达式（`"5m"` 会被解析成一次性任务）；`--repeat 0` = 无限循环；**job 只有在 gateway 运行时才会自动触发**（`hermes cron status` 查看；未运行时输出仍会被保存但不投递）。

3. **查看结果**：`jq . workspace/status.json` 看流转；`ls workspace/artifacts/` 看终版；`tail workspace/logs/pipeline.log` 看审计；**有问题先跑 `python3 scripts/statectl.py diagnose`**（问题定位见 `docs/troubleshooting.md`）。

> 替代方案：**第 2 步可直接用一键脚本** `bash install.sh` 完成（幂等，可重复执行），见下节。

## 安装与卸载

```bash
bash install.sh                        # 一键安装/修复（幂等）：目录骨架 + cron 薄壳 + 4 个 job + zbot 职责注入 + 自检；zbot 配置变更时自动重启 gateway（REQREVIEW_NO_RESTART=1 跳过）
bash install.sh --with-gateway         # 干净机器一键到位：gateway 未运行则自动安装并启动
bash uninstall.sh                      # 卸载：移除 4 个 job + 薄壳 + zbot 职责配置，【保留全部数据】
bash uninstall.sh --full               # 清空数据层 workspace/（全部项目数据），项目资产与 git 历史保留（交互输入 yes；agent 场景用 REQREVIEW_FULL_YES=1 免交互）
```

### 干净机器完整流程（新机器 / 迁移）

1. **安装 Hermes**（唯一前置，install.sh 不代劳——它本身就是 Hermes 上的流水线）：
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
   hermes --version    # 确认 CLI 可用
   ```
2. **拷贝工作区**：把整个 `zteam/` 目录拷到目标机任意路径（路径随意，脚本自动适配；迁移后必须重跑 install 以按新路径重建薄壳）：
   ```bash
   scp -r zteam/ user@host:~/
   ```
3. **一键安装（含 gateway 自启）**：
   ```bash
   cd <工作区> && bash install.sh --with-gateway
   ```
   该命令幂等完成：目录骨架 → cron 薄壳（按当前路径生成）→ 3 个 cron job → gateway 未运行则自动安装启动（用户级 systemd 服务，开机自启）→ 末尾自动 `diagnose` 自检，全绿才 exit 0。
4. **验证**：
   ```bash
   hermes cron status                    # 应见 "Gateway is running" + 3 active jobs
   python3 scripts/statectl.py diagnose  # 应见 0 严重问题 / 0 警告
   # 可选端到端验证（消耗少量 token）：投放一个测试需求并立即触发
   cp 测试需求.md workspace/<项目名>/input/test-install.md && hermes cron run req-worker-top
   python3 scripts/statectl.py list      # 应见 analyzing → analyzed
   ```
5. **场景差异说明**：
   - **未装 Hermes** → install.sh 明确报错并给出第 1 步的安装命令（exit 1，无副作用）；
   - **已装但 gateway 未启动** → 不加参数会警告 + exit 1（job 照常建好但不触发）；加 `--with-gateway` 自动解决；
   - **无 systemd 环境**（WSL/Docker 等）→ `--with-gateway` 自动启动失败时会提示手动方案（`hermes gateway run` 前台 / `sudo hermes gateway install --system`），不会静默假装成功。

- **install 幂等**：重复执行只会补齐缺失项（已存在则跳过），末尾自动跑 `diagnose` 自检；**工作区迁移后重跑 install 即可**（薄壳按当前路径重新生成）；
- **uninstall 默认安全**：只拆 cron job 与 `$HERMES_HOME/scripts/` 薄壳，`workspace/status.json`/产物/日志原样保留；`--full` 才删数据且有确认；
- 两者都**不碰 gateway**（它同时服务 Hermes 其他功能）。

## v2 模块中心（八角色）

| 角色 | 职责 |
|---|---|
| PM | 需求导入与细化（麦肯锡+联网）→ 用户评审（confirm/reject 拍板）|
| SE | 版本级架构设计 + 模块组织/需求分发/迭代计划（PM 评审）|
| TE | 整体测试方案（IT/ST）+ 测试套件框架（SE 评审）|
| MDE | 功能模块设计（SE 评审）+ 模块代码检视 |
| FO | TDD 开发（代码+UT 自闭环；检视门禁；问题单修复）|
| MTO | 模块 IT（用例 TE 评审→测试代码→报告+问题单）|
| STO | 版本 ST（用例 TE 评审→端到端测试+问题单）|
| QA | 报告评审（实现率/通过率/覆盖率）+ 安全红线 + 用户指南（用户评审）→ release 包 |

流程：需求请求（input 草稿）→ PM 细化 → 用户评审 → 规格锁定 → SE 架构 → TE 方案 →
模块迭代（MDE→FO→MTO，迭代内无依赖并行/依赖串行，模块跨迭代）→ STO 版本 ST →
QA 发布（用户指南用户确认）→ 版本 released（同项目版本串行）。
详细设计见 docs/v2-工程分层模型设计.md。

- **解除阻塞**：`module {项目} unblock {模块} {迭代}` / `unblock {项目} {版本}`；资源限制 blocked 配额恢复后自动恢复

## 模型配置

**绑定位置**：不在 cron 配置里，而在 `scripts/statectl.py` 的 **ROLE_MODELS 映射**（worker spawn 时经 `hermes chat -q -m <model> --provider <provider>` 传入）。每角色独立模型，改模型只需改常量/映射，无需重建 cron job。

| 角色 | 常量（环境变量可覆盖） | 当前值 | 说明 |
|------|------------------------|--------|------|
| ~~需求分析师~~（v1 退役）→ **PM** | `ANALYST_MODEL` / `ANALYST_PROVIDER` | `deepseek-v4-flash` / `deepseek` | 产出类（快/便宜） |
| **PM / SE / TE**（v2） | `PM_MODEL`/`SE_MODEL`/`TE_MODEL` | `deepseek-v4-pro` / `deepseek` | 强推理（规格/架构/方案） |
| **FO**（v2，TDD 开发） | `FO_MODEL`/`FO_PROVIDER` | `MiniMax-M3` / `minimax-cn` | 用户指定（受 5h 窗口配额，资源感知自动恢复） |
| **MDE / MTO / STO**（v2） | 复用 CODE/TEST/ST 角色常量 | `deepseek-v4-flash` / `deepseek` | 产出类（快/便宜） |
| **QA**（v2，发布终审） | `QUALITY_REVIEWER_MODEL` | `deepseek-v4-pro` / `deepseek` | 评审把关 |
| 需求评审师 | `REVIEWER_MODEL` / `REVIEWER_PROVIDER` | `deepseek-v4-pro` / `deepseek` | 评审类（强推理，把关） |
| 方案设计/评审 | `PLAN_DESIGNER_MODEL` / `PLAN_REVIEWER_MODEL` | `deepseek-v4-flash` / `deepseek-v4-pro` | 产出+评审 |
| 测试方案设计/评审 | `TESTPLAN_DESIGNER_MODEL` / `TESTPLAN_REVIEWER_MODEL` | `deepseek-v4-flash` / `deepseek-v4-pro` | 产出+评审 |
| **code 阶段** | `CODE_DEVELOPER_MODEL` / `CODE_REVIEWER_MODEL` / `CODE_PROVIDER` | `MiniMax-M3` / `MiniMax-M3` / `minimax-cn` | 产出+评审均 M3 |
| **test 阶段** | `TEST_DEVELOPER_MODEL` / `TEST_REVIEWER_MODEL` / `TEST_PROVIDER` | `MiniMax-M3` / `MiniMax-M3` / `minimax-cn` | 产出+评审均 M3 |
| 质量/安全门禁 | `QUALITY_REVIEWER_MODEL` / `SECURITY_REVIEWER_MODEL` | `deepseek-v4-pro` | 把关/红线 |
| 发布者 | `RELEASER_MODEL` | `deepseek-v4-flash` | 打包交付 |

**改模型两种方式**：
1. **直接改常量/映射（推荐）**：编辑 `scripts/statectl.py` 模型常量区（约 185–235 行）即可，立即生效；
2. **环境变量覆盖**：上表常量同名环境变量优先。⚠️ **坑**：cron job 由 gateway（systemd 服务）执行，交互 shell 里 `export` 的变量**到不了 gateway 进程**——环境变量覆盖只对手动运行（`python3 scripts/statectl.py ...`）生效；要让 gateway 场景也走环境变量，需 `systemctl --user edit hermes-gateway` 在 `[Service]` 下加 `Environment=CODE_DEVELOPER_MODEL=...` 再 `hermes gateway restart`。

**验证生效**：`tail workspace/logs/pipeline.log` 中 `SPAWN` 行带实际模型（`... model=MiniMax-M3 ...` / `... model=deepseek-v4-flash ...`）。

> 可用模型以上游 API 实际返回为准；当前配置组合：DeepSeek（`deepseek-v4-flash`/`deepseek-v4-pro`，api.deepseek.com）+ MiniMax（`MiniMax-M3`，minimax-cn 中国站，KEY=MINIMAX_CN_API_KEY）+ Kimi（kimi-coding-cn，KEY=KIMI_CN_API_KEY，备用未启用）。

## 关键限制与对策

- **cron 3 分钟硬中断** → 上半部只做秒级唤醒，耗时活全部在下半部独立进程完成（`setsid` 脱离 cron 会话，进程级持久）；
- **双 job 竞态/并发** → 全局锁注册 + 项目级 flock 锁（workspace/<项目>/status.lock）——不同项目并行、同项目串行；中间态原子认领（compare-and-swap）+ claim 防重复；
- **worker 崩溃** → 上半部 stale 恢复（`kill -0` 存活检查 + 超时回滚 + failures 计数），2 次后 `blocked` + 告警推送；
- **worker 漏设状态/卡死循环** → 巡检兜底（guard_recovery）：超时后按产物存在性/评审结论自动补正（PASS→done / FAIL→重做 / 无产物→回滚），GUARD 审计留痕，无需人工；
- **模型质量上限** → 检查清单逐条可勾选，主观判断最小化。
- **job 冗余（已知）**：`req-analyst-top`/`req-reviewer-top` 与 `req-worker-top` 调度重叠（后者已覆盖全阶段认领），保留为兼容/冗余调度，暂不合并。

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
- **投放**："我有个新需求：<内容>" → 自动写入 `workspace/<项目名>/input/`（起合法 req_id）；
- **查询**："需求进度" / "req-003 状态" → 状态摘要回复；
- **干预**："requeue req-003" / "rollback req-003" / "跑下诊断"；
- 结果随时可问，或等通道②推送。

### zbot 职责约束（严格模式）
zbot 是**流水线专属助手**：只处理投放/查询/干预/汇报，其他请求（闲聊、通用问答、编程等）一律拒绝。
- **单一事实来源**：`roles/bot.md`（职责边界 + 人格定义）；
- **注入机制**：`install.sh` 把 `roles/bot.md` 内容写入 `$HERMES_HOME/gateway.json` 的 `platforms.telegram.channel_overrides[<chat_id>].system_prompt`（频道级提示词，追加不覆盖默认能力；用 gateway.json 而非 config.yaml 是因为后者注释会被重写丢失）；
- **生效**：改 `roles/bot.md` 后重跑 `python3 scripts/bot_config.py install` + `systemctl --user restart hermes-gateway`；
- **卸载**：`uninstall.sh` 自动移除该配置（gateway.json 空壳自清理）；手动：`python3 scripts/bot_config.py uninstall`。

### 前置步骤（一次性，需要你操作）
1. Telegram 里找 **@BotFather** → `/newbot` → 拿到 bot token；
2. 配置（二选一）：
   - 交互式：`hermes gateway setup` 按向导填写；
   - 手动：token 写入 `$HERMES_HOME/.env` 的 `TELEGRAM_BOT_TOKEN=`（建议同时设 `TELEGRAM_ALLOWED_USERS`（你的用户 ID，限制只响应你）与 `TELEGRAM_HOME_CHANNEL`（目标 chat id，投递落点））；
3. `hermes gateway restart`；
4. **给 bot 发一条消息**（建立会话、确认 home channel）；
5. 验证：`hermes cron run req-result-notify`——最近有归档会收到推送；无消息 = 正常（空输出不推送）。

> install.sh 默认所有 job `deliver=telegram`（告警/结果自动推送，tick 脚本无活静默不会刷屏）；纯本地模式用 `REQREVIEW_DELIVER=local bash install.sh` 覆盖。**已存在的 job 若 deliver 不符，重跑 install.sh 会自动校正**（2026-08-08 修复：此前默认 local 导致结果不推送）。

### 当前状态（2026-08-07 实测）
- ✅ **四通道全部打通**：①告警推送 ②结果推送 ③聊天查询/干预 ④聊天投放需求——均已实证可用
- ✅ **zbot 职责约束已生效**（2026-08-07 用户实测）：严格模式——只处理流水线操作，越界请求（闲聊/通用问答等）一律拒绝；定义在 `roles/bot.md`，install/uninstall 自动注入/移除（gateway.json channel_overrides）
- ✅ 配置：`TELEGRAM_BOT_TOKEN`（有效，@zyzs_bot）、`TELEGRAM_ALLOWED_USERS=6525650097`、`TELEGRAM_HOME_CHANNEL=6525650097`（DM 落点）均在 `$HERMES_HOME/.env`
- ✅ 4 个 cron job 均 `deliver=telegram`；notify 推送链路两次端到端实证全送达（即使执行时适配器刚经历重连，网络恢复即投递成功）
- ✅ 退出 TUI 会话后依然可用——常驻 gateway 为 systemd 服务（`hermes-gateway.service`），与终端会话无关
- ⚠️ 已知边界：Telegram 适配器（Hermes 内置）对网络波动恢复慢（首次连接可能卡 "attempt 1/8" 数分钟～数小时，#63309 家族）；期间聊天/推送可能短暂无响应，网络恢复后自动重连。clash 节点不稳定是外部根因。**不构成功能缺口**（实测推送会送达，只是可能延迟）
- ⚠️ 环境：gateway systemd drop-in（`~/.config/systemd/user/hermes-gateway.service.d/override.conf`）置空 `http_proxy`/`https_proxy`——适配器直连走 clash TUN（fake-IP），实测优于走 7890 HTTP 代理（后者会触发适配器挂起）
- 投递落点：`deliver=telegram` 在触发时解析到配置的 home channel（= 用户私聊）

## 使用注意事项

### 版本管理（git，防误删/误改）
工作区是 git 仓库（2026-08-07 初始化，首提交含全部核心资产 + 业务数据）。
- **远程备份**：`git@github.com:chenyuxiangg/zteam.git`（`origin`，SSH 免密；新机器恢复：`git clone git@github.com:chenyuxiangg/zteam.git <工作区>`）；
- **日常提交**（推荐每次改动后）：
  ```bash
  cd <工作区> && git add -A && git commit -m "描述改动" && git push
  ```
- **误删恢复**：`git checkout -- .`（恢复所有改动）/ `git restore <文件>`（恢复单个）；
- **回滚到某次提交**：`git log --oneline` 查版本号 → `git reset --hard <版本号>`（谨慎，丢弃之后改动）；
- **忽略项**：`workspace/logs/`、`workspace/**/logs/`、`__pycache__/`、`*.lock`（运行噪音，不入库）；`workspace/<项目>/status.json`、`workspace/<项目>/input/` 等业务数据全部入库；
- **教训**：2026-08-07 工作区曾被旧版 `uninstall.sh --full`（删除整个工作区）误删，靠会话 DB 重建——现 `--full` 已改为只清空数据层 workspace/、保留项目资产；纳入 git 后即使误删也可 `git restore` 秒级恢复。


- 投放唯一入口是 `workspace/<项目>/input/`；一个 `.md` = 一个需求，**文件名即需求 ID**（仅允许 `[A-Za-z0-9_-]`）；
- **归档快速阅读**：`workspace/artifacts/<project>/{req_id}.md` 头部「结论摘要」区 = 最终结论（状态/最终轮次/分析路径/评审历史），接手开发以【原文 + 最终分析 + 最后一轮评审】为准，前面轮次评审意见是过程记录；
- **改内容不改文件名不会触发重新分析**——重跑用 `python3 scripts/statectl.py requeue <req_id>`（从失败阶段续跑，已通过阶段不重跑，省 token）；
- **人工补记产物**（评审已过但 product 漏记）：`python3 scripts/statectl.py record_product <req_id> <stage> <产物路径>`（校验存在，合规替代手改 status.json）；
- **手动暂停/恢复流水线**（异常排查时防 token 消耗）：`python3 scripts/statectl.py halt [原因]` / `unhalt`（touch/删 `workspace/.pause` 标记，tick 整体跳过调度；已运行 worker 不受影响；**halt 是唯一暂停方式**——`hermes cron pause` 会被 cron guard 自动恢复）
- 删除 `workspace/<项目>/input/` 文件不会清理状态条目（历史保留）；
- 非 `.md` 文件忽略；一个文件放多个需求会被当作一个需求处理；
- 完整边界行为表见 `docs/state-machine.md` §9.1。

## 设计文档索引

- 角色：`roles/req-analyst.md`（产品视角·麦肯锡方法论）、`roles/req-reviewer.md`（12 项检查清单）、`roles/bot.md`（zbot 职责，install/uninstall 自动注入/移除）
- 状态机（含上下半部调度架构）：`docs/state-machine.md`
- **问题定位指南（DFx）**：`docs/troubleshooting.md`
- 流水线约定（下半部加载）：`AGENTS.md`
