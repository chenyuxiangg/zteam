# 模块设计评审意见：game-core（snake-linux v2.0.0 迭代 1）r1

> SE 评审 · 依据：`design/game-core/设计-r1.md`（MDE 产出）+ 架构 `arch/v2.0.0/架构设计.md` + `arch/v2.0.0/功能模块分工表.md` + 需求规格 `analysis/snake-gui-r1.md`（approved）+ v1 代码 `code/snake-linux-r1/snake.py`
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：设计整体结构完整、可测试性设计到位（UT 清单/夹具/覆盖率/TDD 步骤齐全），但存在 2 项阻塞级问题——① 接口注解使用 `X | None` / `tuple[...]` 等 3.9+/3.10+ 语法，违反架构「Python 3.8 语法兼容」硬约定；② 撞自身判定规则文档自相矛盾且与 v1 实际行为相反（违反架构「玩法规则与 v1.0.0 保持一致」约束）——修订后可复评。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点 | 结果 |
|---|---|---|
| `Difficulty` 枚举 + `base_tick_ms`（250/160/100） | §2.1 + §1.2 参数表 | ✅ |
| `GameState(width, height, difficulty)` 构造 | §2.4 | ✅ |
| `set_direction`（含 180° 反向禁止） | §2.4/§3.2：反向静默忽略 | ⚠️ 见 P2-2（长度 1 特例缺失） |
| `step()` 每节拍推进（移动/吃食/碰撞/得分） | §2.4/§3.2 五大分支齐全 | ⚠️ 撞自身分支见 P1-2 |
| `toggle_pause()` | 明确放迭代 2（架构同），PAUSED 枚举占位不暴露入口 | ✅ |
| `snapshot()` 只读快照（蛇身/食物/得分/长度/状态/难度） | §2.5 Snapshot 冻结 dataclass，含 tick_ms | ✅ |
| `status`（run/paused/over） | §1.1 GameStatus 枚举 | ✅ |
| `on_score(score)` 事件 | 明确放迭代 2 与 platform-storage 接入时同做 | ✅ |
| 数据流：输入 → set_direction/step → snapshot → renderer 只读 | §数据传递方式：不可变快照 + step 返回新对象（renderer 不可改 state） | ✅ |
| 零 GUI 依赖（NFR-05） | §3.7 import 约束仅标准库；§5.6 UT 无 GUI 依赖 | ✅ |
| 语法兼容 Python 3.8（架构「不使用 3.9+ 新语法」） | §2.x 接口注解 | ❌ **P1-1** |
| 玩法规则与 v1.0.0 保持一致（架构约束） | §3.6 声称「撞尾也算结束（v1 行为一致）」 | ❌ **P1-2**（与 v1 相反） |
| 难度游戏中不可切换（FR-05） | GameState 构造固化 difficulty，无运行中切换接口 | ✅ |
| 不做计时/不渲染/不读盘写盘 | §3.7 明确 | ✅ |
| 事件机制迭代 1 不引入（与迭代 2 对齐） | §1.3 明确不引入 events/on_score | ✅ |

## 2. 可落地性（FO 可否据其 TDD）

- **UT 框架完备**：§5.1 测试文件组织、§5.2 conftest 夹具、§5.3 断言规范、§5.4 20 条必写用例、§5.5 覆盖率目标（行 95%/分支 90%）、§5.6 运行命令、§5.7 严格 RED-GREEN-REFACTOR 步骤——FO 可直接照做，可落地性设计是本设计的最大亮点 ✅。
- **接口签名/语义/异常完整**：§2.1~2.7 全部公开 API 含签名、docstring 语义、异常矩阵（§4.6）✅。
- **FO 实现须知清晰**：§3.6 v1→v2 差异表、§3.7 实现注意点 7 条、§附录 A 迭代 2 增量预告（扩展点不破坏既有签名）✅。
- **受阻点**：P1-1 注解语法会让 FO 在 Python 3.8 下直接跑不起来；P1-2 撞尾规则文本冲突会让 FO 无所适从——这两项必须先修订。

## 3. 问题清单

### P1（阻塞级，必须修订）

**P1-1 接口注解超出架构 Python 3.8 语法兼容约定**
- 架构硬约定：技术选型「Python 3.8+（语法兼容 3.8，不使用 3.9+ 新语法）」、代码风格「不用 dataclass/海象/3.9+ 特性」。
- 设计 §2.4 签名中 `pending_direction: Direction | None`、`rng: random.Random | None`（PEP 604 联合类型，**3.10+**）；`body: tuple[Point, ...]`、`snake_body: tuple[Point, ...]`（内置泛型下标，**3.9+**）。FO 按此实现，Python 3.8 下函数定义求值注解即 TypeError。
- 修改点：全部改为 typing 写法 `Optional[Direction]` / `Optional[random.Random]` / `Tuple[Point, ...]`（`from typing import Optional, Tuple`）；§3.1 文件组织与 §2.7 API 表同步。
- 注：`@dataclass(frozen=True)` 为 3.7+ 标准库、3.8 可用，不属于 3.8 兼容问题（见 P3-1 SE 裁决）。

**P1-2 撞自身判定规则自相矛盾且与 v1 实际行为相反**
- 设计 §3.2 注释两段冲突：第一段「只有当 new_head == 旧尾时才允许，其余身段均视为撞」；第二段「简化规则（FO 必须按此实现）：撞自身判定 = new_head in set(body)，含义：撞尾也算结束」——同一规则两种说法，FO 无法确定执行哪个。
- 与 v1 不符：v1 代码 `code/snake-linux-r1/snake.py:119-120` 实际为 `if nh in body and not (nh == self.snake[0] and not eating)`（deque 头在右端，`snake[0]` 为蛇尾）——**新头撞旧尾且本 tick 不吃食（旧尾将移走）时允许让行**，即 v1 撞尾不算结束。设计 §3.6/§5.4-6 声称「撞尾 → OVER（v1 行为保持一致）」与 v1 相反。
- 违反架构约束「玩法规则与终端版 v1.0.0 保持一致」。
- 修改点：统一为 v1 行为——撞自身判定 = `new_head in set(body)` 且 `not (new_head == 旧尾 and not 吃食)`；或 MDE 明确裁决偏离 v1 并给出理由（在架构「与 v1 一致」约束下应跟 v1）。§3.2 注释两段合并为一条确定性规则；§5.4 UT #6 断言同步改为「撞尾（不吃食）→ 不结束、蛇身正常让行」；§5.4 UT #5 保持「撞非尾身段 → OVER」。

### P2（应修订，影响边界正确性）

**P2-1 最小网格校验与初始布局矛盾（width=3 时初始蛇身出界）**
- `__init__` 只校验 width/height ≥ 3（§4.5/§4.6），但初始 3 节水平蛇 body=[(W//2,H//2),(W//2-1,H//2),(W//2-2,H//2)]，width=3 时 W//2-2 = -1，蛇身 x 坐标出界（破坏 INV-3 精神与初始布局自洽性）。
- 修改点：`__init__` 最小校验改为 width ≥ 4（或初始布局按网格宽度自适应）；§5.4 UT #14 断言改为 `GameState(3, 3, ...)` 抛 ValueError；补一条「width=4 初始蛇身全部在界内」用例。

**P2-2 架构关键约束「反向禁止（长度 1 时除外）」未落地**
- 架构 §关键约束：`set_direction` 拒绝与当前行进方向相反（**长度 1 时除外**）；设计 §2.4 反向一律静默忽略，无长度 1 特例，且未说明为何弃用。
- 修改点：设计显式裁决——(a) 实现长度 1 特例（与架构一致），或 (b) 说明「初始蛇长 3、长度 1 实际不可达，弃用特例」并同步修订架构措辞（需 SE/PM 确认）。当前为契约偏差，必须显式化而非默认忽略。

### P3（建议，不阻塞本轮）

**P3-1（SE 裁决）`@dataclass(frozen=True)` 与架构「不用 dataclass」措辞冲突**
- 架构代码风格约定「不用 dataclass」，设计用 frozen dataclass 实现 Point/Snapshot。SE 裁决：dataclasses 为 Python 3.7+ 标准库，3.8 完全可用，frozen dataclass 是值对象（不可变、可哈希、__eq__ 自动）的合理选择，**放行**；架构「不用 dataclass」措辞将在架构维护轮次修订为「值对象允许 frozen dataclass（标准库），业务逻辑类不用」。MDE 无需修改。

**P3-2 `Difficulty.base_tick_ms` 与 `DIFFICULTY_PARAMS` 双数据源归属未明确**
- §1.2 定义 `DIFFICULTY_PARAMS` dict，§2.1 `Difficulty.base_tick_ms` property 返回 250/160/100，但未说明 property 的实现来源。若 property 硬编码数值，则与 §4.2「难度参数集中在 params.py，迭代 2 加 speed_curve 只改这一处」矛盾。
- 修改点：明确 `base_tick_ms` property 从 `DIFFICULTY_PARAMS` 读取（单一数据源），或删除 dict 只留 property。

**P3-3 测试组织 pytest conftest 与「unittest 强制」的张力**
- §5.1/§5.2 用 pytest 风格 conftest fixture，§5.6 又强制「unittest 可跑（core UT 不依赖任何 GUI 工具，CI 干净容器直接 `python3 -m unittest` 通过）」——conftest.py 对 unittest 不生效，两条路线共存易让 FO 困惑。
- 修改点：统一为 unittest（setUp 内 `random.Random(42)`），或明确「pytest 为团队偏好、unittest 为 CI 兜底」的共存方式及各自夹具写法。

## 4. 结论与复评条件

- **FAIL**（阻塞级 2 项 + 应修 2 项）。
- 复评条件：MDE 修订设计后重新 `release_module ... design ... DONE`，满足以下即可 PASS：
  1. P1-1 注解改为 Python 3.8 兼容写法（`Optional`/`Tuple`）；
  2. P1-2 撞自身判定统一为 v1 行为（撞尾不吃食允许让行），§3.2 注释与 UT #6 同步；
  3. P2-1 最小网格校验与初始布局自洽；
  4. P2-2 长度 1 反向特例显式裁决；
  5. P3-2/P3-3 顺手修订（P3-1 已由 SE 裁决放行，无需改）。
