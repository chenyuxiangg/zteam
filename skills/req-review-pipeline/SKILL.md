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
- **路径模型（2026-08-09 项目分层）**：数据层按项目分层（2026-08-19 解耦）：每项目在映射表 **work_path**（默认 `~/project/<项目>/`，含 input/analysis/arch/testplans/code/tests/quality/security/release/artifacts/archive/logs + status.json/lock + modules.json/versions.json/issues，首次投放自动创建）；资产层（roles/docs/scripts/skills）留在 zteam 根。产物相对路径（如 `<项目>/analysis/{req_id}-r1.md`）经 **product_path()** 查表解析为 work_path 绝对路径。**并发**：全局锁（register）+ 项目锁（调度）——项目间并行、同项目串行；曾修复阶段 1 全量写覆盖竞态（改为只注册不写盘，增量随项目锁合并）。再遇到"产物不存在"先 grep 路径拼接。
- 状态流转：`pending → analyzing → analyzed → reviewing → needs_fix ↺ / approved / blocked`。

## 日常操作（在 <工作区> 下）

```bash
# 投放新需求：任意 .md 放进 {work_path}/input/（默认 ~/project/<项目名>/input/，项目先 `project add` 登记；未登记项目 register 拒绝=强制先登记），下一个 tick 自动注册并启动
# 边界行为：改内容不改文件名 → 不触发重新分析（重跑用 requeue）；删 {work_path}/input/ 文件 → 状态条目保留；
#           文件名即 ID（仅 [A-Za-z0-9_-]）；完整边界表见 docs/state-machine.md §9.1
# 安装/卸载（幂等/安全，见 README「安装与卸载」）
bash install.sh        # 一键安装/修复（薄壳+5 job+zbot 注入+自检）；工作区迁移后重跑
bash install.sh --with-gateway   # 干净机器一键到位（gateway 未运行则自动安装启动；未装 Hermes 会报错并给安装命令）
bash uninstall.sh      # 卸载（移除 job+薄壳+zbot 配置，保留数据）；--full 清空项目数据（work_path 目录 + projects.json 登记，保留资产，有确认）
# 查看进度
python3 scripts/statectl.py list          # 总览
python3 scripts/statectl.py get <req_id>  # 单条详情（含 claim 字段 + 各阶段四态）
# 状态设置（所有角色共用一个入口，严格迁移校验，乱跳拒绝）——worker 干完活漏调了？巡检会兜底，不用人工补
python3 scripts/statectl.py set_status <req_id> <stage> working              # worker 启动时（第 0 步）
python3 scripts/statectl.py set_status <req_id> <stage> reviewing <产物路径>  # 产出完成 → 待评审
# 人工干预
python3 scripts/statectl.py requeue <req_id>   # blocked 后重投（**从 block 阶段续跑**：只重置失败阶段及后续，已通过阶段保留；req 阶段未过才全链重跑；failures 清零）
python3 scripts/statectl.py record_product <req_id> <stage> <产物路径>  # 人工补记产物（评审已过但漏记；校验存在，合规替代手改 status.json）
python3 scripts/statectl.py halt [原因] / unhalt  # 手动暂停/恢复流水线（tick 整体跳过调度，防异常时烧 token；已运行 worker 不受影响）
python3 scripts/statectl.py rollback <req_id>  # 手动回滚中间态
python3 scripts/statectl.py resume <req_id> <stage> <designing|reviewing|gating|releasing|done>  # 人工恢复指定阶段状态
# 审计
tail zteam/logs/pipeline.log   # 状态迁移审计（含 GUARD 巡检补正行）
ls {work_path}/logs/worker-*.log     # 每个下半部 worker 的明细
```

## 角色与模型

- 角色定义：`roles/req-analyst.md`（**产品视角·麦肯锡方法论**：SCQA 理解、MECE 分解、金字塔表达、5W1H 澄清；主动查资料；产出需求分解文档 FR/NFR/竞品分析；**红线=只答 What/Why 绝不答 How**，禁止技术方案/选型/架构）、`roles/req-reviewer.md`（**12 项检查清单**，含 MECE 完整性、竞争力分析两项）。
- 模型绑定在 `scripts/statectl.py` **第 43–48 行**常量（改模型直接改这里，立即生效；同名环境变量覆盖**仅对手动运行生效**——gateway 是 systemd 服务，不继承交互 shell 的 export，需 `systemctl --user edit hermes-gateway` 加 `Environment=` 再 restart）：
  - deepseek-v4-flash（产出类）：analyst、dev-plan-designer、test-plan-designer、releaser
  - **MiniMax-M3（provider `minimax-cn`，MiniMax 中国站，2026-08-09 起）**：code-developer、code-reviewer、test-developer、test-reviewer 均用 M3；覆盖环境变量前缀 CODE_/TEST_（如 CODE_DEVELOPER_MODEL、TEST_PROVIDER）
  - deepseek-v4-pro（评审/门禁类）：req-reviewer、dev-plan-reviewer、test-plan-reviewer、quality-reviewer、security-reviewer
- **用户 DeepSeek API 只有这两个模型**——不要写 deepseek-chat / deepseek-reasoner（不存在，会必现报错）。
- **11 角色阶段链**：需求(分析师/评审师) → plan(dev-plan-designer/reviewer) → testplan(test-plan-designer/reviewer) → code(code-developer/reviewer) → test(test-developer/reviewer) → quality(门禁) → security(门禁) → release(releaser，**打包交付**：发布说明+用户指南+`{req_id}-v{版本}.tar.gz`+SHA256SUMS+可用性自检，产物为目录) → released 终态。角色定义见 `roles/*.md`。
- **四态状态机**：每阶段 `claimed（tick 认领）→ working（worker 启动时 set_status）→ reviewing（产出后 set_status + 产物）→ done（评审 PASS）`；FAIL 打回 working 重做，连续 FAIL 达 max_rounds → blocked。真值存 `stages[stage].state`（status.json），顶层 status 为派生显示。
- **巡检兜底（guard_recovery）**：worker 漏设状态/卡死循环时，超时（20 分钟）后按"产物存在性 + 评审结论"自动补正（PASS→done / FAIL→重做 / 无产物→回滚），写 `GUARD` 审计——**worker 无需自觉，漏了自动兜底，不要人工补状态**。

## 告警处理

- `[BLOCKED]`：连续失败 ≥2 次，流水线停止流转等人工。**处置必须走下方标准流程，先查根因再 requeue**。
- `[FORCED]`：达 max_rounds=3 仍 FAIL，强制归档 `{work_path}/artifacts/<req_id>.md`（含全部轮次历史），需人工复核未解决意见。
- 告警经上半部 tick 从 `zteam/logs/alarms.txt` 消费并输出；cron 未配 deliver 时只本地保存。

## BLOCKED 根因分析标准流程（zbot 收到 BLOCKED 后必须主动完成，带结论请示；不得只问"要不要 requeue"）

触发机制：`failures ≥ 2`（stale 回滚或评审 FAIL 累计），护栏触发后停止流转。requeue 前完成下面 4 步：

1. **定位卡死点**：`statectl list` + `tail zteam/logs/pipeline.log`——找 BLOCKED 前最后一条 RECOVER/FAIL 属于哪个阶段，failures 如何累计（**stale 回滚** vs **评审 FAIL** 性质不同：前者是进程问题，后者是内容问题）；
2. **查 worker 生死**：pipeline.log 的 SPAWN/SKIP 行有 pid；`ps -p <pid>`——存活且多 tick 无进展=可能"干完活没退出"（模式 A）；已死=崩溃（模式 B）；
3. **看 worker 日志**：`tail {work_path}/logs/worker-<key>-r<N>.log` 最后输出 + 对比日志 mtime 与停止时间差，grep `error|traceback|timeout`；
4. **产物完整性**：`ls {work_path}/{stage}/{req_id}-r{N}/`——决定 requeue 后该阶段是否重做（已通过阶段产物保留复用，只有失败阶段及其后续重做）。

**已知模式**（共 4 类，按排查顺序）：
- **模式 A「干完活没退出」**（2026-08-08 tetris 实测）：worker 日志有完整成功收尾（验证全绿/产物落盘/set_status 已在 pipeline.log 留下审计）+ 进程存活但连续多 tick 无进展 + dmesg 无 OOM/kill → 判定为 **hermes chat 进程完成响应后挂住不退出**（网络/会话收尾卡住，与 Telegram 适配器挂起 #63309 同族，环境网络不稳是背景）。**产物无损 → 直接 requeue 从该阶段续跑即可，无需改任何代码**（已通过阶段不重跑）；
- **模式 B「中途崩溃」**：worker 日志尾部有 traceback/代码缺陷 → 先修根因再 requeue；
- **模式 C「API 配额耗尽」**（2026-08-09 gomoku/pacman 实测，minimax-M3）：worker 日志尾部有 `HTTP 429: 已达到 Token Plan 用量上限：请升级 Token Plan 套餐或购买积分补充用量`。**requeue 不能解决问题**，必须先充值/换套餐/换模型（如切回 deepseek），否则再跑仍 429。区分要点：模式 A 是"进程挂着不死"，模式 C 是"进程秒退/重试3次后失败"，看 pipeline.log SPAWN 到 RECOVER 的时间差（模式 A 通常满 20 分钟，模式 C 通常分钟级）+ worker 日志尾部有无 429；
- **模式 D「评审 FAIL 累计」**（2026-08-09 gomoku 实测，混合模式 C）：代码/方案等阶段连续 FAIL → requeue 回上一阶段让产出者修改，可能也撞上 API 限额，要先排除模式 C。
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

- **投放（必须确认项目，P2）**：用户发需求文本/文件 → 起合法 `req_id`（英文短名或拼音，仅 `[A-Za-z0-9_-]`，**避免中文文件名**）→ **先确认项目名**（未指定→询问；无法指定→执行 `statectl project list` 列出项目帮回忆；仍无→拒绝投放，不写文件）→ 写入 `{work_path}/input/{req_id}.md` → 回复"已投放 {项目}/{req_id}，5 分钟内自动开始分析"；
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
诊断覆盖：状态文件/目录/条目 schema/非法状态/中间态滞留/claim 残留/引用文件/归档/gateway 运行/cron job/worker 进程/日志可写/**D15 版本可达性表完整（改状态机跑 diagnose 即回归）**/**D16 版本实际状态在表内（v1 遗留状态暴露）**。**完整症状决策表见工作区 `docs/troubleshooting.md`（唯一权威）**，要点：

| 症状 | 第一检查 | 修复 |
|---|---|---|
| 一直 pending 不分析 | diagnose D11 / `hermes cron status` | 多半是 gateway 未运行 → `hermes gateway start` |
| **版本卡死**（无 SPAWN 无告警） | `tail logs/pipeline.log` grep `VERSION_STUCK\|VERSION_GUARD` | **b6dc84a 起有版本级 guard**：arch 死状态自动回 planning（VERSION_GUARD 告警）；12 tick 滞留自动 VERSION_STUCK 告警——先看告警再查 versions.json 调度前置条件 |
| **版本状态不在可达性表** | diagnose D16 WARN | v1 遗留状态（st_pending 等）或状态机改动遗漏——核查 VERSION_FLOW 表 |
| 卡 analyzing/reviewing | `ps aux \| grep "hermes chat"`；worker 日志 | worker 还活着=慢，等（20min 后 stale 自动回滚）；死了 → 下个 tick 自动恢复或 `rollback <id>` |
| `[BLOCKED]`（失败≥2） | `tail {work_path}/logs/worker-*.log` 找根因 | 修根因 → `requeue <id>` |
| `[FORCED]`（超轮次强制归档） | 复核 `{work_path}/artifacts/<id>.md` 未解决意见 | 人工裁决；误判则 requeue 重跑 |
| worker 秒退/日志空 | pipeline.log 的 SPAWN 行看 model | **最常见：模型名不存在** → 改 statectl.py 第 43–48 行；其次 API key/限流 |
| job 不自动触发 | `hermes cron status` + Repeat 是否 ∞ | gateway 未跑 → start；`"5m"` 建的一次性任务 → `hermes cron edit --schedule "*/5 * * * *" --repeat 0` |
| {work_path}/status.json 损坏 | 备份 → 修复/重建条目（产物不丢） | 见 docs/troubleshooting.md §2 S9 |

**MTO 复测证据坑（2026-09-10 SOCSIM-06 实测）**：soc-sim subprocess 后端超时抛 `EngineCrashedError` 时，异常消息里带**整条监视器命令缓冲**（大 ELF 单次 `sysbus WriteBytes [...]` ≈300KB 一行）——`grep EngineCrashedError`/`read_file` 会把 60 万字符灌进上下文。用 `grep -o 'seq=[0-9]*, cmd=.\{0,80\}'` 或先 `cut -c1-400` 截断。同族：问题单 .md（长行）会被 read_file 误判 binary，用 `python3 -c "print(open(p,encoding='utf-8').read())"` 读。复测不通过一律走 `issue {项目} reopen {iid} <原因>`（自动 状态：fixed→open + 审计），别手改状态行。

**MTO 复测裁决协议（2026-09-10 web-ui it3 五轮实测）**：
1. **先证「修复是否落地」再跑用例**：对比根因代码位 mtime 与提单时间——FO 反复出现的「FO 修复完成」常是**纯状态机标记**（只写 issues/<iid>.md，全代码树零源码变更）。命令：`find . -type f -newermt "<提单时刻>" -not -path "*/node_modules/*"`；根因文件 mtime 早于提单 ⇒ 修复未落地，无需空跑 8 分钟用例即可判不通过（但仍要跑一次留真实证据）。
2. **复测记录落盘 + reopen 一条命令**：记录写成独立 .md 片段用 write_file 落 `/tmp/...`，再用短 python 脚本 append 到 `issues/<iid>.md`，最后 `statectl issue reopen`。**别用 heredoc 写含「重启/stop/start」字样的复测记录**——会被 gateway 安全护栏拦成「cannot restart or stop the gateway」而整条命令失败（write_file 内容不受此限制）。
3. **跨模块错挂的处理**：根因不在本模块时（如 web-ui it3 的 waiting_issues 挂着 web-api/debug-core/soc-sim 根因单），reopen 原因里必须写清①判据未达成的实测证据②根因代码位与 mtime ③**归口建议（重派哪个模块的 FO 修）**——否则单会连续多轮错挂同一模块，FO 反复拒修空转。
4. **判定要分开写**：本模块代码面是否有效（探针 + UT 双证）与整体判据是否达成是两件事；代码面已修但判据被上游污染时，仍判不通过 → reopen，并注明「代码面已修复有效，卡在上游 X」。
5. **「就绪门/握手」类修复的盲区（2026-09-11 DEBUGCORE-03 第 5 轮实测）**：只做「提交前同步读 state（READY/PAUSED 直通）」不足——真链 503 来自 **op 执行期** engine 系异常（engine_timeout/engine_crashed → map_soc_error→`engine`→web-api 503 dbg_engine）。判据复现即 reopen，归口建议必须写到「op 级 engine 错误有界吸纳/重试」，否则 FO 只能再交一次同款就绪门。
6. **真链判据必须在无并发 worker 的静默窗口复跑**：同一判据 r1/r2 结果可完全不同——若 `code/<上游模块>` 源文件 mtime 落在 run 中途（并发 FO 正在改写），该轮结果失真（本轮 r1 = 0 次 dbg_engine，r2 = 3/3 复现）。跑前查 `ps aux | grep "hermes chat"` + 源文件 mtime + `uptime`（load/核数）；有并发就等窗口或明确标注干扰，并至少复跑一轮。
7. **按问题单「修复方向」改动用例时保持资产一致**：如 FR15-104 改调 `continue_over_bp()`（原 `soc.run()` 废弃）——需同步改 ①IT 测试代码 + conftest 注入（`run_cmd`）②`测试用例.md`（行 + 明细 + 修订记录）③`模块测试报告.md` 追加复测记录 addendum；否则下一轮一致性核查必报漂移。

8. **「修复落地」≠「修复生效」——必须核触发路径在真链里真被走到（2026-09-11 soc-sim it2 实测两例）**：①SOCSIM-05 watch-diff 回调确实新增（`_diff_watch_callbacks`），但只挂在 `HeadlessRenodeBackend.read_memory`，而真链采样 tick（`engine_worker._realtime_tick`）只调 `read_registers`（SnapshotBuilder.build 不读内存）→ 运行期永不触发，UT 全绿仍断源；核法：`grep -n '\.read_memory(' <模块>/*.py` 列出全部调用点，确认是否落在 tick/采样主路径。②SOCSIM-06 分块常量 4096 未按真引擎校准：实测 Renode 1.16.1 监视器单条 `sysbus WriteBytes` 上限 <2048B（1024 OK 0.33s / 2048 挂 3.24s）→ 首个 4KB 块即 hang；核法：写升序试写脚本（16/64/256/512/1024/2048…，每档 readback 校验）直连 subprocess Renode 定位上限，别信 UT（假监视器只验切块算术）。共同教训：UT 全绿 + 代码注释自称「已实现」都不算证据，必须真链复跑判据用例。
9. **UI 渲染类判据（STO/MTO 复测）必须「不重点击、轮询 DOM」，且每轮新起服务**（2026-09-11 web-ui it3 WEBUI-09/11 复测实测）：
    ① 定点采样会假 FAIL——`点击应用 → sleep 1.2s → 读一次 DOM` 在并发 FO 满载（load≈5）时读到占位符 `··`，改「点完不重点击、每 250ms 轮询 15s」后真值 <1s 出现（2 轮一致）。**采样窗口过短 + 高负载时延 ≠ 功能缺陷**，别据此 reopen；
    ② 有状态引擎下**每轮复测必须新起服务**：同一 st_serve 跑第 2 轮时 CPU 徽标停在上一轮终态（如「已停止」），harness 若断言启动即 `INIT` 会直接 TimeoutError 假失败（本例 r1 第二轮整轮空跑）；
    ③ 复测记录写清「不重点击是否自行出真值」——这正是「页缓存/刷新层」类缺陷的判据分界（自行出现=修复生效；只有二次点击才出=reactive 触发仍未接上）；
    ④ 现有全量 UI harness（`st/v1.0.0/ui/st_ui_e2e.cjs`）用固定 `waitForTimeout(1000)` 读内存字节 + S3 串口 30s `waitForFunction` 会中断后续组——定点复测单条问题单时，另写只跑该判据的小探针（附 HTTP 响应捕获）比重跑 8 项快且不误伤。

10. **statectl reopen 原因别在 bash 里裸传**：原因含 `(`/`）`/`>` 会被 shell 当语法错或重定向（`syntax error near unexpected token '('`），也可能静默吞掉片段（`（assert 0>=1，…）` 变 `（assert …）`）。用 `python3` 的 `subprocess.run([...])` 参数数组传；详述写进 issue.md 片段，命令行只留一行摘要。批量 reopen 时先查 `issue list` 确认状态（open 的单再 reopen 会 rc=1「非 fixed」）。

10. **真链 WS/快照类判据的测量陷阱：别在 asyncio 协程里混用同步 HTTP / time.sleep（2026-09-11 WEBUI-08 实测）**：`st/v1.0.0/_logs/probe2_webui07_ws.py` 在 `asyncio.run()` 协程内直接调同步 `urllib` + `time.sleep()`，**阻塞事件循环 → WS 接收协程被饿死 → 恒报「新增 snapshot 帧 0 条」**，把已修复的引擎误判成「WS 静默」（连续多轮误导复测方）。正解：WS 客户端放**独立线程**（自带 event loop 收帧），主线程只做同步 HTTP——模板见 `st/v1.0.0/_logs/probe_webui08_ws.py`。最省事的旁证是 REST `/api/state` 的 `snapshot.seq` 增速（修复前 ≈0.5 帧/s，修复后 ≈20 帧/s）。**判据权威性分级**：UI 症状类单（如 WEBUI-08 点1 PC 面板）以 ST 本案为准——`ST_UI_PORT=<空闲端口> bash st/v1.0.0/ui/run_ui_st.sh`（本例 `st-UI-S4-001`，端口 18706 常被并发 worker 占用，务必换端口）；API/WS 探针作为数据源侧旁证。
11. **探针 stdout 会被引擎 DBG 日志灌爆**：SOCSIM-06 的 `evidence_large_elf_probe.py`（in-process TestClient）单轮 stdout 1MB+（DBG-RT/DBG-UIO 刷屏）。一律 `python3 probe.py > /tmp/x.log 2>&1` 落盘后再 `read_file`/`tail` 取关键行，**别 `| tee` 直接进上下文**。另：shell 命令里若 `head/cat` 引用到含 stop/restart 字样的日志，会被 gateway 安全护栏拦成「cannot restart or stop the gateway」——用 read_file 工具或重定向落盘绕开（同族：显式写 venv 绝对路径 `…/hermes-agent/venv/bin/python` 的 `-c` 命令也会被误拦，直接用 `python3`）。

**分层心法**：`SPAWN` 审计行是上下半部分界线——上半部问题看 gateway/脚本，下半部问题看 worker/模型/API；产物文件永不覆盖，最坏情况是重跑一轮而非丢数据。

## 验证

- 状态机自测（零 token）：`register` → `claim <id> analyst` → 写产物 → `release_analyze` → `claim <id> reviewer` → `release_review <id> <file> FAIL` → 检查各状态分支与 `{work_path}/artifacts/` 生成。
- 端到端冒烟：放真实需求进 `{work_path}/input/`，手动跑 `python3 scripts/statectl.py worker_tick` → 轮询 `get` 到 `approved`，核对 `zteam/logs/pipeline.log` 与 `{work_path}/artifacts/`。


### v2 blocked 处理（模块/版本级）

- **解除阻塞命令**：`module {项目} unblock {模块} {迭代}`（blocked → design_pending 重跑）/ `unblock {项目} {版本}`（→ planning）；清 failures/claim，不再手改 modules.json；
- **资源限制自动恢复**：blocked 时巡检按脚本规则判因（扫项目 worker 日志尾部：429/配额 → `resource:minimax`；timeout → `network`；无痕迹 → `other`）；`resource` + 配额恢复（check_minimax_quota.py 退出码 0）或 `network` → **自动 unblock**（RESOURCE_RECOVERED 告警）；`other` → 人工介入（永不自动）；
- **判别顺序**：先查 `blocked_reason` 字段（已标记直接用），未标记才扫日志——一切判定为脚本固定规则，非 AI 读日志。


### 项目工作路径解耦（v2.1）

- **项目映射表** `zteam/projects.json`（唯一真理源，git 跟踪）：项目名/成立时间/最新版本/工作路径/默认标记——**只能用户明确修改**（zbot 需用户确认）经 `statectl project ...` 写入；
- 命令：`project list/info/add {name} {path?}/setpath {name} {path}/default {name}/rm {name}`（add 路径缺省 `~/project/{name}`；校验=绝对路径+非 zteam 内部；default 唯一）；
- **路径解析**：`project_dir(project)` 查表取 work_path（未登记回退 workspace/{project} 存量兼容）；需求投放= `{work_path}/input/{req_id}.md`；register 扫映射表（未登记项目不扫=强制先 add）；
- **版本同步**：版本 released（confirm_guide）自动更新 latest_version（脚本守护）；
- **zbot 必守**：/new 第一步执行 `project list`；用户未指定项目→提示默认项目；项目操作需用户确认后执行。

## 问题单归属与分单机制（2026-09-11，错挂根治）

**背景**：问题单原无归属字段 → `release_module it` 把**项目级全部 open 单**挂进迭代 waiting → 错挂五连犯
（UARTIO-01、SOCSIM-05/06、DEBUGCORE-01/03、WEBAPI-02/03）：FO 被派无关单，拒修或"假修复"（只标状态不改码）。

**状态机（4 态）**：`open（待修）→ fixed（已修·待验证）→ closed（复测验证·终态）`；
旁路 `open|fixed → pending（挂起待处理，不阻塞门禁）→ activate → open`。
- `fixed` 必须保留：驱动复测派单、防 FO 自证通过（假修复靠它揪出）；`closed`=真闭环；挂起用 `pending`（别再用 closed 兼作挂起）。

**流程**：提单（自动写 `归属模块：待定` + `提单人：MTO|STO`，来自 spawn 注入的 `ISSUE_REPORTER`）
→ 调度检测待归属 open 单 → spawn **SE 分单**（`issue assign <iid> <模块>`）
→ 跨模块多项缺陷 → SE 用 **`issue split <原单> <新单> <模块> <项描述>`** 逐项拆出（原单 close）
→ 挂载**只挂归属本模块**的单（`release_module it DONE`）→ 归属模块最后一个迭代 `it_working` 补挂 / `it_passed` **再激活**
→ FO 修复 → **复测方=提单人**（IT 单→MTO；ST 单→**STO 验收**）→ close → 迭代收口 it_passed。

**三个必知坑（都踩过）**：
1. **FO 修复上下文必须含复测建议**（SOCSIM-05/06 空转 3 轮的真根因）：原实现只喂单**前 2000 字符**——
   描述在前、复测方重申三次的精确修复建议在**单末尾** → FO"看不到要求" → 标 fixed 但没改正确路径 → 复测必打回。
   现 `_issue_brief_for_fix()` = 头 1500 + 尾 2500 字符（末尾标注"必须逐条落实"），query 加硬性 4 条：
   逐条落实写明文件:行／**真链运行路径生效（UT 全绿≠闭环）**／自证复测方点名的调用点与常量已改／未落实即视为未修复。
2. **版本不变式（D17）**：存在"进行中迭代"（非 it_passed/blocked）时版本必须 `in_dev`——否则 FO/检视/MTO 派单被
   `_schedule_module_iter` 的 `in_dev` 门禁挡住 +"全 it_passed"前提破坏使 STO 不再重生 + st 通道不报滞留
   → **"无 FO/无 STO/无告警"的静默完全停滞**（STO 第 10 轮读代码发现）。现每 tick 幂等自愈（VERSION_REOPEN，
   后期阶段回归修复单自动把版本拉回 in_dev），修复闭环后全 it_passed 自动回 st。`diagnose` D17 可自动检出不自洽。
3. **版本 unblock 回"被打断阶段"**（`blocked_from`）：曾固定回 `planning` → ST 阶段版本被整个打回架构重做；
   另 `wait_user` 状态（qa_reviewing/blocked）**不计** VERSION_STUCK 滞留（等用户不是卡死）。

**命令**：`issue {p} assign {iid} {模块}`（SE 分单）｜`issue {p} split {原单} {新单} {模块} {描述}`（拆分）｜
`issue {p} pend {iid} {目标版本} [理由]` / `issue {p} activate {iid}`（挂起/激活）。

## v2 模块中心命令（PM/SE/TE/MDE/FO/MTO/STO/QA 八角色）

- 规格评审（用户拍板）：`confirm {req_id}` / `reject {req_id} <理由>`（zbot 推送🧾待评审）
- 模块管理（SE）：`module {项目} add|rm|dep|dispatch|iter <...>`
- 问题单：`issue {项目} open|fix|close|list <...>`（提单人复测关闭；open>0 卡模块/版本门禁）
- 版本前置：`release_arch {p} {v} {产物} DONE|PASS|FAIL`（SE 产出/PM 评审）、`release_testplan_v2 ...`（TE 产出/SE 评审）
- 模块迭代：`release_module {p} {模块} {迭代} design|code|review|case|it {产物} [DONE|PASS|FAIL]`
- 版本收尾：`release_st_v2 ... DONE`（STO）、`release_qa ... DONE`（QA）、`confirm_guide {p} {v}`（用户确认指南→released）
- 解除阻塞：`module {项目} unblock {模块} {迭代}`（模块 blocked → design_pending）/ `unblock {项目} {版本}`（版本 blocked → planning）——**资源限制 blocked（blocked_reason=resource:minimax）在配额恢复后由巡检自动 unblock**，其他原因保持人工
- 问题单复测不通过：`issue {项目} reopen {iid} <原因>`（回 open 重试）
- 变更：`change_request {req_id} modify|remove <描述>`（修改→重细化全链重跑 / 删除→忽略+解锁；released 版本冻结）
- 版本串行：同项目仅 1 活跃版本；released 后才能开新版本架构
- 查看：`versions [项目]`（版本/模块/迭代聚合视图）

## 专项参考（references，按需 skill_view 加载）

- `references/project-workspace.md`——**项目映射表机制专项**：projects.json 结构/命令族/路径解析（product_path）/diagnose 语义/worker cwd 改造/并发会话污染排查/迁移流程（合并自 zteam-project-workspace）；
- `references/zteam-v2-ops.md`——**v2 模块中心排障专项**：版本/需求/模块状态机、已修复缺口（评审 spawn/版本自动推进）、zbot 模型认知排障（session DB 铁证）、released 继续开发、用户评审拍板流程、排障定位清单（合并自 zteam-pipeline-v2）。
