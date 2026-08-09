# 状态机定义：需求分析与多轮评审流水线

> 本文件是整个流水线的"唯一事实来源"：定义了工作区布局、**上下半部调度架构**、状态集合、迁移规则、并发防护、轮次与终止条件、失败处理。
> 任何实现（上半部脚本、下半部 worker、cron job 配置）都必须与本文档保持一致；如要修改，先改本文档。

---

## 1. 工作区布局与文件命名约定

```
zteam/                       # 资产层（git 跟踪）
├── roles/ scripts/ docs/          # 角色定义 / 代码 / 文档
└── workspace/                     # 数据层（运行数据，按项目组织）
    ├── <项目>/input/{req_id}.md             # 需求原文（用户投放区，一个文件一个需求；项目目录首次投放自动创建）
    ├── <项目>/analysis/{req_id}-r{N}.md     # 需求分析报告（N = 轮次，每轮新文件，不覆盖）
    ├── <项目>/review/{req_id}-r{N}.md       # 需求评审意见
    ├── plans/<project>/{req_id}-r{N}.md     # 开发方案（阶段链产物，同名 -review.md 为评审意见）
    ├── testplans/<project>/{req_id}-r{N}.md # 测试方案
    ├── code/<project>/{req_id}-r{N}.md      # 代码交付（含源码/说明；评审意见同目录 -review.md）
    ├── tests/<project>/{req_id}-r{N}.md     # 测试代码与执行报告
    ├── quality/<project>/{req_id}-r{N}.md   # 质量门禁结论
    ├── security/<project>/{req_id}-r{N}.md  # 安全红线门禁结论
    ├── <项目>/release/{req_id}-r{N}/        # 交付包目录（发布说明+用户指南+tar.gz+SHA256SUMS+自检，released 终态）
    ├── <项目>/artifacts/{req_id}.md         # 终版产出（评审通过 / 完整交付后归档）
    ├── logs/                      # pipeline.log（审计）+ worker-*.log（下半部明细）
    └── status.json                # 状态机（唯一事实来源；key = <project>/<req_id>）
```

命名规则：
- `req_id` = 需求原文文件名去扩展名（如 `req-001.md` → `req-001`），仅允许 `[A-Za-z0-9_-]`；
- 轮次 `N` 从 1 开始；分析报告与评审意见的轮次号**同步递增**（r1 分析 → r1 评审 → r2 分析 → r2 评审……）；
- 下半部 worker 日志：`workspace/logs/worker-{project}-{req_id}-r{N}.log`。

## 2. 调度架构：上半部 / 下半部（核心设计）

对应 Linux 中断处理的"上半部（top half）/ 下半部（bottom half）"模型：**上半部只唤醒（秒级、不耗时），下半部干活（分钟级、耗时）**。

### 2.1 为什么必须拆

- cron 单次运行有 **3 分钟硬中断**，而一次需求分析/评审是 LLM 长任务，可能 5–10 分钟；
- 拆开后，**上半部**（cron 触发）只做秒级确定性操作，3 分钟内绰绰有余；**下半部**（被唤醒的独立进程）完全不受该限制。

### 2.2 角色划分

| 部分 | 形态 | 耗时 | token 消耗 | 持久性 |
|------|------|------|------------|--------|
| **上半部** | cron 触发的纯脚本（`no_agent` 模式） | 秒级（<10s） | **零**（脚本不调 LLM） | cron 调度，天然持久 |
| **下半部** | `setsid hermes chat -q ...` 拉起的**独立 Hermes 进程** | 分钟级 | 正常消耗 | 独立 OS 进程，cron 会话结束/网关重启不影响已唤醒的 worker |

### 2.3 时序（一次完整轮次）

```
t0  [上半部·分析师 tick] watchdog-analyst.sh（秒级）
    1) 注册各项目 workspace/<项目>/input/ 下未登记的新文件 → pending
    2) stale 恢复（见 §7.2：回收卡死的 worker 认领）
    3) 原子认领最老的 pending/needs_fix → analyzing（写 claim 字段）
    4) setsid 拉起下半部：
       setsid hermes chat -q "严格遵循 roles/req-analyst.md 完成 req-001 第 N 轮..." \
              -m <ANALYST_MODEL> -Q > logs/worker-req-001-rN.log 2>&1 &
    5) 无活 → 空 stdout 静默退出；异常 → 非 0 退出/输出告警（经 cron 投递）

t1  [下半部·分析师 worker] 独立 Hermes 进程（分钟级，无 3 分钟限制）
    1) 读 claim + workspace/<项目>/input/{req_id}.md（修改轮还读 review/ 下上一轮意见）
    2) 按 roles/req-analyst.md 产出 analysis/{project}/{req_id}-r{N}.md
    3) 原子更新状态 analyzing → analyzed（清空 claim 字段）
    4) 写审计日志，退出

t2  [上半部·评审师 tick] watchdog-reviewer.sh：认领最老的 analyzed → reviewing，拉起评审 worker

t3  [下半部·评审师 worker] 产出 review/{project}/{req_id}-r{N}.md → 状态置 approved 或 needs_fix
    （needs_fix 则回到 t0 进入下一轮；循环直到 approved 或 max_rounds）
```

### 2.4 模型绑定位置（关键）

- 上半部两个 cron job 均为 `no_agent` 纯脚本，**自身不需要模型**；
- **模型绑定发生在下半部 spawn 时**：脚本顶部常量 `ANALYST_MODEL` / `REVIEWER_MODEL`（配 `--provider`），通过 `hermes chat -m` 传入。两个角色天然不同模型；改模型只需改脚本常量，**无需重建 cron job**。

### 2.5 唤醒协议（上半部输出约定）

- **无活** → 空 stdout（no_agent 模式空输出 = 静默，不投递、不耗 token）；
- **异常/告警** → 非 0 退出码或人类可读的告警文本（no_agent 模式会把 stdout 原样投递到 cron 的 deliver 目标，如 Telegram）；
- 下半部 worker 的 stdout 一律重定向到 `workspace/logs/worker-*.log`，**不进入投递通道**（避免刷屏）。

## 3. 状态集合

### 3.1 需求阶段（评审通过后进入阶段链）

| 状态 | 含义 | 持有者 |
|------|------|--------|
| `pending` | 已登记，等待分析师认领 | 无（可被上半部·分析师认领） |
| `analyzing` | 分析师 worker 处理中（中间态，防竞态） | analyst worker |
| `analyzed` | 分析完成，等待评审 | 无（可被上半部·评审师认领） |
| `reviewing` | 评审 worker 处理中（中间态，防竞态） | reviewer worker |
| `needs_fix` | 评审未通过，等待分析师修改 | 无（可被上半部·分析师认领） |
| `approved` | 需求评审通过（进入阶段链的起点，非终态） | — |
| `blocked` | 处理失败达到上限，需人工介入（终态） | — |

### 3.2 阶段链状态（需求 approved 后按序推进）

阶段序列：`plan` → `testplan` → `code` → `test` → `quality`（门禁）→ `security`（门禁）→ `release`（终态）。

| 状态模式 | 含义 | 持有者 |
|----------|------|--------|
| `{stage}_designing` | 阶段产出者处理中（中间态） | 该阶段 designer/developer |
| `{stage}_reviewing` | 阶段评审者处理中（中间态） | 该阶段 reviewer |
| `{stage}_done` | 阶段评审通过（等待下一阶段认领） | — |
| `{stage}_gating` | 门禁评审处理中（quality/security，中间态） | 门禁评审者 |
| `releasing` | 发布者处理中（中间态） | releaser |
| `released` | 完整交付（终态：最终交付物归档 + 通知） | — |

阶段评审 FAIL：回 `{stage}_designing`（下一轮重做）；连续 FAIL 达 `max_rounds` → `blocked`（质量门禁不放行）。

> **四态机制**：上表 `{stage}_designing/_reviewing/_gating/releasing` 是**派生显示**；每阶段内部真实状态机为 `claimed → working → reviewing → done`（存 `stages[stage].state`，见 §7.5.1），状态变更全部经 `set_status`/`release_*`（严格迁移校验），巡检（§7.5.2）自动补正漏设状态。

## 4. 状态迁移表（唯一合法路径）

| 当前状态 | 事件 | 动作（产物） | 下一状态 |
|----------|------|--------------|----------|
| `pending` | 上半部·分析师认领 | 原子置 `analyzing` + 四态 `claimed`（写 claim）；worker 启动置 `working`；产出写 `analysis/{project}/{req_id}-r{N}.md` 后 `set_status reviewing`（记 product） | `analyzed` |
| `analyzed` | 上半部·评审师认领 | 原子置 `reviewing`；评审者产出 `review/{project}/{req_id}-r{N}.md` | `approved` 或 `needs_fix` |
| `needs_fix` | 上半部·分析师认领 | 原子置 `analyzing`（写 claim）；worker 写 `analysis/{project}/{req_id}-r{N+1}.md` | `analyzed` |
| `analyzed`（N = max_rounds） | 轮次已达上限 | 强制归档，置 `approved` + `forced: true` | `approved` |
| `approved` | 上半部·通用 tick 认领 | 原子置 `plan_claimed`（四态 `claimed`）；产出者启动置 `working`；写 `plans/{project}/{req_id}-r{N}.md` 后 `set_status reviewing` | `plan_reviewing` |
| `{stage}_claimed` | 产出者启动 | `set_status working`（标记执行中，第 0 步强制） | `{stage}_designing` |
| `{stage}_designing`（=四态 working） | 产出完成 | `set_status reviewing {产物}`（记 `stages[stage].product`，严格校验） | `{stage}_reviewing` |
| `{stage}_reviewing`（=四态 reviewing） | 评审完成 | worker 写 `{dir}/{project}/{req_id}-r{N}-review.md` → `release_stage_review` PASS/FAIL | `{stage}_done` 或 `{stage}_designing`（重做） |
| `{stage}_done` | 上半部·通用 tick 认领 | 推进下一阶段（design/gate/release） | 下一阶段 `claimed` |
| `{stage}_gating`（=四态 working） | 门禁完成 | worker 写门禁结论 → `release_gate` PASS/FAIL | `{stage}_done` 或 重试 |
| `releasing`（=四态 working） | 发布完成 | worker 产出交付包目录 `{项目}/release/{req_id}-r{N}/`（发布说明/用户指南/tar.gz/校验和/自检）→ `release_release` | `released` |
| `released` | 发布完成 | **完整交付物归档**（结论摘要+各阶段终版+门禁结论+交付包引用）+ 通知 | `released`（终态） |
| 任意非终态 | 失败 ≥ 2 次 | 置 `blocked`，告警 | `blocked` |
| `blocked` | 人工处理后重投 | 重置失败计数，状态回 `pending` | `pending` |

> **四态说明**（详见 §7.5.1）：每阶段内部真实状态机为 `claimed → working → reviewing → done`（存 `stages[stage].state`），顶层 `{stage}_designing/_reviewing/_gating/releasing` 是派生显示（claimed/working 共用 designing 顶层）。所有状态变更必须经 `set_status`/`release_*`（严格迁移校验），**巡检兜底**（§7.5.2）在超时后按产物存在性/结论自动补正漏设状态。

非法迁移（实现必须拒绝）：`pending → reviewed`、`needs_fix → approved`、跳过中间态、`approved/blocked` 被再次认领。

## 5. status.json Schema

```json
{
  "req-001": {
    "status": "analyzing",
    "round": 2,
    "max_rounds": 3,
    "forced": false,
    "analysis": "analysis/snake-linux/snake-linux-r2.md",
    "reviews": ["review/snake-linux/snake-linux-r1.md", "review/snake-linux/snake-linux-r2.md"],
    "failures": 0,
    "claimed_by": "analyst",
    "claimed_at": "2026-08-02T08:05:02Z",
    "worker_pid": 12345,
    "created_at": "2026-08-02T08:00:00Z",
    "updated_at": "2026-08-02T08:05:02Z"
  }
}
```

| 字段 | 说明 |
|------|------|
| `status` | 见第 3 节状态集合 |
| `round` | 当前评审轮次（= 已完成的评审次数；分析报告轮次与之一致） |
| `max_rounds` | 轮次上限，默认 3，可在录入时按需求覆盖 |
| `forced` | `true` 表示达到轮次上限被强制通过（仍会告警提醒人工复核） |
| `analysis` | 当前生效的分析报告路径（永远指向最新轮次） |
| `reviews` | 全部评审意见路径（追加式） |
| `failures` | 连续失败次数（见 §7.2），成功后清零 |
| `claimed_by` | 当前认领角色（`analyzing`→analyst / `reviewing`→reviewer），worker 完成后清空 |
| `claimed_at` | 认领时间戳，stale 判定依据（见 §7.2） |
| `worker_pid` | 下半部 worker 进程 pid，存活检查用（`kill -0`），完成后清空 |
| `created_at` / `updated_at` | 时间戳 |

## 6. 认领与竞态防护

上半部（两个 job）与下半部（多个 worker）可能并发触碰状态，防护规则：

1. **认领 = 上半部脚本内的原子状态迁移**（compare-and-swap）：仅当目标状态为 `pending`/`needs_fix`（分析师）或 `analyzed`（评审师）时才迁移到中间态，并写入 claim 三字段（`claimed_by`/`claimed_at`/`worker_pid`）。认领成功才 spawn 下半部；
2. **上半部只找活 + 认领 + 唤醒，绝不写产物**；下半部只干活（产物 + 状态落定），认领动作不在 worker 内重复执行；
3. **每 tick 至多唤醒 1 个 worker**（最老的可认领需求优先）→ 并发 worker 数受控，也避免唤醒风暴；
4. **状态文件写入串行化**：`flock` 锁 `status.lock`（带超时，如 5s），脚本与 worker 共用同一锁；
5. **产物命名防覆盖**：轮次新文件 + `reviews` 追加式数组，流程异常也不会破坏历史。

## 7. 轮次、终止与失败处理

### 7.1 轮次与终止

- `round` 达到 `max_rounds`（默认 3）时，评审若仍为 FAIL：**强制归档**（`approved` + `forced: true`），上半部输出告警"带未解决意见通过，需人工复核"；
- `forced: true` 的归档文件在 `workspace/<项目>/artifacts/` 中保留全部轮次历史与所有评审意见，供人工复查。

### 7.2 失败处理（无人值守必须内置）

失败兜底有**两层机制**，全部自动、无需人工：

**① stale 恢复（进程死亡兜底，每 tick）**：需求状态滞留中间态（`analyzing`/`reviewing`/`{stage}_designing/_reviewing/_gating`/`releasing`，四态为 `claimed`/`working`/`reviewing`）且 `claimed_at`/`state_since` 超过 `STALE_AFTER`（默认 20 分钟）时：
- `kill -0 $worker_pid` 检查：进程**存活** → 跳过（worker 还在跑，只是慢）；进程**已死** → 回滚（四态 `claimed`/`working` → 上一完成态，`failures + 1`，清空 claim 字段），下个 tick 重新唤醒；
- **上限**：`failures ≥ 2` → 置 `blocked`，上半部脚本输出告警文本（经 cron 的 deliver 推送到 Telegram 等），提示人工介入。

**② 巡检 guard_recovery（漏设状态自动补正，每 tick，详见 §7.5.2）**：worker **活着但漏设状态**（干完活没调 `set_status`，或卡死在循环里）时，按"超时 + 产物存在性 + 评审结论"自动补正——产物存在 → 补 `reviewing`/`done`（PASS）/`working`（FAIL 重做）；无产物且进程已死 → 回滚。全部动作写 `GUARD` 审计行。**这是四态机制的核心可靠性保障**（worker 无需自觉，漏了也能兜底）。

**③ 每周一致性巡检**（`req-weekly-audit`，no_agent 脚本）：检查各项目 `workspace/<项目>/status.json` JSON 合法性、`approved`/`released` 与归档一致性、是否存在滞留超过 24h 的非终态。**只告警，不改状态**。

### 7.3 人工介入方式

- 查看进度：`python3 scripts/statectl.py list`（总览）或 `get <req_id>`（详情）；
- 重投 `blocked` 需求：`python3 scripts/statectl.py requeue <req_id>`（等价 jq 重置：`status=pending, failures=0`）；
- 手动回滚中间态：`python3 scripts/statectl.py rollback <req_id>`；
- 全程可审计：`workspace/logs/pipeline.log`（每步状态迁移）+ `workspace/logs/worker-*.log`（每次下半部执行明细）。

## 7.5 阶段流水线（需求 approved 后自动推进）

需求评审 `approved` 后由通用 tick（`watchdog-worker.py`）驱动阶段链，无需人工干预：

| 阶段 | 产出者角色 | 评审者角色 | 产物目录 | 模型 |
|------|-----------|-----------|---------|------|
| `plan` | dev-plan-designer | dev-plan-reviewer | `plans/` | flash / pro |
| `testplan` | test-plan-designer | test-plan-reviewer | `testplans/` | flash / pro |
| `code` | code-developer | code-reviewer | `code/` | MiniMax-M3（minimax-cn） |
| `test` | test-developer | test-reviewer | `tests/` | flash / pro |
| `quality`（门禁） | — | quality-reviewer | `quality/` | pro |
| `security`（门禁） | — | security-reviewer | `security/` | pro |
| `release`（终态） | — | releaser（打包交付） | `release/`（交付包目录） | flash |

### 7.5.1 阶段四态状态机（每个阶段独立）

每阶段四态：`claimed`（tick 认领）→ `working`（执行者启动，**必须**调 set_status）→ `reviewing`（产出落盘/评审者启动）→ `done`（评审 PASS）。
评审 FAIL → 回 `working` 重做；连续 FAIL 达 `max_rounds` → `blocked`（质量门禁不放行）。

**状态更新命令**（所有角色共用一个状态设置脚本，严格迁移校验，乱跳拒绝）：

```bash
python3 scripts/statectl.py set_status {key} {stage} working              # 执行者/评审者启动时（第 0 步必须）
python3 scripts/statectl.py set_status {key} {stage} reviewing {产物}     # 产出完成 → 待评审（需产物路径）
python3 scripts/statectl.py release_stage_review {key} {stage} {评审意见} PASS|FAIL  # 评审完成
python3 scripts/statectl.py release_gate {key} {stage} {门禁结论} PASS|FAIL          # 门禁
python3 scripts/statectl.py release_release {key} {项目}/release/{req_id}-r{N}/       # 发布（交付包目录 → released）
```

**迁移校验表**（`set_status` 严格强制）：

| 当前状态 | → working | → reviewing | → done |
|----------|-----------|-------------|--------|
| `claimed` | ✅（执行者启动） | ❌ | ❌ |
| `working` | ❌ | ✅（需产物路径） | ❌ |
| `reviewing` | ✅（FAIL 打回） | ✅（评审者启动幂等） | ✅（PASS） |
| `done` | ❌ | ❌ | ❌ |

### 7.5.2 巡检兜底（guard_recovery，核心可靠性机制）

上半部 tick 内置巡检：阶段 `claimed/working/reviewing` 超时（`state_since` > 20 分钟）时自动补正，**不依赖 worker 进程**：

| 状态 | 产物存在？ | 结论 | 自动处理 |
|------|-----------|------|---------|
| `claimed`/`working` | ✅ 阶段产物存在 | — | 补 `reviewing`（干完没设状态） |
| `claimed`/`working` | ❌ 且 worker 已死 | — | 回滚上一完成态（failures+1） |
| `reviewing` | ✅ 评审产物存在 | PASS | 补 `done`（终态自动归档） |
| `reviewing` | ✅ 评审产物存在 | FAIL/无结论 | 回 `working` 重做（轮次+1，达上限 → blocked） |
| `reviewing` | ❌ 且 worker 已死 | — | 回滚上一完成态（failures+1） |
| 任意 | ❌ 但 worker 存活 | — | 等待（慢任务不打扰） |

巡检动作全部写 GUARD 审计行（`logs/pipeline.log`），可追溯。

### 7.5.3 状态表结构（每需求一张状态表，JSON）

每需求 entry 的 `stages` 即其状态表：从需求分析到发布全部阶段的记录，每阶段含
`state`（四态）/`state_since`（状态起始时间）/`timeline`（全部迁移历史）/`product`（终版产物）/`reviews`（评审意见列表）/`round`。

```json
"stages": {
  "plan": {
    "state": "done", "state_since": "2026-08-08T06:10:12Z", "round": 1,
    "product": "plans/snake-linux/snake-linux-r1.md",
    "reviews": ["plans/snake-linux/snake-linux-r1-review.md"],
    "timeline": [{"t": "...", "to": "claimed"}, {"t": "...", "to": "working"}, {"t": "...", "to": "reviewing"}, {"t": "...", "to": "done"}]
  },
  "testplan": { "...": "..." }
}
```

## 8. 上半部脚本与下半部 worker 职责划分
| 组件 | 部分 | 职责 | 禁止 |
|------|------|------|------|
| `watchdog-analyst.py` | 上半部 | 调 `statectl.py analyst_tick`：注册 workspace/<项目>/input/ 新文件；stale 恢复；原子认领 `pending`/`needs_fix` → `analyzing`；按 `ANALYST_MODEL` spawn 分析师 worker；无活静默 | 写产物、评审、改需求原文、直接调 LLM |
| `watchdog-worker.py` | 上半部 | 调 `statectl.py worker_tick`：注册 + stale 恢复 + 按 `next_action` 认领**阶段链**任意角色（方案/测试方案/代码/测试/门禁/发布）并 spawn；无活静默 | 写产物、评审、改需求原文、直接调 LLM |
| analyst worker | 下半部 | 读原文/意见 → 按 `roles/req-analyst.md` 干活 → 落盘 → 调 `statectl.py release_analyze`（`analyzing→analyzed`，清 claim） | 评审、改需求原文 |
| `watchdog-reviewer.py` | 上半部 | 调 `statectl.py reviewer_tick`：stale 恢复；原子认领 `analyzed` → `reviewing`；按 `REVIEWER_MODEL` spawn 评审 worker；无活静默 | 写产物、改分析文档、直接调 LLM |
| reviewer worker | 下半部 | 读原文/分析 → 按 `roles/req-reviewer.md` 评审 → 落盘 → 调 `statectl.py release_review`（`reviewing→approved\|needs_fix`，清 claim） | 修改分析文档 |
| `watchdog-weekly.py` | 巡检 | 调 `statectl.py weekly_tick`：一致性检查（见 §7.2） | 改状态（仅告警） |
| `statectl.py` | 共用 | 状态机全部确定性逻辑（注册/认领/release/spawn/stale/告警/归档），上下半部与人工共用同一实现 | 一切模型判断 |

## 9. 新需求录入（唯一入口）

投放方式：把需求原文放入 `workspace/<项目名>/input/{req_id}.md`（一个文件一个需求，可一次放多个；项目目录不存在会自动创建），其余全自动。

检测机制（`register_new_inputs()`，在 `analyst_tick` 内执行）：
1. 扫描各项目 `workspace/<项目>/input/` 下所有 `*.md`；
2. `req_id` = 文件名去 `.md` 扩展名；
3. 若 `req_id` 尚未出现在 `workspace/status.json` 的 key 中 → 注册为 `pending`（`round: 0, max_rounds: 3, failures: 0`）；
4. 同一 tick 内，新注册的需求立即参与"最老优先"认领并 spawn 分析师 worker（审计日志中 `REGISTER` 与 `CLAIM` 同秒）。

### 9.1 边界行为与使用注意

| 场景 | 行为 | 期望效果时怎么办 |
|------|------|------------------|
| 修改已注册需求的内容（**不改文件名**） | **不会**重新检测/重新分析；状态机按 `req_id` 追踪需求 | `python3 scripts/statectl.py requeue <req_id>` 重置回 `pending` 重跑 |
| 修改文件名 | 文件名即 ID，改名 = 全新需求（旧条目保留，不自动清理） | 如需"替换"而非"新增"，先处理旧条目 |
| 删除 `workspace/<项目>/input/` 中的文件 | 状态条目**保留**（历史可审计，不自动清理） | 保留作记录，或手工编辑 status.json 删除条目 |
| 非 `.md` 文件（`README.md`、`.gitkeep` 等） | 完全忽略 | — |
| 中文 / 空格 / 特殊字符文件名 | 违反命名规则（仅 `[A-Za-z0-9_-]`），实现未强校验，可能引发路径问题 | 按规则命名 |
| 文件放在 `workspace/<项目>/input/` 之外 | 不生效（`workspace/<项目>/input/` 是唯一入口） | 移入 `workspace/<项目>/input/` |
| 一个文件里写多个需求 | 被当作**一个**需求分析（粒度 = 文件） | 拆成多个文件 |

> 设计取舍：注册、认领、stale 恢复都放在上半部脚本（确定性逻辑，零 token，不依赖模型判断）；模型只做"活"本身（分析/评审/修改）。

## 10. 审计日志格式（logs/pipeline.log）

```
2026-08-02T08:00:01Z REGISTER req-001 status=pending round=0
2026-08-02T08:05:02Z CLAIM   req-001 by=analyst from=pending pid=12345
2026-08-02T08:05:03Z SPAWN   req-001 worker=analyst pid=12345 model=deepseek-chat
2026-08-02T08:12:00Z ANALYZE snake-linux/snake-linux round=1 file=analysis/snake-linux/snake-linux-r1.md
2026-08-02T08:12:00Z STATE   req-001 analyzing->analyzed
2026-08-02T08:20:03Z CLAIM   req-001 by=reviewer from=analyzed pid=23456
2026-08-02T08:27:00Z REVIEW  req-001 round=1 file=review/req-001-r1.md conclusion=FAIL
2026-08-02T08:27:00Z STATE   req-001 reviewing->needs_fix
```
