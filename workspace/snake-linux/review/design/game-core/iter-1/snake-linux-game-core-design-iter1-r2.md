# 模块设计评审意见：game-core（snake-linux v2.0.0 迭代 1）r2

> SE 评审 · 依据：`design/game-core/设计-r2.md`（MDE 修订产出）+ 架构 `arch/v2.0.0/架构设计.md` + `arch/v2.0.0/功能模块分工表.md` + 需求规格 `analysis/snake-gui-r1.md`（approved）+ v1 代码 `code/snake-linux-r1/snake.py`
> 复评对象：r1 评审（FAIL）后 MDE 修订稿；评审日期：2026-08-14

## 0. 评审结论

- **结论：PASS**
- 一句话理由：r1 的 2 项阻塞级（P1-1 语法兼容 / P1-2 撞自身规则）与 2 项应修订（P2-1 网格下限 / P2-2 长度 1 反向特例）全部修订到位且核对无残留；架构契约 14 项全绿；可落地性保持 r1 的高水准（21 条 UT + 夹具 + TDD 步骤）。本轮新发现 2 项 P2 应修订（文档内部自洽性，不改变接口契约、不阻塞 FO 开工）+ 3 项 P3 建议，见 §3，建议 MDE 在 code 阶段启动前顺手修订设计文档。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点 | 结果 |
|---|---|---|
| `Difficulty` 枚举 + `base_tick_ms`（250/160/100，验收「困难 ≤ 简单 50%」） | §1.2 `DIFFICULTY_PARAMS` 单一数据源 + §2.1 property 从 dict 读取（P3-2 已修）；100 ≤ 250×50% ✅ | ✅ |
| `GameState(width, height, difficulty)` 构造 | §2.4（含 rng/initial_direction 注入参数） | ✅ |
| `set_direction`（180° 反向禁止，**长度 1 时除外**） | §2.4/§3.2：长度 ≥2 静默忽略、长度 1 显式允许反向（P2-2 已修） | ✅ |
| `step()` 每节拍推进（移动/吃食/碰撞/得分） | §2.4/§3.2 五大分支齐全，判定顺序：撞墙→撞自身→吃食→移动 | ✅ |
| `toggle_pause()`（暂停定格，暂停期方向输入不生效） | 迭代 2 落地；PAUSED 枚举占位不暴露入口（§3.5），与分工表 game-core 迭代 1,2 一致 | ✅ |
| `snapshot()` 只读快照（蛇身/食物/得分/长度/状态/难度） | §2.4/§2.5 冻结 dataclass；额外含 `tick_ms`（迭代 2 speed_curve 扩展点，属合理增强） | ✅ |
| `status`（run/paused/over） | §1.1 GameStatus 枚举 | ✅ |
| `on_score(score)` 事件（供 app 接最高分判定） | 明确迭代 2 与 platform-storage 接入时同做（§1.3），迭代 1 由调用方读 state.score | ✅ |
| 数据流：输入 → set_direction/step → snapshot → renderer 只读 | §数据传递方式：不可变快照 + step 返回新对象；§3.7-5 renderer 不可改 state | ✅ |
| 零 GUI 依赖（NFR-05） | §3.7 import 约束仅标准库（enum/dataclasses/random/typing）；§5.6 UT 无 GUI 依赖 | ✅ |
| 语法兼容 Python 3.8（不用 3.9+ 新语法） | 全文档注解改 `Optional[X]`/`Tuple[Point, ...]`/`Dict[...]`，§3.1 导入示例明示禁用 PEP 604 / 内置泛型下标；全文 grep 无残留（唯一命中为 §3.7 禁用说明文字本身） | ✅ **P1-1 修订彻底** |
| 玩法规则与 v1.0.0 保持一致 | §3.2/§3.6：撞自身判定 = `next_head in set(body) and not (next_head == 旧尾 and not eating)`，与 v1 `snake.py:119-120` 逐字等价；撞墙后蛇身/分数不变与 v1 一致 | ✅ **P1-2 修订到位** |
| 难度游戏中不可切换（FR-05） | GameState 构造固化 difficulty，无运行中切换接口 | ✅ |
| 不做计时/不渲染/不读盘写盘 | §3.7-4/5/6 明确 | ✅ |
| 事件机制迭代 1 不引入 | §1.3 明确不引入 events/on_score | ✅ |

## 2. 可落地性（FO 可否据其 TDD）

- **r1 复评条件逐项核对**：
  1. P1-1 注解 3.8 兼容 ✅（§2.4/§2.5/§3.1/§3.7 + UT #21 语法验证用例）；
  2. P1-2 撞自身统一 v1 行为 ✅（§3.2 注释二合一，UT #6 撞尾不吃食→不结束、#6b 撞尾吃食→OVER 拆分，TDD 步骤 4 明确「先验 v1 行为」）；
  3. P2-1 最小网格自洽 ✅（`width>=4 and height>=4`，INV-7 同步，UT #14 三组非法输入 + #14b 下限 4×4 初始布局在界内验证）；
  4. P2-2 长度 1 反向特例显式裁决 ✅（实现特例与架构一致，UT #9a/#9b 拆分）；
  5. P3-2/P3-3 顺手修订 ✅（base_tick_ms 走 DIFFICULTY_PARAMS 含 UT #15b 数据源参数化验证；测试统一 unittest、pytest 可选）。
- **UT 框架完备**：21 条必写用例覆盖五大分支 × 边界 × 终态保护 × 确定性 × 3.8 兼容；覆盖率目标（行 95%/state.py 100%、分支 90%）；`_GameCoreBase` 夹具 + `make_small_state(5×5)` 穷举手段；§5.7 九步 RED-GREEN-REFACTOR 顺序合理（先撞墙/撞自身/撞尾再 set_direction）——FO 可直接照做 ✅。
- **接口签名/语义/异常完整**：§2.1~2.7 公开 API 含签名、docstring 语义、§4.6 错误矩阵 7 行全覆盖 ✅。
- **v1→v2 差异表（§3.6）+ 迭代 2 预告（附录 A）**：扩展点不破坏既有签名，FO 实现须知清晰 ✅。
- **受阻点**：P2-A（INV-5 与长度 1 特例矛盾）与 P2-B（UT #9b 无构造途径）两处文档内部自洽问题，见 §3——不阻塞实现主流程，但建议 code 前修订，避免 FO 在写 UT 时停顿。

## 3. 问题清单（本轮新发现，r1 遗留均已闭环）

### P2（应修订，不阻塞 PASS）

**P2-A INV-5 与「长度 1 反向特例」自相矛盾**
- §1.4 INV-5：「`pending_direction` 若非 None，则与 `direction` 非 opposite（受理时校验）」；但 §2.4/§3.2 明确长度 1 时允许 `pending_direction = opposite` 并按反向生效。INV-5 对长度 1 不成立。
- §5.3 又要求「每个 UT 至少断言一条 INV」——FO 若照 INV-5 字面实现会破坏长度 1 特例；照 §3.2 实现则 INV-5 无法作为通用断言。
- 修改点（一处措辞）：INV-5 改为「`pending_direction` 若非 None 且蛇长 ≥ 2，则与 `direction` 非 opposite（受理时校验）；长度 1 特例除外（§2.4）」；同步 §5.3 示例或 INVs 引注说明特例。

**P2-B 长度 1 状态无公开构造途径，UT #9b 无法直接落地**
- GameState 构造（§2.4）不暴露 snake 参数，初始蛇固定 3 节且蛇长只增不减（移动不丢长度、吃食 +1），长度 1 状态从公开 API 不可达；§5.4 UT #9b「单节蛇身时 set_direction(opposite) 后 step 按反向走」与 §5.2 夹具（default_state 3 节 / make_small_state 5×5）均无法构造该状态。
- 修改点：设计明确测试构造途径——(a) 增加内部测试钩子（如 `GameState._replace(snake=...)`，§3.2 已暗示 `copy()`/`dataclasses.replace` 模式，落到文档即可），或 (b) 在 §5.2 提供 `make_len1_state()` 夹具并注明「经内部构造，供特例 UT 专用」。FO 不需要为此发明私有 hack。

### P3（建议，顺手修订）

**P3-A §3.5 状态机图 `NEW` 未定义**
- 图首「NEW ──▶ OVER」中的 NEW 应为初始 RUN（§3.4 初始 status=RUN），图例缺失易误导。改为「RUN(初始) ──(撞墙/撞自身)──▶ OVER」。

**P3-B `DirectionError` 当前无任何抛出路径且未来用途未说明**
- §2.6 定义 `DirectionError(ValueError)` 但注明「当前迭代不抛」，附录 A 迭代 2 预告也未提启用场景——死代码占位。建议删掉，或在附录 A 注明启用时机（如迭代 2 暂停期方向输入时抛出），避免 FO 误实现。

**P3-C §5.4 UT #10 断言表述不精确**
- 「set_direction(同方向) 返回值与 self.snapshot 相等」——set_direction 返回 GameState 而非 Snapshot，字面不可比。应为「`after.snapshot() == before.snapshot()`（同方向幂等，状态不变）」。

## 4. 结论与后续

- **PASS**（阻塞级 0 项；r1 全部评审项闭环；架构符合性 14/14；可落地性受 P2-A/P2-B 轻微影响但不阻塞）。
- 后续要求：
  1. P2-A / P2-B 由 MDE 在 code 阶段启动前修订设计文档（或 FO 实现时以本评审意见 §3 为准：实现规则以 §3.2 伪代码为权威；长度 1 UT 用内部构造）；
  2. P3-A/B/C 顺手修订；
  3. 本轮意见连同 r1 意见归档于 `review/design/game-core/iter-1/`，code 阶段检视（模块间接口/数据流视角）以此设计为基线。
