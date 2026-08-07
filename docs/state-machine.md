# 状态机定义：需求分析与多轮评审流水线

> 本文件是整个流水线的"唯一事实来源"：定义了工作区布局、**上下半部调度架构**、状态集合、迁移规则、并发防护、轮次与终止条件、失败处理。
> 任何实现（上半部脚本、下半部 worker、cron job 配置）都必须与本文档保持一致；如要修改，先改本文档。

---

## 1. 工作区布局与文件命名约定

```
req-review/
├── input/        # 需求原文：{req_id}.md（用户投放区，一个文件一个需求）
├── analysis/     # 分析报告：{req_id}-r{N}.md（N = 轮次，每轮新文件，不覆盖）
├── review/       # 评审意见：{req_id}-r{N}.md
├── artifacts/    # 终版产出：{req_id}.md（评审通过后归档，含全部轮次历史）
├── roles/        # 角色定义（analyst.md / reviewer.md）
├── scripts/      # statectl.py（状态机唯一实现）+ 上半部入口（watchdog-analyst.py / watchdog-reviewer.py / watchdog-weekly.py）
├── docs/         # 设计文档
├── logs/         # 审计日志 pipeline.log + 下半部 worker 日志 worker-*.log
├── AGENTS.md     # 流水线约定（下半部 worker 自动加载的项目上下文）
└── status.json   # 状态机（唯一事实来源）
```

命名规则：
- `req_id` = 需求原文文件名去扩展名（如 `req-001.md` → `req-001`），仅允许 `[A-Za-z0-9_-]`；
- 轮次 `N` 从 1 开始；分析报告与评审意见的轮次号**同步递增**（r1 分析 → r1 评审 → r2 分析 → r2 评审……）；
- 下半部 worker 日志：`logs/worker-{req_id}-r{N}.log`。

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
    1) 注册 input/ 下未登记的新文件 → pending
    2) stale 恢复（见 §7.2：回收卡死的 worker 认领）
    3) 原子认领最老的 pending/needs_fix → analyzing（写 claim 字段）
    4) setsid 拉起下半部：
       setsid hermes chat -q "严格遵循 roles/analyst.md 完成 req-001 第 N 轮..." \
              -m <ANALYST_MODEL> -Q > logs/worker-req-001-rN.log 2>&1 &
    5) 无活 → 空 stdout 静默退出；异常 → 非 0 退出/输出告警（经 cron 投递）

t1  [下半部·分析师 worker] 独立 Hermes 进程（分钟级，无 3 分钟限制）
    1) 读 claim + input/{req_id}.md（修改轮还读 review/{req_id}-r{N-1}.md）
    2) 按 roles/analyst.md 产出 analysis/{req_id}-r{N}.md
    3) 原子更新状态 analyzing → analyzed（清空 claim 字段）
    4) 写审计日志，退出

t2  [上半部·评审师 tick] watchdog-reviewer.sh：认领最老的 analyzed → reviewing，拉起评审 worker

t3  [下半部·评审师 worker] 产出 review/{req_id}-r{N}.md → 状态置 approved 或 needs_fix
    （needs_fix 则回到 t0 进入下一轮；循环直到 approved 或 max_rounds）
```

### 2.4 模型绑定位置（关键）

- 上半部两个 cron job 均为 `no_agent` 纯脚本，**自身不需要模型**；
- **模型绑定发生在下半部 spawn 时**：脚本顶部常量 `ANALYST_MODEL` / `REVIEWER_MODEL`（配 `--provider`），通过 `hermes chat -m` 传入。两个角色天然不同模型；改模型只需改脚本常量，**无需重建 cron job**。

### 2.5 唤醒协议（上半部输出约定）

- **无活** → 空 stdout（no_agent 模式空输出 = 静默，不投递、不耗 token）；
- **异常/告警** → 非 0 退出码或人类可读的告警文本（no_agent 模式会把 stdout 原样投递到 cron 的 deliver 目标，如 Telegram）；
- 下半部 worker 的 stdout 一律重定向到 `logs/worker-*.log`，**不进入投递通道**（避免刷屏）。

## 3. 状态集合

| 状态 | 含义 | 持有者 |
|------|------|--------|
| `pending` | 已登记，等待分析师认领 | 无（可被上半部·分析师认领） |
| `analyzing` | 分析师 worker 处理中（中间态，防竞态） | analyst worker |
| `analyzed` | 分析完成，等待评审 | 无（可被上半部·评审师认领） |
| `reviewing` | 评审 worker 处理中（中间态，防竞态） | reviewer worker |
| `needs_fix` | 评审未通过，等待分析师修改 | 无（可被上半部·分析师认领） |
| `approved` | 评审通过，已归档（终态） | — |
| `blocked` | 处理失败达到上限，需人工介入（终态） | — |

## 4. 状态迁移表（唯一合法路径）

| 当前状态 | 事件 | 动作（产物） | 下一状态 |
|----------|------|--------------|----------|
| `pending` | 上半部·分析师认领 | 原子置 `analyzing`（写 claim）；worker 写 `analysis/{req_id}-r{N}.md` | `analyzed` |
| `analyzed` | 上半部·评审师认领 | 原子置 `reviewing`（写 claim）；worker 写 `review/{req_id}-r{N}.md` | `approved` 或 `needs_fix` |
| `needs_fix` | 上半部·分析师认领 | 原子置 `analyzing`（写 claim）；worker 写 `analysis/{req_id}-r{N+1}.md` | `analyzed` |
| `analyzed`（N = max_rounds） | 轮次已达上限 | 强制归档，置 `approved` + `forced: true` | `approved` |
| 任意非终态 | 失败 ≥ 2 次 | 置 `blocked`，告警 | `blocked` |
| `blocked` | 人工处理后重投 | 重置失败计数，状态回 `pending` | `pending` |

非法迁移（实现必须拒绝）：`pending → reviewed`、`needs_fix → approved`、跳过中间态、`approved/blocked` 被再次认领。

## 5. status.json Schema

```json
{
  "req-001": {
    "status": "analyzing",
    "round": 2,
    "max_rounds": 3,
    "forced": false,
    "analysis": "analysis/req-001-r2.md",
    "reviews": ["review/req-001-r1.md", "review/req-001-r2.md"],
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
- `forced: true` 的归档文件在 `artifacts/` 中保留全部轮次历史与所有评审意见，供人工复查。

### 7.2 失败处理（无人值守必须内置）

- **worker 失败**（进程崩溃 / 退出非 0 / 产物缺失 / 状态未更新）→ 需求状态滞留 `analyzing`/`reviewing`，由**上半部 stale 恢复**兜底：
  1. 发现 `analyzing`/`reviewing` 且 `claimed_at` 超过 `STALE_AFTER`（默认 20 分钟）；
  2. `kill -0 $worker_pid` 检查：进程**存活** → 跳过（worker 还在跑，只是慢）；进程**已死** → 回滚（`analyzing→pending` / `reviewing→analyzed`，`failures + 1`，清空 claim 字段），下个 tick 重新唤醒；
- **上限**：`failures ≥ 2` → 置 `blocked`，上半部脚本输出告警文本（经 cron 的 deliver 推送到 Telegram 等），提示人工介入；
- **巡检 job**（每周一次，no_agent 脚本）：检查 `status.json` JSON 合法性、`approved` 与 `artifacts/` 一致性、是否存在滞留超过 24h 的非终态。**只告警，不改状态**。

### 7.3 人工介入方式

- 查看进度：`python3 scripts/statectl.py list`（总览）或 `get <req_id>`（详情）；
- 重投 `blocked` 需求：`python3 scripts/statectl.py requeue <req_id>`（等价 jq 重置：`status=pending, failures=0`）；
- 手动回滚中间态：`python3 scripts/statectl.py rollback <req_id>`；
- 全程可审计：`logs/pipeline.log`（每步状态迁移）+ `logs/worker-*.log`（每次下半部执行明细）。

## 8. 上半部脚本与下半部 worker 职责划分

| 组件 | 部分 | 职责 | 禁止 |
|------|------|------|------|
| `watchdog-analyst.py` | 上半部 | 调 `statectl.py analyst_tick`：注册 input/ 新文件；stale 恢复；原子认领 `pending`/`needs_fix` → `analyzing`；按 `ANALYST_MODEL` spawn 分析师 worker；无活静默 | 写产物、评审、改需求原文、直接调 LLM |
| analyst worker | 下半部 | 读原文/意见 → 按 `roles/analyst.md` 干活 → 落盘 → 调 `statectl.py release_analyze`（`analyzing→analyzed`，清 claim） | 评审、改需求原文 |
| `watchdog-reviewer.py` | 上半部 | 调 `statectl.py reviewer_tick`：stale 恢复；原子认领 `analyzed` → `reviewing`；按 `REVIEWER_MODEL` spawn 评审 worker；无活静默 | 写产物、改分析文档、直接调 LLM |
| reviewer worker | 下半部 | 读原文/分析 → 按 `roles/reviewer.md` 评审 → 落盘 → 调 `statectl.py release_review`（`reviewing→approved\|needs_fix`，清 claim） | 修改分析文档 |
| `watchdog-weekly.py` | 巡检 | 调 `statectl.py weekly_tick`：一致性检查（见 §7.2） | 改状态（仅告警） |
| `statectl.py` | 共用 | 状态机全部确定性逻辑（注册/认领/release/spawn/stale/告警/归档），上下半部与人工共用同一实现 | 一切模型判断 |

## 9. 新需求录入（唯一入口）

投放方式：把需求原文放入 `input/{req_id}.md`（一个文件一个需求，可一次放多个），其余全自动。

检测机制（`register_new_inputs()`，在 `analyst_tick` 内执行）：
1. 扫描 `input/` 下所有 `*.md`；
2. `req_id` = 文件名去 `.md` 扩展名；
3. 若 `req_id` 尚未出现在 `status.json` 的 key 中 → 注册为 `pending`（`round: 0, max_rounds: 3, failures: 0`）；
4. 同一 tick 内，新注册的需求立即参与"最老优先"认领并 spawn 分析师 worker（审计日志中 `REGISTER` 与 `CLAIM` 同秒）。

### 9.1 边界行为与使用注意

| 场景 | 行为 | 期望效果时怎么办 |
|------|------|------------------|
| 修改已注册需求的内容（**不改文件名**） | **不会**重新检测/重新分析；状态机按 `req_id` 追踪需求 | `python3 scripts/statectl.py requeue <req_id>` 重置回 `pending` 重跑 |
| 修改文件名 | 文件名即 ID，改名 = 全新需求（旧条目保留，不自动清理） | 如需"替换"而非"新增"，先处理旧条目 |
| 删除 `input/` 中的文件 | `status.json` 条目**保留**（历史可审计，不自动清理） | 保留作记录，或手工编辑 status.json 删除条目 |
| 非 `.md` 文件（`README.md`、`.gitkeep` 等） | 完全忽略 | — |
| 中文 / 空格 / 特殊字符文件名 | 违反命名规则（仅 `[A-Za-z0-9_-]`），实现未强校验，可能引发路径问题 | 按规则命名 |
| 文件放在 `input/` 之外 | 不生效（`input/` 是唯一入口） | 移入 `input/` |
| 一个文件里写多个需求 | 被当作**一个**需求分析（粒度 = 文件） | 拆成多个文件 |

> 设计取舍：注册、认领、stale 恢复都放在上半部脚本（确定性逻辑，零 token，不依赖模型判断）；模型只做"活"本身（分析/评审/修改）。

## 10. 审计日志格式（logs/pipeline.log）

```
2026-08-02T08:00:01Z REGISTER req-001 status=pending round=0
2026-08-02T08:05:02Z CLAIM   req-001 by=analyst from=pending pid=12345
2026-08-02T08:05:03Z SPAWN   req-001 worker=analyst pid=12345 model=deepseek-chat
2026-08-02T08:12:00Z ANALYZE req-001 round=1 file=analysis/req-001-r1.md
2026-08-02T08:12:00Z STATE   req-001 analyzing->analyzed
2026-08-02T08:20:03Z CLAIM   req-001 by=reviewer from=analyzed pid=23456
2026-08-02T08:27:00Z REVIEW  req-001 round=1 file=review/req-001-r1.md conclusion=FAIL
2026-08-02T08:27:00Z STATE   req-001 reviewing->needs_fix
```
