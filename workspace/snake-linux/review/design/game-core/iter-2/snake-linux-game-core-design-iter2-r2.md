# 模块设计评审意见：game-core（snake-linux v2.0.0 迭代 2）r2 复评

> SE 复评 · 依据：`design/game-core/设计-iter2-r2.md`（MDE r2 修订版）+ 架构 `arch/v2.0.0/架构设计.md` + `arch/v2.0.0/功能模块分工表.md` + 需求规格 `analysis/snake-gui-r1.md`（approved）+ 上轮评审 `review/design/game-core/iter-2/snake-linux-game-core-design-iter2-r1.md`（FAIL）+ 迭代 1 已落地代码 `code/game-core/iter-1/`
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：PASS**
- 一句话理由：**r1 阻塞项 P1-1（加速曲线数学违反 NFR-01）已闭环**——三档独立下限（EASY 100 / MEDIUM 80 / HARD 50）+ 公式 `max(MIN_TICK_MS[d], base - k*score)`，经代码实测 `s ∈ [0, 2000]` 全区间 `HARD ≤ EASY×0.5` 恒成立、三档均单调不增，UT #23/#24/#25 可绿；r1 全部 P2×3、P3×7 修订到位。本轮仅发现 P2×1（§4.5 一处残留矛盾表述）+ P3×3（文档一致性），均不阻塞。
- 架构符合性 14 项全部通过（与 r1 一致，逐项复核无回退）；可落地性：41 条 UT + 夹具 + 8 步 TDD 顺序可执行，FO 照 §5.7 无卡点。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）——复评

| 架构契约（设计期定义） | r2 落点 | 结果 |
|---|---|---|
| `Difficulty` + 参数表 `base_tick_ms`（250/160/100）+ `speed_curve(score)` | §1.2/§2.1/§2.7：`speed_curve(score, difficulty)` 单一数据源，`base_tick_ms` property 走 `speed_curve(0, self)`，调用方无感；`Snapshot.tick_ms` 同源 | ✅ |
| `GameState(width, height, difficulty)` 构造 | §2.4：+`rng/initial_direction/score_callback` 关键字参数，向后兼容迭代 1 | ✅ |
| `set_direction`（180° 反向禁止，长度 1 除外） | §2.4/§3.2：长度 ≥2 静默忽略、长度 1 放行、PAUSED 期静默忽略（FR-12） | ✅ |
| `step()` 每节拍推进（移动/吃食/碰撞/得分） | §2.4/§3.2 分支齐全；PAUSED/OVER 抛 InvalidStateError | ✅ |
| `toggle_pause()`（暂停定格，暂停期方向输入不生效） | §2.4/§3.5：RUN↔PAUSED、OVER 抛错、INV-8 恢复清 pending、INV-9 字段冻结；与 FR-12 验收逐条对齐 | ✅ |
| `snapshot()` 只读快照 + `tick_ms` | §2.4/§2.5：`tick_ms = speed_curve(score, difficulty)`，字段名/类型不变，非破坏性 | ✅ |
| `status`（run/paused/over） | §1.1 GameStatus 三态全启用 | ✅ |
| `on_score(score)` 事件（供 app 接最高分判定） | §2.4/§3.2：`set_score_callback(cb)` 注册制、吃食触发一次、异常不捕获、core 不持有 storage 引用 | ✅ |
| 数据流：输入 → core → snapshot → renderer 只读；得分 → storage | §数据传递方式 + §3.7：不可变快照、renderer 只读、core 不读写盘 | ✅ |
| 零 GUI 依赖（NFR-05） | §3.7 import 约束仅标准库；C2-7 core 不知窗口/焦点，app 监听 WINDOWFOCUSLOST | ✅ |
| 语法兼容 Python 3.8 | 全文档 typing.Optional/Tuple/Dict/Callable，禁用 PEP 604 / 内置泛型 | ✅ |
| 玩法规则与 v1.0.0 一致 | §3.2 撞自身判定与迭代 1（已验 v1 等价）一致 | ✅ |
| 难度游戏中不可切换（FR-05） | 构造固化 difficulty，无运行中切换接口；附录 A 明确「开新局」语义 | ✅ |
| 不做计时/不渲染/不读盘写盘 | §3.7-4/5/6 | ✅ |

**数据流一致性**：与架构数据流图（输入 → set_direction/step/toggle_pause → snapshot → renderer；得分事件 → platform-storage.save）一致 ✅。

## 2. r1 评审意见闭环核对

| r1 意见 | 级别 | r2 修订落点 | 闭环验证 |
|---|---|---|---|
| **P1-1** 加速曲线数学违反 NFR-01 50% 约束 | 阻塞 | §1.2 公式 + `MIN_TICK_MS: Dict[Difficulty,int]` 三档独立下限（100/80/50）+ INV-10/C2-8/UT #23~25/§4.5 同步修订 | ✅ **实测闭环**：`s∈[0,2000]` 全区间 HARD ≤ EASY×0.5 恒成立、三档单调不增；边界 s=37（EASY=102,HARD=50，50≤51）与 s=38（EASY 触底 100,HARD=50，50≤50）衔接正确；score=0 三档 250/160/100 |
| **P2-A** INV-5 与长度 1 反向特例矛盾 | 应修订 | §1.4 INV-5 改为「若非 None **且蛇长 ≥2** 则非 opposite；长度 1 特例除外」 | ✅ |
| **P2-B** 长度 1 状态无公开构造途径 | 应修订 | §5.2 新增 `make_len1_state()` 夹具（dataclasses.replace 替换 Snake，注明迭代 1 先例） | ✅ |
| **P2-C** 回调异常时「状态已更新」不可观察 | 应修订 | §3.7#9 明示 new_state 随异常丢失、调用方拿不到、旧 state 未推进；§4.6 错误矩阵同步；UT #39 改为断言 `before == state.snapshot()`（旧 state 未污染） | ✅（§4.5 一处残留见下 P2-2） |
| **P3-A** 状态机图 NEW 未定义 | 建议 | §3.5 改为 `RUN(初始) ──▶ OVER` | ✅ |
| **P3-C** UT #10 比较类型错误 | 建议 | §5.4 #10 改为 `after.snapshot() == before.snapshot()` | ✅ |
| **P3-D** §2.1 示例与 §3.1 导入时序冲突 | 建议 | §3.7#8 注明 params 后导入 + 运行时 property 绑定模式（迭代 1 已落地），禁止 types 内 from .params | ✅（实测迭代 1 `__init__.py` 正是此模式） |
| **P3-E** `_score_callback` frozen 字段实现注意 | 建议 | §3.7#10 注明 `field(repr=False, compare=False)`、`__init__` allowed 集合、`_build_initial` 补字段 | ✅（实测迭代 1 `_build_initial` dict 结构属实） |
| **P3-F** NFR-01 默认节拍 ≤200ms 与简单档 250ms 歧义 | 建议 | §4.1 注明「默认节拍」= 普通档 160ms ≤ 200ms；简单档 250ms 为独立档位 | ✅ |
| **P3-G** DirectionError 删除需明确迁移 | 建议 | §3.1 注明同步从 errors.py 与 __init__.py 删除定义与 re-export | ✅（实测迭代 1 两处均定义/re-export 属实） |

## 3. 可落地性（FO 可否据其 TDD）

- **UT 框架完备可执行**：迭代 1 基线 #1~21 + 迭代 2 增量 #22~41 共 41 条；§5.7 八步 RED-GREEN-REFACTOR 顺序合理（先 speed_curve → pause → INV-8 → callback → snapshot.tick_ms），步骤 1 已验证可绿（见 P1-1 闭环）；夹具 `_GameCoreBase` / `make_small_state(5×5)` / `make_len1_state()` 齐备。
- **接口签名/语义/异常完整**：§2.1~2.7 公开 API 含签名与 docstring；§4.6 错误矩阵 13 行覆盖全分支；§3.6 迭代差异表、§3.7 十条实现注意点（含 r2 修订的导入时序、frozen 字段、pure-function 语义）清晰。
- **与迭代 1 代码兼容性确认**（实测 `code/game-core/iter-1/`）：frozen dataclass + `dataclasses.replace` 模式与新增 `_score_callback` 字段兼容（replace 自动保留）；`spawn_food` 模块级函数、params 后导入模式与设计 §3.1/§3.7 一致。
- **无阻塞点**。

## 4. 本轮新发现（不阻塞 PASS）

### P2（应修订，建议 code 前顺手改）

**P2-2 §4.5 鲁棒性表「得分回调内抛异常」行仍残留 r1 旧表述，与 §3.7#9/§4.6 矛盾**

- §4.5 表格行原文：「core 不捕获，异常向外抛；**状态字段已正确更新为新 GameState**」——这是 r1 P2-C 指出的「不可观察」旧表述；§3.7#9 与 §4.6 已改为「new_state 随异常一起丢失、调用方拿不到、旧 state 未推进」。
- 影响：FO 若只读 §4.5 会误以为回调异常后能拿到已更新的新状态；与 §4.6/§3.7#9 权威表述冲突。
- 修改点：§4.5 该行改为「异常向外抛；本 tick 的 new_state 不交付、调用方拿不到（pure-function 语义）；旧 state 未污染」（与 §4.6 对齐）。

### P3（建议，顺手修订）

- **P3-2** §1.4 INV-10 表述「持平**当下限 50**」为 r1 全局下限残留——r2 已改三档独立下限（100/80/50），应改为「持平该档位下限」。
- **P3-3** 增量用例条数口径不一：修订摘要 C2-6 称「~14 个用例」、但 §5.4 #22~41 实为 **20 条**（且「21 → 41」自洽为 20）；建议统一为 20。
- **P3-4** §3.6 差异表列头「迭代 2 r1」但内容含 r2 修订（如下限 per-difficulty 100/80/50 是 r2 新增）；建议列头改为「迭代 2 r2」。

## 5. 结论与后续

- **PASS**。r1 阻塞项 P1-1 数学验证闭环（实测全区间满足 NFR-01 50% 约束与单调性），P2-A/B/C、P3-A~G 全部修订到位；架构符合性 14/14 无回退。
- 后续要求：
  1. P2-2 与 P3-2~4 为文档一致性微调，建议 FO code 前由 MDE 顺手修订（不阻塞本 PASS）；
  2. code 阶段（FO TDD）以本设计为基线；代码检视时重点复核：speed_curve 三档参数与 UT #22~25、toggle_pause 的 INV-8/9、回调异常 pure-function 语义（UT #39）；
  3. 本意见归档于 `review/design/game-core/iter-2/`。
