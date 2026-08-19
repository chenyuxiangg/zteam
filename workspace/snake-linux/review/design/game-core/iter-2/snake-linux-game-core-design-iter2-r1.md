# 模块设计评审意见：game-core（snake-linux v2.0.0 迭代 2）r1

> SE 评审 · 依据：`design/game-core/设计-iter2-r1.md`（MDE 首发）+ 架构 `arch/v2.0.0/架构设计.md` + `arch/v2.0.0/功能模块分工表.md` + 需求规格 `analysis/snake-gui-r1.md`（approved）+ 迭代 1 已落地代码 `code/game-core/iter-1/`（54 UT 实测全绿）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：**P1-1 加速曲线数学不满足 NFR-01「困难档节拍 ≤ 简单档 50%」**——score≥40 时 EASY/HARD 同时钳制到 50ms 下限，比例变 1:1（50 ≤ 25 不成立），设计声明的 INV-10/C2-8 是假断言，UT #23 按设计必红且无法变绿，FO 照 §5.7 TDD 步骤 1 即卡死；若照公式实现则高分局 HARD 与 EASY 同速，违反规格验收。
- 架构符合性 14 项全部通过（接口/数据流/契约对齐，含 FR-12 暂停语义、FR-13 得分事件、C2-7 零 GUI 边界）；可落地性主体优秀（41 条 UT + 夹具 + TDD 步骤），但受 P1-1 阻塞、P2-C 一处断言不可测、迭代 1 评审遗留 P2-A/P2-B 未闭环影响。
- 本轮新发现：P1 × 1、P2 × 1；迭代 1 遗留未闭环：P2 × 2、P3 × 2（详见 §3）。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点 | 结果 |
|---|---|---|
| `Difficulty` + 参数表 `base_tick_ms`（250/160/100）+ `speed_curve(score)` | §1.2/§2.1/§2.7：`speed_curve(score, difficulty)` 单一数据源，`base_tick_ms` property 走 `speed_curve(0, self)`（调用方无感，兼容迭代 1） | ✅（曲线数学见 P1-1） |
| `GameState(width, height, difficulty)` 构造 | §2.4：+`rng/initial_direction/score_callback` 关键字参数，向后兼容 | ✅ |
| `set_direction`（180° 反向禁止，长度 1 除外） | §2.4/§3.2：长度 ≥2 静默忽略、长度 1 放行；PAUSED 期静默忽略（FR-12） | ✅ |
| `step()` 每节拍推进（移动/吃食/碰撞/得分） | §2.4/§3.2 分支齐全，判定顺序：撞墙→撞自身→吃食→移动；PAUSED/OVER 抛 InvalidStateError | ✅ |
| `toggle_pause()`（暂停定格，暂停期方向输入不生效） | §2.4/§3.5：RUN↔PAUSED 翻转、OVER 抛错、INV-9 字段冻结、INV-8 恢复清 pending；语义与 FR-12 验收逐条对齐（画面定格/节拍停止/恢复后蛇位得分长度不变） | ✅ |
| `snapshot()` 只读快照 + `tick_ms` | §2.4/§2.5：`tick_ms` 改走 `speed_curve(score, difficulty)`（字段名/类型不变，非破坏性变更，renderer/app 按 snapshot.tick_ms 定时） | ✅ |
| `status`（run/paused/over） | §1.1 GameStatus 三态，迭代 2 全部启用 | ✅ |
| `on_score(score)` 事件（供 app 接最高分判定） | §2.4/§3.2：`set_score_callback(cb)` 注册制，step 吃食触发一次、异常不捕获、core 不持有 storage 引用；与架构「app 接 platform-storage 持久化」契约一致 | ✅ |
| 数据流：输入 → core → snapshot → renderer 只读；得分 → storage | §数据传递方式 + §3.7-5/6：不可变快照、renderer 只读、core 不读写盘 | ✅ |
| 零 GUI 依赖（NFR-05） | §3.7 import 约束仅标准库（enum/dataclasses/random/typing）；C2-7 明确 core 不知窗口/焦点，app 监听 WINDOWFOCUSLOST 调 toggle_pause | ✅ |
| 语法兼容 Python 3.8 | 全文档 typing.Optional/Tuple/Dict/Callable，禁用 PEP 604 / 内置泛型；§3.1 明示 | ✅ |
| 玩法规则与 v1.0.0 一致 | §3.2 撞自身判定与迭代 1（已验 v1 等价）一致；§未变更清单沿用 | ✅ |
| 难度游戏中不可切换（FR-05） | 构造固化 difficulty，无运行中切换接口；附录 A 明确「开新局」语义不预留切换 | ✅ |
| 不做计时/不渲染/不读盘写盘 | §3.7-4/5/6 | ✅ |

**数据流一致性**：`输入 → set_direction/step/toggle_pause → snapshot → renderer` 与架构数据流图一致；得分事件经回调接 storage 的路径与架构「──得分事件──▶ platform-storage.save(最高分)」一致 ✅。

## 2. 可落地性（FO 可否据其 TDD）

- **迭代 1 基线健康**：`code/game-core/iter-1/` 54 UT 实测全绿（0.010s）；frozen dataclass + `dataclasses.replace` 模式与迭代 2 设计兼容（新增 `_score_callback` 字段在 replace 路径自动保留，行为正确）。
- **UT 框架完备**：迭代 1 基线 21 条 + 迭代 2 增量 14 条（#22~41）覆盖 speed_curve 参数化 / pause 全分支 / on_score 回调 / 暂停期方向忽略；覆盖率目标（行 95%、state.py 与 params.py 100%、分支 92%）；夹具 `_GameCoreBase` + `make_small_state(5×5)` 穷举手段；§5.7 八步 RED-GREEN-REFACTOR 顺序合理。
- **接口签名/语义/异常完整**：§2.1~2.7 公开 API 含签名与 docstring 语义；§4.6 错误矩阵较迭代 1 扩展 5 行；§3.6 迭代差异表 FO 实现须知清晰。
- **受阻点**：① **P1-1 使 UT #23 必红无法变绿**（§5.7 步骤 1 即卡死）——阻塞；② P2-C 使 UT #39 断言不可观察；③ 迭代 1 遗留 P2-A（INV-5 矛盾）/P2-B（长度 1 构造途径未说明）仍未闭环；④ §3.6 差异表「暂停期 set_direction：静默忽略」与迭代 1 已落地行为（OVER 才抛）的迁移影响未提示 FO 需同步改既有 test_state_set_direction.py 的 OVER 断言以外的用例——属增量，低风险。

## 3. 问题清单

### P1（阻塞，必须修订后复评）

**P1-1 加速曲线数学不满足 NFR-01 50% 约束（INV-10 / C2-8 / UT #23 为假断言）**

- 设计公式：`tick_ms = max(50, base - k*score)`，EASY(250,4) / MEDIUM(160,4) / HARD(100,3)，全局下限 MIN_TICK_MS=50。
- 实测（按设计公式计算）：
  - score=30：EASY=130, HARD=50 → 50 ≤ 65 ✅
  - score=40：EASY=90, HARD=50 → **50 ≤ 45 ❌**
  - score=50：EASY=50, HARD=50 → **50 ≤ 25 ❌**
  - score=100：EASY=50, HARD=50 → **50 ≤ 25 ❌**
- 根因：EASY 与 HARD 共用同一全局下限 50，EASY 先触下限（score=50）后与 HARD 同为 50ms，比例恒为 1:1，50% 约束在 score ≥ 40（EASY 降到 100 以下、HARD 已钳制 50）即被破坏。
- 影响：a) **UT #23**（`score in [0,100]` 断言 `speed_curve(score, HARD) <= speed_curve(score, EASY) * 0.5`）必红且按设计公式永远无法变绿——FO 照 §5.7 步骤 1「写 test_speed_curve.py → 绿」直接卡死（除非擅自改断言，破坏 TDD 纪律）；b) 若照公式实现，高分局（score ≥ 40，约 40+ 分）HARD 与 EASY 同速，违反规格 NFR-01 验收「困难档节拍 ≤ 简单档节拍的 50%」；c) INV-10 与 C2-8 声称「任意 score 成立」为假，作为 FO 实现与 UT 断言依据不可信。
- 修改点建议（MDE 择一）：
  1. **三档独立下限**（推荐）：EASY 下限 100 / MEDIUM 下限 80 / HARD 下限 50。验证：EASY 触底 100、HARD 触底 50 → 50 ≤ 100×0.5 = 50 ✅ 边界成立；任意 score 满足 50% 约束且各档速度仍有区分度（100/80/50）。需同步修订 §1.2 公式与注释、INV-10、C2-8、UT #25（钳制断言）、§4.5 表格；
  2. **50% 约束限定未触下限区间**：文档明示「下限区 1:1 持平，50% 验收以未触下限区（score<40）为准」，但规格验收字面不满足，需用户在规格层确认后方可采纳；
  3. 其他满足 `HARD ≤ EASY×0.5` 恒成立的曲线族（如 HARD 下限 ≤ EASY 下限×0.5）。

### P2（应修订，不阻塞复评 PASS 但建议 code 前修订）

**P2-A（迭代 1 遗留，未闭环）INV-5 与「长度 1 反向特例」仍自相矛盾**
- §1.4 INV-5 原文照旧：「`pending_direction` 若非 None，则与 `direction` 非 opposite（受理时校验）」；但 §2.4/§3.2 保留长度 1 允许反向生效。迭代 1 评审 P2-A 已指出，迭代 2 未修订。
- 修改点：INV-5 改为「`pending_direction` 若非 None 且蛇长 ≥ 2，则与 `direction` 非 opposite；长度 1 特例除外（§2.4）」；同步 §5.3 断言规范说明特例。

**P2-B（迭代 1 遗留，未闭环）长度 1 状态无公开构造途径，文档未说明**
- §5.2 夹具（default_state 3 节 / make_small_state 5×5）均无法构造长度 1；§5.4 #9b、#34、#35 依赖该状态。迭代 1 代码已实际解决：`dataclasses.replace(s, snake=Snake((Point(x,y),)), ...)` 直接替换（`test_state_reversal_block.py` 有先例，实测可用），但迭代 2 设计未在 §5.2 提供 `make_len1_state()` 夹具说明。
- 修改点：§5.2 补 `make_len1_state` 夹具（注明经 dataclasses.replace 构造，供特例 UT 专用），避免 FO 重蹈「发明私有 hack」的停顿。

**P2-C（新）回调异常时「状态字段已正确更新」不可观察，UT #39 无法按描述落地**
- §3.2 step 伪代码：`new_state = self.copy(...)` → `self._score_callback(new_score)`（异常不捕获）。回调抛异常时 step 向外抛，**new_state 不可达**——调用方（app 或 UT）拿不到「已正确更新」的新状态；而迭代 1 已实现的 GameState 是 frozen dataclass（self 永不改变），旧 state 也不含新 score。
- 因此 §4.6 错误矩阵「状态字段已正确更新（callable 抛错前 copy() 已完成）」与 UT #39「状态字段已正确更新（step 返回前的 new_state 已含新 score）」**均无法从外部断言**——FO 写 UT #39 会卡住。
- 修改点：a) 文档明示异常语义：**本 tick 的状态更新随异常一起丢失**（new_state 未交付），app 捕获回调异常后的正确处置是「本 tick 不推进」或「重开对局」，不得用旧 state 继续 step（否则蛇卡原位、下一 tick 重复吃同一食物、反复触发同一失败回调）；b) UT #39 断言改为「step() 抛 RuntimeError + 旧 state 快照未被污染（纯函数性质：`before == state.snapshot()`）」；c) 若坚持「更新可达」，需改变回调触发位置（如回调失败仍返回 new_state 的错误包装），但不建议过度设计——纯函数语义下方案 a/b 最自洽。

### P3（建议，顺手修订）

- **P3-A（迭代 1 遗留）** §3.5 状态机图首「NEW ──▶ OVER」的 NEW 未定义，应为「RUN(初始)」（迭代 1 评审 P3-A 已指出，未改）。
- **P3-C（迭代 1 遗留）** §5.4 UT #10「set_direction(同方向) 返回值与 self.snapshot 相等」——GameState 与 Snapshot 字面不可比，应为「`after.snapshot() == before.snapshot()`」（迭代 1 评审 P3-C 已指出，未改）。
- **P3-D（新）** §2.1 示例代码（class 内 `@property` 直接调 `speed_curve`）与 §3.1 文件组织（types.py 不含 params 依赖）冲突：照抄示例会因 types→params 导入时序报错。迭代 1 已用「params 模块在 types 之后导入 + 运行时 property 绑定」（params.py `Difficulty.base_tick_ms = property(...)`）解决，设计应注明沿用该模式。
- **P3-E（新）** `_score_callback` 作为 frozen dataclass 字段的实现注意未说明：应 `field(repr=False, compare=False)`（避免 repr 打印/eq 比较回调不稳定）；`__init__` 的 allowed 集合需加 `score_callback`；`_build_initial` 返回 dict 需补该字段（迭代 1 手写 `__init__` 结构下遗漏会 AttributeError）。设计 §1.3 仅标「私有」，建议补一句实现指引。
- **P3-F（新）** 规格 NFR-01「默认节拍 ≤ 200ms」与 FR-05 参数说明「简单 250ms」措辞存在歧义（若「默认」指简单档则 250 > 200）。架构与迭代 1 已按 250/160/100 落定并 PASS，建议在设计中注明「默认节拍以普通档 160ms 计」消除歧义（不属本设计缺陷，供 MDE 顺手说明）。
- **P3-G（新）** 删除 `DirectionError` 属破坏性变更：迭代 1 代码 `errors.py`/`__init__.py` 已定义并 re-export（实测迭代 1 54 UT 无引用，无外部消费者，低风险）。设计应明确「迭代 2 需同步从 `errors.py` 与 `__init__.py` 移除导出」，避免 FO 遗漏导致残留死代码或下游 import 不一致。

## 4. 结论与后续

- **FAIL**（阻塞级 1 项：P1-1 加速曲线数学违反 NFR-01；架构符合性 14/14 通过；迭代 1 遗留 P2-A/P2-B 与 P3-A/P3-C 未闭环）。
- 后续要求：
  1. **P1-1 必须修订**（推荐三档独立下限方案）并同步修订 INV-10 / C2-8 / UT #23/#25 / §1.2 / §4.5，修订后 r2 复评；
  2. P2-A / P2-B / P2-C 修订设计文档（P2-C 需同时改 UT #39 断言描述）；
  3. P3-A~G 顺手修订；
  4. 本意见归档于 `review/design/game-core/iter-2/`，code 阶段检视以此设计为基线。
