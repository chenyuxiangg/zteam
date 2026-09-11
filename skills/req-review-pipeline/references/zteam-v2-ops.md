# zteam v2 模块中心排障专项——参考

> 合并自原 skill `zteam-pipeline-v2`。v2 模块中心特有的实测缺口与排障；映射表/路径解析机制见 `references/project-workspace.md`。详细设计见工作区 `docs/v2-工程分层模型设计.md`（读取时若 read_file 报 Binary file，用 `python3 -c "print(open(p,encoding='utf-8').read())"` 或 iconv）。

## 核心架构（v2）

- **版本状态机**：`planning → arch → arch_reviewing → testplan → testplan_reviewing → in_dev → st → st_done → qa → qa_reviewing → released`
- **版本串行**：同项目仅 1 活跃版本；新版本 planning 可提前建（仅规划），**arch 起需当前版本 released**
- **需求状态**：`pending → analyzing → analyzed → awaiting_user_confirm → approved（规格锁定）→ dispatched → released`（blocked 人工 requeue）
- **模块迭代**：`design_pending → design_reviewing → dev_working → dev_reviewing（检视门禁）→ it_working → it_passed`；模块可跨迭代，前序迭代未 it_passed 则串行
- **命令**：`confirm/reject`、`module add/dep/dispatch/iter`、`issue open/fix/close`、`release_arch`/`release_testplan_v2`/`release_module`/`release_st_v2`/`release_qa`、`assign`、`versions`

## 已修复缺口（2026-08-13，commit 4eb2247 起）

### 缺口 1（已修复）：版本级评审无 spawn → 流水线卡死 arch_reviewing
- **修复**：`_schedule_arch_te` 补 `arch_reviewing → spawn pm`（release_arch PASS|FAIL）、`testplan_reviewing → spawn se`（release_testplan_v2 PASS|FAIL）；`_schedule_module_iter` 补 `design_reviewing → spawn se`（release_module design）、`dev_reviewing → spawn mde`（release_module review，检视门禁）；各评审点 `*_claimed` + pid 防重；
- **教训（设计检查清单）**：**每个 reviewing/waiting 状态必须有对应的自动推进路径（spawn 评审者 或 用户推送通道）**——"有状态必有推进"，实现期逐个状态核对，否则流水线静默卡死（无 BLOCKED 无告警）；
- 现在 arch_reviewing 卡点**不再出现**（PM/SE 评审自动 spawn）。

### 缺口 2（已修复）：需求落进 released 版本静默卡死
- **修复**：`advance_current(project)`——注册未指定版本需求时，current 已 released → **自动开新版本（语义化 minor+1，如 v1.0.0→v1.1.0）设为 current**，需求挂新版本（planning 可调度）；显式指定 released 版本 → **拒绝注册**（版本冻结，REGISTER_REJECT 审计行）；
- 注册逻辑在 `register_new_inputs`：`ver = meta["version"] or advance_current(proj)`；
- 不再需要人工 assign 解卡；投放侧仍可用 `version: vX.Y.Z` frontmatter 显式指定。

### 缺口 3（已修复，309659c）：arch 评审 FAIL → 版本永久卡死（无兜底）
- release_arch FAIL 原把版本置回 `arch`，但调度器只在 `planning` spawn SE——`arch` 无分支，SE 永不重调度；stale 兜底只在 claim=True+进程死时动作，FAIL 后 claim=False 不触发 → 版本静默卡死；
- **修复**：FAIL → `planning`（planning 分支自动重新 claim + spawn SE）；**根因是"可达性无保证"——任何 FAIL/回退落点必须落在有调度分支的状态**。

### 缺口 4（已修复，cc3a927）：read_status() 不认 projects.json 项目
- read_status(None) 聚合只遍历（已删除的）workspace/ → 映射表项目 work_path/status.json 读不到 → PM 干完活 set_status/release_analyze 报「不存在」→ 卡 claimed → stale/guard 误判 → BLOCKED；
- **修复**：聚合主源 = 映射表项目（project_status_file 内部查表）+ workspace 存量兼容；v1 release_*/stale/guard/notify 15 处产物路径 WORKSPACE_DIR 拼接 → product_path()（PAUSE_FILE 也移 zteam 根）。

### 缺口 5（已修复，b6dc84a）：版本状态机系统性防线（②版本 guard + ③可达性表）
- ② `_version_guard_watch`（每 tick）：**arch+claim=False 死状态 → 即时回 planning + VERSION_GUARD 告警**；中间态 12 tick（~60min）无变化无活 worker → **VERSION_STUCK 告警**（不再静默卡死）；补正仅限 arch→planning（其余告警为主）；no_worker 判定注意 `_claims_sig` 全 False 返回非空串（查 "True" not in）；
- ③ `VERSION_FLOW` 可达性表（12 状态 × 通道 auto_sched/auto_done/wait_user/term + stuck 落点）；**D15 结构级**（表内每状态必须有通道——改状态机跑 diagnose 即回归）；**D16 运行级**（versions.json 实际状态必须在表——v1 遗留 st_pending/st_passed/quality_pending 暴露 WARN）；
- 版本状态名两套混用隐患（v1 st_pending vs v2 st 等）由 D16 兜底检出。

## zbot 模型 / 认知排障（2026-08-13 实测）

- **zbot 模型 = gateway channel_overrides per-channel**（gateway.json `platforms.telegram.channel_overrides.<chat_id>` 的 `model`/`provider` 字段，ChannelOverride 支持；优先级：session `/model` → channel_overrides → config.yaml default）；bot_config.py install 已注入 `model=deepseek-v4-flash, provider=deepseek`；**不动 config.yaml 全局 default**；
- **session DB 是模型/认知的铁证**：`~/.hermes/state.db` 表 `sessions` 的 `model`/`system_prompt` 字段（按 chat_id 查最新行）——**zbot 自报模型不可信**（它被问时读 config.yaml 的 default 自报，如报 minimax-m3 但实际是 flash）；验证实际模型查 session DB，不要信自报；
- **zbot 认知旧（还提分析师/方案设计者等旧角色）**：system_prompt 是每轮动态加载的（`_get_system_prompt_for_channel`），注入新 bot.md 后**旧会话历史上下文仍会覆盖新认知** → 让用户给 zbot 发 `/new`（或 `/reset`）重置会话（`_handle_reset_command`）即加载新认知；
- **改 bot.md 后**：`python3 scripts/bot_config.py install` 注入（system_prompt 动态加载无需重启；改 model 需重启 gateway）；**配套步骤 = 提醒用户 /new**；
- **gateway.json 是 legacy 配置**：config.yaml 无 platforms 段时生效（本机现状）；gateway/config.py 的 config 加载优先级 env > config.yaml > gateway.json。

## 已 released 项目继续开发（用户常见问法）

- **可以**：released 版本冻结（change_request modify/remove 被拒，需开新版本承载）；新功能 = 投放新需求 → 开新版本 → 走全流程；
- 流程：投放 input → PM 细化 → 🧾 用户 confirm → assign 到新版本 → SE 架构 → PM 评审 → TE 方案 → SE 评审 → 模块迭代 → ST/QA → confirm_guide → released。

## 用户评审拍板流程（规格待确认点逐条拍板）

- 用户逐条回复 Q-01~Q-09 → 与 PM 建议一致的可直接 `confirm`；**有任何一条偏离 PM 建议（如加难度分级）→ `reject {rid} <完整理由>`**（状态回 analyzing，reject_reason 留档）让 PM 重细化；
- **reject 后 PM 修订仍写同 rN 文件**（round 仅评审时递增），初版留档 `archive/`，修订版文件头标注"修订版"；reject 理由要完整带上全部拍板，PM 才能逐条固化（修订版含 R-01~R-09 对照表）；
- confirm 是规格锁定的唯一入口，锁定后进入版本级流程。

## 问题单分单/再激活排障（2026-09-11 全链实测）

- **症状**：某单连续多轮打回、FO 每轮标 fixed 但复测证据显示代码没改到位 → 先查 **FO 拿到的上下文**：
  `_issue_brief_for_fix` 是否给了单末尾的复测建议（原实现只给前 2000 字符，建议被截掉=空转真因）。
- **症状**：单已裁决归属但没人修 → 查版本状态是否 `in_dev`（D17：进行中迭代要求版本 in_dev；不变式自愈每 tick 跑）；
  已收口迭代（it_passed）会被**再激活**，日志 `MODULE_ITER_REACTIVATE` / `VERSION_REOPEN`。
- **症状**：跨模块单挂一个模块反复修不好 → 用 SE 重新裁决：把 `归属模块` 改回"待定"（或从 waiting 摘除）
  → 调度自动 spawn SE → 它会按复测意见 `issue split` 逐项拆到各根因模块（WEBUI-07 → WEBUI-08/09/10/11 实例）。
- **复测方**：`issue assign` 后看单的 `提单人` 字段——MTO 提单由 MTO 复测、ST 阶段 STO 提单由 STO 验收
  （日志 `SPAWN-RETEST ... worker=sto|mto`）；批量 fixeds 混有 STO 单时复测方取 STO。

## 排障定位清单

1. `statectl list` + `statectl get {rid}` + `tail zteam/logs/pipeline.log`（SPAWN/STATE/ARCH_DONE/VERSION 审计行）三步定位卡点；
   - ⚠️ **2026-08-20 项目数据解耦后**：`statectl list`/`get` 无参聚合可能读不到 `~/project/<项目>/status.json`（projects.json work_path）→ **list 可能误报"空：还没有需求"**。别信空结果，直接 `ls ~/project/` + grep pipeline.log 的 REGISTER/CLAIM/SPAWN 行核对，或手工 `python3 -c "import json;print(json.load(open('/home/zyzs/project/<项目>/status.json')))"`。
2. **卡点分类**：无新 SPAWN = 调度缺口（缺口 1/2 已于 4eb2247 修复；若复现先查对应 spawn 分支与 advance_current 是否被回归）或版本挂错（查 versions.json 归属）；有 SPAWN 无 STATE = 下半部问题（worker 日志/模型名/API 配额）；
3. `versions {p}` 聚合视图看版本/迭代/需求归属（版本状态 + 需求 done 数）；
4. 版本级产物（arch/testplan）卡点不体现在需求条目 stages 里——**必须查 versions.json 和 pipeline.log 的 VERSION/ARCH 行**，statectl get 只覆盖需求级；**b6dc84a 起版本卡死会 VERSION_STUCK/VERSION_GUARD 自动告警——先看 alarms.txt 的这两个标记**；
5. **幽灵 worker / 伪 pending（并发会话数据污染，2026-08-20 实测）**：并发会话迁移/改动 work_path 数据可能改坏状态（versions.json 被改成 planning + status.json 清空 + input 文件不全）→ tick 修复后把这些"伪 pending"当新需求调度 → 冒出不该跑的 worker（如已 released 的 snake-linux/snake-linux 被 PM 重新分析）。**查证三件套**：`ls ~/project/<项目>/input/`（input 文件是否齐全）↔ `versions.json` 版本状态/reqs ↔ `status.json` 条目——三者不一致 = 数据被外部改动；对照备份 `~/cyx/zteam-workspace-backup-<日期>/` 恢复真实状态；杀错 worker 用 `ps aux | grep "hermes chat"` 找 pid 后 kill（**勿用 `pkill -f "hermes chat -q"`——模式过宽会误杀自身 shell/gateway 进程**）；
6. **ad-hoc 验证 mock spawn 的坑**：`spawn_worker` 的 cmd 数组 = `["hermes","chat","-q",query,"-m",model,"-Q"]`——**query 在 `cmd[3]`（不是 cmd[2]）**；断言指令内容用 `captured[0][3]`；mock 只验证"调度模板生成的指令"（find_claimable/_schedule_* 的 query），**直接调 spawn_worker 传旧 query 断言不到模板替换**。

## MTO 模块 IT 收尾登记续跑（web-ui it3 实测，2026-09-10）

**命令语义与判定（`release_module {项目} {模块} {迭代} it {产物} DONE`）**：
- 前置 `status == it_working`；执行后写 `it_report`/`it_product`、`claimed=False`，再查 **项目级** `open_issues(项目)`（该文件状态 ∈ {open, fixed} 的单，**非按模块过滤**——会带上其它模块的单）；
- 非空 → status **留在 it_working** + `waiting_issues=[...]`（修复链：FO `issue fix` → MTO 复测 `issue close` → 全 closed 自动 it_passed）；全空 → **自动 it_passed**。
- ⚠️ 推论：**IT 有 FAIL 用例却没提单就登记 = 系统判 it_passed（假通过）**。必须先 `issue open` 再登记，顺序反了要回滚/补单。

**续跑收尾核对清单（缺一不可，登记前逐项核）**：
1. `测试用例.md` 存在且模块迭代 `case_passed=true`（TE 评审已过）；
2. `模块测试报告.md` 存在，**结论区 PASS/FAIL 在头部 3000 字符内**（机器可解析）；
3. `测试执行日志.txt` 存在（原始执行输出）；
4. 本轮缺陷已 `issue {项目} open <iid> <P0-P4> <描述>`（含断言原文 + 复现命令 + 代码位）；
5. 建议真链**重跑留证**（间歇缺陷需多次；报告只记本轮真实结果，勿沿用上轮结论）。

**worker 撞上限的半成品形态**：日志尾 `⚠️ Reached maximum iterations (150)`。典型残缺 = `tests/`、`测试用例.md`、样本/harness 齐全，但**报告/执行日志/问题单全缺**、状态停在 `it_working` 且 `it_product=null`（web-ui it3 r1 即此形态）。此类"续跑收尾"任务**必须补齐 1-4 再登记**，只跑登记命令会制造假通过。

**取证要点**：`modules.json` → `modules[name=web-ui].iterations[n]`（v2 模块状态在 modules.json，**不在 status.json**）；`issue {项目} list open`；临时诊断/探针文件放 `_tmp/` 并从 `tests/it/` 移出（vitest include `tests/it/**/*.test.ts` 会把 `_diag*.test.ts` 计入用例集）；`evidence_*.py` 探针保留作缺陷证据。
