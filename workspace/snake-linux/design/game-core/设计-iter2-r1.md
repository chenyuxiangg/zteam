# 功能模块设计：game-core（snake-linux v2.0.0 迭代 2）

> MDE 首发 r1 · 跨迭代复用基线：迭代 1 设计 `snake-linux/design/game-core/设计-r2.md`（SE 评审 PASS）
> 依据：架构设计 `snake-linux/arch/v2.0.0/架构设计.md`（§迭代计划迭代 2）+ 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）
> 迭代 2 范围（增量三件套）：
>   ① 加速曲线 `speed_curve(score, difficulty)` 替代迭代 1 的 `base_tick_ms` 直读（NFR-01：困难档节拍 ≤ 简单档 50%）
>   ② 暂停状态机 `toggle_pause()`（RUN↔PAUSED；FR-12：暂停定格、暂停期方向输入不生效）
>   ③ 得分事件回调 `on_score(score)`（FR-13：app 接 platform-storage 持久化最高分）
> **零 GUI 依赖、纯标准库、可独立 UT**（NFR-05）—— 本约束沿用迭代 1，迭代 2 仅在 core 暴露入口，**窗口失焦自动暂停由 app 监听 + 调 `toggle_pause()` 实现**（core 不知道"窗口/焦点"概念）

---

## 修订摘要（相对迭代 1 设计 r2）

| ID | 级别 | 修订内容 | 章节 |
|----|------|----------|------|
| C2-1 | 应实现 | 新增 `speed_curve(score, difficulty) -> int`：参数化"基础节拍 + 加速曲线"，三档（EASY/MEDIUM/HARD）曲线独立；`Difficulty.base_tick_ms` property 改为调用 `speed_curve(0, self)`（与迭代 1 调用方兼容）；`Snapshot.tick_ms` 改走 `speed_curve(score, difficulty)` | §1.2 / §2.1 / §3.2 / §3.4 |
| C2-2 | 应实现 | 新增 `toggle_pause() -> GameState`：RUN↔PAUSED 切换；OVER 状态调用抛 `InvalidStateError` | §2.4 / §3.5 / §4.6 |
| C2-3 | 应实现 | 新增得分事件 `on_score(score: int)`：构造期或 `set_score_callback(cb)` 注册回调；step 吃食时回调一次；**回调内抛异常由调用方隔离（core 不捕获）**，**core 不持有 storage 引用** | §2.4 / §3.2 / §4.6 |
| C2-4 | 应实现 | 状态机扩展：RUN ↔ PAUSED；PAUSED 期 `step()` 抛 `InvalidStateError`、`set_direction()` 静默忽略（不报错也不入 pending）、`toggle_pause()` 返回 RUN | §3.5 / §4.5 / §4.6 |
| C2-5 | 应实现 | INV-4 扩展：PAUSED 期快照字段（蛇身/食物/得分/长度/状态/方向）冻结，仅 `status` 与 `pending_direction` 在 toggle_pause 时变更；新增 INV-8 "PAUSED → RUN 恢复时 pending_direction 应清空"（防止"暂停前按 UP、继续后第一拍立刻 180° 撞尾"） | §1.4 |
| C2-6 | 应实现 | UT 框架扩展：新增 speed_curve 参数化 / pause 状态机 / on_score 回调 / 暂停期方向忽略 共 ~14 个用例；覆盖率达迭代 1 同等标准（行 ≥95% / 分支 ≥90%） | §5 |
| C2-7 | 约束 | **暂停入口语义对齐架构与规格**：app 通过 GUI 主循环按 P/ESC/失焦 触发 `toggle_pause()`；core 不引入任何"窗口/焦点"概念（保持零 GUI 依赖，NFR-05） | §3.5 / §4.5 |
| C2-8 | 约束 | **速度曲线保证 NFR-01 量化**：score=0 时三档节拍 = 250/160/100；任何 score 下 `tick_ms(HARD, score) <= tick_ms(EASY, score) * 0.5` | §1.2 / §5.4 #22 |

**未变更（沿用迭代 1 r2）**：模块定位、零 GUI 依赖、Python 3.8 语法兼容、纯函数语义、不可变 snake.body tuple、反向移动规则（长度 1 特例 / 长度 ≥2 忽略）、撞自身判定（v1 一致）、撞尾让行（不吃食时）、网格下限 `width >= 4 and height >= 4`、RNG 注入、不做计时/不做渲染/不读盘不写盘、import 约束（仅标准库）。

---

## 数据结构

### 1.1 基础值对象

| 类型 | 字段 | 说明 |
|------|------|------|
| `Point`（值对象） | `x: int`、`y: int` | 网格坐标。y 向下、0,0 为左上角，沿用 v1 约定 |
| `Direction`（枚举） | `UP=(0,-1)` / `DOWN=(0,1)` / `LEFT=(-1,0)` / `RIGHT=(1,0)` | 4 向；`opposite()` 工具方法返回反向 |
| `GameStatus`（枚举） | `RUN` / `PAUSED` / `OVER` | 运行态机；迭代 2 全部启用 |
| `Difficulty`（枚举） | `EASY` / `MEDIUM` / `HARD` | 难度档位，绑定 `base_tick_ms`（**迭代 2 起改为走 `speed_curve(0, self)`**） |

> 本节字段、签名、不变性与迭代 1 r2 §1.1 完全一致，仅补充"迭代 2 全部启用 PAUSED"。

### 1.2 加速曲线（迭代 2 单一数据源）

迭代 2 起，**节拍毫秒数由 `speed_curve(score, difficulty)` 动态算得**；迭代 1 的 `DIFFICULTY_PARAMS` 常量 dict **保留为文档留档**（FO 实现里可删除或保留为兜底，§3.2 标注取舍）。

```python
from typing import Dict, Callable
from enum import Enum

class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @property
    def base_tick_ms(self) -> int:
        """基线节拍（score=0 时）；迭代 2 起本 property 走 speed_curve(0, self)。
        对调用方保持兼容：snapshot.tick_ms 由 speed_curve(score, difficulty) 提供。"""
        return speed_curve(0, self)


# 加速曲线：score 越大、tick_ms 越小（蛇越快）；三档曲线独立
# 公式：tick_ms = max(MIN_TICK_MS, base - k * score)
#   - EASY:   base=250, k=4   → score=0..50 时 250→50（极慢速加速）
#   - MEDIUM: base=160, k=4   → score=0..27 时 160→50
#   - HARD:   base=100, k=3   → score=0..16 时 100→50（已很快）
#   - 全部档位下限 MIN_TICK_MS=50（再快就超出 NFR-01 输入延迟 ≤1 节拍 的人体反应极限）
def speed_curve(score: int, difficulty: Difficulty) -> int:
    """返回当前 score 在指定难度下应使用的 tick_ms。
    约束（NFR-01）：
      - score=0 时 == difficulty.base_tick_ms（== 250 / 160 / 100）
      - 任意 score：tick_ms(HARD, score) <= tick_ms(EASY, score) * 0.5
      - tick_ms 不低于 MIN_TICK_MS=50
    """
    params: Dict[Difficulty, Dict[str, int]] = {
        Difficulty.EASY:   {"base": 250, "k": 4},
        Difficulty.MEDIUM: {"base": 160, "k": 4},
        Difficulty.HARD:   {"base": 100, "k": 3},
    }
    p = params[difficulty]
    return max(50, p["base"] - p["k"] * score)


MIN_TICK_MS: int = 50
```

> **取舍说明**：迭代 1 `DIFFICULTY_PARAMS` 是 `{"base_tick_ms": int}` 形态；迭代 2 改为 `{"base": int, "k": int}`（base + 斜率）。FO 实现可保留 `DIFFICULTY_PARAMS` 常量 dict 但**迭代 2 起所有 `tick_ms` 读取必须走 `speed_curve()`**；`Difficulty.base_tick_ms` property 仅作为 score=0 的快捷访问，**不构成 hot path**（snapshot.tick_ms 走 speed_curve）。本曲线公式选择**线性加速 + 下限钳制**，原因：(a) 与"档位间存在可感知差异"语义最直接对应；(b) UT 易断言（线性公式 → 已知 score 序列 → 已知 tick_ms）；(c) 性能 O(1)。

### 1.3 核心实体

**`Snake`**
- 字段：`body: Tuple[Point, ...]`（**不可变 tuple**，蛇头 = `body[0]`，蛇尾 = `body[-1]`）
- 不变量：`len(body) >= 1`；相邻两节点必须 4-邻接
- 派生：`head -> Point`、`len -> int`
- 关键方法（生成新对象，不修改自身）：
  - `with_head(new_head) -> Snake`：在头部插入新节点（移动未吃食）
  - `without_tail() -> Snake`：去掉尾部（移动未吃食，与 `with_head` 配对）
  - `with_head_no_tail_drop(new_head) -> Snake`：仅头部插入（吃食后不丢尾）
  - `contains(p) -> bool`：判断点是否在蛇身

**`Food`**
- 字段：`pos: Point`
- 不变量：`pos not in snake.body`

**`GameState`**
- 字段：
  - `width: int`（网格宽，列数；建议默认 20）
  - `height: int`（网格高，行数；建议默认 15）
  - `difficulty: Difficulty`
  - `snake: Snake`（初始 3 节，居中朝右：body=[(W//2, H//2), (W//2-1, H//2), (W//2-2, H//2)]）
  - `direction: Direction`（初始 RIGHT）
  - `pending_direction: Optional[Direction]`（**同帧多输入合并用**：每个 step 取一次最终方向）
  - `food: Food`
  - `score: int`（**每节长度+1 = 1 分**）
  - `status: GameStatus`（RUN / PAUSED / OVER）
  - `rng: random.Random`（注入，便于 UT 确定性，**禁止隐式全局 random**）
  - `_score_callback: Optional[Callable[[int], None]]`（**迭代 2 新增**：得分事件回调；不传则静默）

> 字段命名沿用迭代 1 r2；`_score_callback` 为私有（避免 snapshot 暴露），通过 `set_score_callback(cb)` 注入（见 §2.4）。

### 1.4 不变量清单（FO 实现必须保证，UT 也要覆盖）

| ID | 不变量 | 违反后果 | 迭代 |
|----|--------|----------|------|
| INV-1 | `len(snake.body) >= 1` 且相邻节点 4-邻接 | 移动逻辑破坏 | 1 |
| INV-2 | `food.pos not in snake.body` | 同位 bug | 1 |
| INV-3 | `0 <= head.x < width` 且 `0 <= head.y < height` | 出界 bug（撞墙判定在 step 入口先做） | 1 |
| INV-4 | `status == OVER` 后所有 step/set_direction/toggle_pause 不再改变 snake/food/score/direction | 终态保护 | 1 |
| INV-5 | `pending_direction` 若非 None，则与 `direction` 非 opposite（受理时校验） | 反向移动禁止 | 1 |
| INV-6 | `rng` 始终是注入实例，模块内不出现 `import random` 后直接 `random.xxx` | 确定性测试前提 | 1 |
| INV-7 | `width >= 4` 且 `height >= 4`（初始布局需要至少 4 列宽度以容纳 3 节水平蛇） | 初始布局自洽 | 1 |
| **INV-8** | **`status == PAUSED` 期 step 抛 `InvalidStateError`、set_direction 静默忽略（不入 pending）；toggle_pause 返回 RUN 时 `pending_direction` 必须清空（防止"暂停前按 UP、继续后第一拍立刻 180° 撞尾"）** | **暂停/恢复语义漏洞** | **2 新增** |
| **INV-9** | **`status == PAUSED` 期所有非状态字段（snake/food/score/length/direction）冻结；toggle_pause 自身也不修改这些字段**（仅 status 翻转 + INV-8 清 pending） | **PAUSED 期不应有副作用** | **2 新增** |
| **INV-10** | **`speed_curve(score, difficulty)` 单调不增**：score 越大、tick_ms 越小（或持平当下限 50）；`speed_curve(score, HARD) <= speed_curve(score, EASY) * 0.5`（任意 score） | **NFR-01 量化不达标** | **2 新增** |

---

## 数据传递方式

| 通道 | 形态 | 用途 |
|------|------|------|
| **构造注入** | `GameState(width, height, difficulty, *, rng=None, initial_direction=RIGHT, score_callback=None)` | 注入 RNG、初始方向、得分回调；UT 用 `Random(seed)` 复现 |
| **参数传入** | `set_direction(d: Direction)` / `step() -> GameState` / **`toggle_pause() -> GameState`** | 不在类内维护隐式时间轴；调用方按节拍显式 step |
| **不可变快照** | `snapshot() -> Snapshot`（`@dataclass(frozen=True)`） | 供 gui-renderer 读、供 app 判定终态；**迭代 2 起 `tick_ms` 字段由 `speed_curve(score, difficulty)` 计算** |
| **返回值** | `step()` / `set_direction()` / `toggle_pause()` **返回新 GameState**（不原地修改） | 纯函数语义，UT 断言前后状态对比 |
| **回调** | **`on_score(score: int)`**（迭代 2 新增）：**得分时触发一次**；调用方（app）注册回调做最高分持久化；core 不持有 storage 引用 | 解耦 core 与 platform-storage |
| **异常** | `InvalidStateError`（继承 `RuntimeError`） | 错误输入显式失败，不静默吞 |

> **回调契约（C2-3）**：
> - 注册：`state = state.set_score_callback(cb)`（返回新 state）或构造期 `score_callback=cb`；
> - 触发时机：`step()` 内吃食分支（`next_head == food.pos`）**在状态字段已更新为新 GameState 后**，调用 `cb(new_score)`；
> - 异常处理：**core 不 try/except 捕获回调异常**；回调内异常向外抛，由调用方（app 主循环）隔离。理由：(a) core 鲁棒性边界 = "状态推进正确"，持久化失败属 app 决策；(b) UT 中可显式构造"回调抛错"用例验证状态字段仍正确；
> - 多次回调：单 tick 最多 1 次（贪吃蛇每 tick 最多吃 1 个食物）。

> **关键决策（与 v1 的差异）**：`step()`/`set_direction()`/`toggle_pause()` 不修改入参对象，而是返回新 `GameState`。FO 实现时须在 docstring 强调此点（沿用迭代 1 §2 数据传递方式关键决策）。

---

## 对外接口

### 2.1 `Difficulty` 枚举（迭代 2 调整）

```python
from enum import Enum

class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @property
    def base_tick_ms(self) -> int:
        """基线节拍（score=0 时）；迭代 2 起走 speed_curve(0, self)。
        对调用方保持兼容（迭代 1 用法仍可用）。"""
        return speed_curve(0, self)
```

> **取舍**：`base_tick_ms` property 体由迭代 1 的 `DIFFICULTY_PARAMS[self]["base_tick_ms"]` 改为 `speed_curve(0, self)`（单一数据源）。调用方无感（property 签名不变）。

### 2.2 `Point`（沿用迭代 1）

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Point:
    x: int
    y: int
```

### 2.3 `Direction` 枚举（沿用迭代 1）

```python
from enum import Enum

class Direction(Enum):
    UP    = (0, -1)
    DOWN  = (0,  1)
    LEFT  = (-1, 0)
    RIGHT = (1,  0)

    @property
    def dx(self) -> int: ...
    @property
    def dy(self) -> int: ...
    def opposite(self) -> "Direction": ...
```

### 2.4 `GameState`（迭代 2 扩展）

```python
import random
from typing import Optional, Callable

# 类型别名（仅文档用，FO 须照此实现）
ScoreCallback = Callable[[int], None]

class GameState:
    def __init__(
        self,
        width: int,
        height: int,
        difficulty: Difficulty,
        *,
        rng: Optional[random.Random] = None,
        initial_direction: Direction = Direction.RIGHT,
        score_callback: Optional[ScoreCallback] = None,
    ): ...

    # --- 只读属性（迭代 1 + 迭代 2 不变）---
    @property
    def head(self) -> Point: ...
    @property
    def score(self) -> int: ...
    @property
    def status(self) -> GameStatus: ...
    @property
    def snake(self) -> Snake: ...
    @property
    def food(self) -> Food: ...
    @property
    def direction(self) -> Direction: ...
    @property
    def difficulty(self) -> Difficulty: ...

    # --- 命令式接口（返回新 GameState，不修改 self）---

    def set_direction(self, d: Direction) -> "GameState":
        """登记期望方向；同一节拍内多次调用以最后一次为准。

        规则（迭代 2 扩展）：
          - 若 status==OVER，抛 InvalidStateError。
          - 若 status==PAUSED，**静默忽略**（不入 pending，不报错）—— FR-12 "暂停期方向输入不生效"。
          - 若 d 与当前 direction 相同，直接返回 self（幂等）。
          - 若 d 与当前 direction 反向：
              * 蛇身长度 == 1 时允许（架构「长度 1 时除外」），按反向生效；
              * 蛇身长度 >= 2 时静默忽略（连续按 WS 不致死）。
          - 其他：pending_direction = d。
        """

    def step(self) -> "GameState":
        """推进一个节拍（确定性规则，与 v1.0.0 保持一致）：
          1. 校验 status==RUN，**否则抛 InvalidStateError（含 PAUSED、OVER）**。
          2. 计算 d = pending_direction or direction
          3. 计算 next_head = head + d(d)
          4. 撞墙：next_head 越界 → status=OVER
          5. 撞自身：判定 = new_head in set(body) AND NOT (new_head == 旧尾 AND NOT 吃食)
          6. 吃食：next_head == food.pos → score += 1，生成新 food（排除蛇身），蛇身 = [next_head, *body]
              → 状态字段更新为新 GameState 后，若 _score_callback 非 None，调用 cb(new_score)
              → **回调异常不捕获**，向外抛
          7. 普通移动：蛇身 = [next_head, *body[:-1]]
          8. 提交 pending_direction → direction（每次 step 一次性消费）

        返回新 GameState。
        """

    def toggle_pause(self) -> "GameState":
        """暂停/继续切换（FR-12）。

        规则：
          - 若 status==OVER，抛 InvalidStateError（终态不可暂停/恢复）。
          - 若 status==RUN → 返回 status=PAUSED 的新 GameState；其余字段（snake/food/score/direction/pending_direction）保持不变。
          - 若 status==PAUSED → 返回 status=RUN 的新 GameState；**pending_direction 必须清空为 None**（INV-8，防止"暂停前按 UP、继续后第一拍立刻 180° 撞尾"）；其余字段保持不变。

        多次连续调用等价于两次（RUN↔PAUSED 翻转）；仅 OVER 时抛错。
        """

    def set_score_callback(self, cb: Optional[ScoreCallback]) -> "GameState":
        """注册或清空得分回调（迭代 2 新增）。返回新 GameState，不修改 self。

        适用场景：app 在游戏开始前注册 `lambda s: storage.save(max(s, storage.load()))`；
        替换回调（如重置时清空）：传 None。

        调用时机不影响当前 step；只对**之后**的 step 吃食事件生效。
        """

    def snapshot(self) -> "Snapshot":
        """返回不可变快照：
          snake_body: Tuple[Point, ...]
          food: Point
          score: int
          length: int
          status: GameStatus
          difficulty: Difficulty
          tick_ms: int   # 迭代 2 起 = speed_curve(self.score, self.difficulty)
        """
```

### 2.5 `Snapshot`（值对象，迭代 2 字段语义调整）

```python
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class Snapshot:
    snake_body: Tuple[Point, ...]
    food: Point
    score: int
    length: int
    status: GameStatus
    difficulty: Difficulty
    tick_ms: int   # 迭代 2 起 = speed_curve(score, difficulty)
```

> **差异**：迭代 1 `tick_ms` 字段值 == `difficulty.base_tick_ms`；迭代 2 改为 `speed_curve(score, difficulty)`（**随 score 动态变化**）。调用方（renderer/app）按 snapshot.tick_ms 设定定时器节拍。**字段名/类型不变**——这是非破坏性变更。

### 2.6 异常（沿用迭代 1，**取消 DirectionError 占位**）

```python
class InvalidStateError(RuntimeError):
    """对 OVER 状态调用 set_direction/step/toggle_pause；
    对 PAUSED 状态调用 step；
    OVER 状态下调用 toggle_pause；
    抛出。"""
```

> **迭代 2 修订**：移除 `DirectionError` 占位（迭代 1 已注明"当前迭代不抛"，迭代 2 确认永不抛——反向输入统一静默忽略或放行）。

### 2.7 公开 API 列表（迭代 2 扩展）

| 名称 | 类型 | 用途 | 迭代 |
|------|------|------|------|
| `Point` | dataclass(frozen) | 坐标值对象 | 1 |
| `Direction` | Enum | 4 向 + opposite/dx/dy | 1 |
| `Difficulty` | Enum | 难度 + base_tick_ms（property 走 `speed_curve(0, self)`） | 1/2 |
| `GameStatus` | Enum | RUN / PAUSED / OVER（**迭代 2 全部启用**） | 1/2 |
| `GameState` | class | 主控类 | 1/2 |
| `Snapshot` | dataclass(frozen) | 不可变状态快照（**`tick_ms` 走 `speed_curve`**） | 1/2 |
| `InvalidStateError` | Exception | 非法状态转换（**set_direction(OVER) / step(非 RUN) / toggle_pause(OVER)**） | 1/2 |
| `speed_curve(score, difficulty)` | function | 加速曲线：返回当前 score 下应使用的 tick_ms（NFR-01） | **2 新增** |
| `MIN_TICK_MS` | int（常量） | tick_ms 下限（50ms） | **2 新增** |
| `ScoreCallback` | type alias | `Callable[[int], None]` | **2 新增** |
| `GameState.set_score_callback(cb)` | method | 注册/清空得分回调 | **2 新增** |
| `GameState.toggle_pause()` | method | RUN↔PAUSED 切换 | **2 新增** |
| ~~`DIFFICULTY_PARAMS`~~ | ~~dict（仅迭代 1 用）~~ | **迭代 2 删除/保留为内部常量**：所有 tick_ms 读取走 `speed_curve` | 1 → 2 弃用 |
| ~~`DirectionError`~~ | ~~Exception~~ | **迭代 2 删除占位** | 1 → 2 弃用 |

---

## 实现细节/步骤

### 3.1 模块文件组织（迭代 2 微调）

```
game_core/
├── __init__.py          # 对外 re-export：Point, Direction, Difficulty, GameStatus, GameState, Snapshot, InvalidStateError, speed_curve, MIN_TICK_MS
├── types.py             # Point, Direction, Difficulty, GameStatus, Snapshot
├── params.py            # speed_curve(score, difficulty)、MIN_TICK_MS；_DIFFICULTY_CURVE_PARAMS 内部常量
├── state.py             # GameState（含 step/set_direction/toggle_pause/snapshot/set_score_callback）
└── errors.py            # InvalidStateError（DirectionError 删除）
```

> 导入约束沿用迭代 1：仅 `enum`、`dataclasses`、`random`、`typing` 标准库；类型注解全部走 `typing.Optional` / `typing.Tuple` / `typing.Dict` / `typing.Callable`，禁止 PEP 604 / 内置泛型。

### 3.2 核心流程（step / toggle_pause / set_direction，迭代 2 完整版）

```
set_direction(d):
  if status==OVER: raise InvalidStateError
  if status==PAUSED: return self                    # 迭代 2 新增：暂停期方向输入不生效（FR-12）
  if d == direction: return self                   # 幂等
  if d == direction.opposite():
      if len(snake) == 1:
          return self.copy(pending_direction=d)    # 长度 1 特例
      return self                                  # 长度 ≥2 反向忽略
  return self.copy(pending_direction=d)

toggle_pause():
  if status==OVER: raise InvalidStateError         # 迭代 2 新增：终态不可暂停
  if status==PAUSED:
      return self.copy(status=RUN, pending_direction=None)  # INV-8 清 pending
  # status==RUN
  return self.copy(status=PAUSED)                  # INV-9：仅 status 翻转，其余字段不变

step():
  if status != RUN: raise InvalidStateError        # 覆盖 PAUSED（迭代 2 新增分支）和 OVER
  d = pending_direction or direction
  next_head = Point(head.x + d.dx, head.y + d.dy)
  new_status = RUN
  body_set = set(snake.body)
  eating = (next_head == food.pos)

  # 撞墙
  if not (0 <= next_head.x < width and 0 <= next_head.y < height):
      new_status = OVER
      return self.copy(status=OVER, pending_direction=None)

  # 撞自身（v1 一致规则）
  body_tail = snake.body[-1]
  if next_head in body_set and not (next_head == body_tail and not eating):
      new_status = OVER
      return self.copy(status=OVER, pending_direction=None)

  # 吃食
  if eating:
      new_snake = snake.with_head_no_tail_drop(next_head)
      new_food = spawn_food(rng, width, height, new_snake)
      new_score = score + 1
  else:
      new_snake = snake.with_head(next_head).without_tail()
      new_food = food
      new_score = score

  new_state = self.copy(
      snake=new_snake, food=new_food, score=new_score,
      direction=d, pending_direction=None, status=new_status,
  )

  # 得分事件回调（迭代 2 新增；状态字段先更新，再触发回调）
  if eating and self._score_callback is not None:
      self._score_callback(new_score)  # 异常不捕获，向外抛
  return new_state
```

### 3.3 食物生成（沿用迭代 1 §3.3）

```
1. 收集所有空闲格 = {(x,y) for x in [0,W) for y in [0,H)} - set(snake.body)
2. 若空闲格为空 → 抛 RuntimeError("No space for food")
3. choice(rng, list(空闲格)) → 新食物点
```

> 性能注：默认 20×15=300 格，set 差集 + 随机选对单步开销可忽略（<0.1ms）。不引入空间索引。

### 3.4 初始布局（沿用迭代 1 §3.4）

- 蛇：3 节，居中朝右，body=[(W//2, H//2), (W//2-1, H//2), (W//2-2, H//2)]
- 食物：随机一个非蛇身位置
- direction = RIGHT
- score = 0
- status = RUN（迭代 2 起：禁止初始 PAUSED；初始 OVER 在正常 RNG 下不可达）
- pending_direction = None
- **网格下限**：`width >= 4` 且 `height >= 4`
- **`tick_ms` 计算**：`speed_curve(0, difficulty)` —— score=0 时等于 EASY=250 / MEDIUM=160 / HARD=100（与迭代 1 `base_tick_ms` 等价）

### 3.5 状态机（迭代 2 完整版）

```
                step (撞墙/撞自身)          step (正常/吃食)
NEW ─────────────────────────▶ OVER        RUN ──────────────▶ RUN
                                                       │
                                                toggle_pause()
                                                       │
                                                       ▼
                                                    PAUSED
                                                       │
                                       set_direction ─┘ (静默忽略)
                                                toggle_pause()
                                                       │
                                                       ▼
                                                      RUN  (pending_direction 清空，INV-8)

set_direction:
  OVER  → InvalidStateError
  PAUSED → 静默忽略（不入 pending）
  RUN   → 生效（含长度 1 反向特例）

step:
  非 RUN (含 PAUSED / OVER) → InvalidStateError

toggle_pause:
  OVER  → InvalidStateError
  PAUSED → RUN（清 pending_direction）
  RUN   → PAUSED
```

**与 app/GUI 的协作边界**（C2-7）：
- **P 键 / ESC 键** → app 事件循环 → `game_core.toggle_pause()`；
- **窗口失焦自动暂停** → app 主循环监听 `pygame.WINDOWFOCUSLOST` 等事件 → 调 `game_core.toggle_pause()`；
- **core 不知道"窗口/焦点/键盘"概念**，保持零 GUI 依赖（NFR-05）。

### 3.6 与迭代 1 差异（FO 实现须知，迭代 2）

| 维度 | 迭代 1 r2 | 迭代 2 r1 |
|------|-----------|-----------|
| 节拍来源 | `difficulty.base_tick_ms` 直读 DIFFICULTY_PARAMS | `speed_curve(score, difficulty)` 动态算得 |
| 暂停 | `GameStatus.PAUSED` 枚举占位、无入口 | `toggle_pause()` 方法 + RUN↔PAUSED 实际切换 |
| 暂停期 step | 抛 InvalidStateError（仅 OVER） | 抛 InvalidStateError（含 PAUSED、OVER） |
| 暂停期 set_direction | 抛 InvalidStateError（仅 OVER） | **静默忽略**（不入 pending、不抛错） |
| 暂停→继续 | — | **pending_direction 清空**（INV-8，防暂停前按 UP 导致继续后第一拍 180° 撞尾） |
| 得分事件 | 调用方读 `state.score` 自行判定 | `set_score_callback(cb)` + step 吃食时触发 `cb(new_score)` |
| `Snapshot.tick_ms` | `== difficulty.base_tick_ms` | `== speed_curve(score, difficulty)` |
| `DirectionError` | 占位 | 删除 |
| 公式 | `tick = 250/160/100`（常量） | `tick = max(50, base - k*score)`；`base/k` 三档独立 |

### 3.7 实现注意点

1. **纯函数化**：`step` / `set_direction` / `toggle_pause` / `set_score_callback` 必须返回新对象；用 `dataclasses.replace` 或自定义 `copy()` 简化。
2. **不可变 snake.body**：所有"移动/吃食"操作走 `with_head*` / `without_tail`；避免 list 原地 append。
3. **RNG 注入**：`__init__` 默认 `rng=random.Random()`（**非全局 random**），UT 显式传 `Random(42)`。
4. **不做计时**：core 不知道"时间"，仅按"节拍"推进。`tick_ms` 由 `speed_curve(score, difficulty)` 提供，渲染层/主循环按此定时。
5. **不做渲染**：core 不输出任何字符/颜色/图像，只产出 snapshot。
6. **不读盘/不写盘**：core 不引入任何 I/O；最高分持久化由 app 调 `set_score_callback(cb)` 接入 `platform-storage`，core 不持有 storage 引用。
7. **import 约束**：本模块**仅可 import 标准库**（`enum`、`dataclasses`、`random`、`typing`），禁止 `import pygame` 等。**所有类型注解使用 `typing.Optional` / `typing.Tuple` / `typing.Dict` / `typing.Callable`**——禁用 PEP 604 联合类型（`X | None`）与内置泛型下标（`tuple[...]`）。
8. **回调异常不捕获**（C2-3）：core 不在 `step` 内 try/except 包回调；调用方负责隔离。理由：core 鲁棒性边界 = "状态推进正确"，持久化失败属 app 决策；UT 中可显式构造"回调抛错"用例验证状态字段仍正确。
9. **OVER 与 PAUSED 互斥**：`status` 字段单一枚举值；OVER → toggle_pause 抛错；PAUSED → 撞墙/撞身检测不会被 step 触达（step 入口先校验 RUN）。

---

## DFx / 可测试性 / 鲁棒性 / 韧性

### 4.1 可维护性（Maintainability）
- 每个公开类/方法有 docstring，标注对应 FR/NFR 编号（如 `"""FR-12 暂停/继续。FR-13 得分事件入口。NFR-05 零 GUI 依赖。"""`）
- 关键不变量在代码中以注释 + UT 用例双标注（INV-1~10）
- 单一职责：state.py 只管状态推进；types.py 只管值对象；params.py 只管参数表（**迭代 2 起含 `speed_curve` + `MIN_TICK_MS`**）

### 4.2 可扩展性（Extensibility）
- **加速曲线单一数据源**：`speed_curve()` 是唯一节拍计算入口；调参（换曲线公式 / 加档位 / 改下限）只改 `params.py` 一处；`Difficulty.base_tick_ms` property 与 `Snapshot.tick_ms` 都走它，调用方无感
- **`set_score_callback(cb)` 接口可替换**：未来迭代若需"吃不同食物得不同分"或"特殊食物事件"，只需扩展 callback 类型（`Callable[[ScoreEvent], None]`），不破坏既有签名
- **状态机扩展性**：`GameStatus` 枚举仅 RUN/PAUSED/OVER；未来若加"REPLAY/REVIEW"等不破坏既有接口（仅新增枚举值 + 状态转换规则）
- **`toggle_pause()` 仅读写 status + INV-8 清 pending**：未来若加"暂停时显示半透明遮罩"等 UI 副作用，app 监听 status 变化即可，core 不知情
- **食物生成抽象为内部函数**：迭代 3 若需"特殊食物"可扩展

### 4.3 可部署性（Deployability）
- 纯标准库，PyInstaller 打包时**无需 hook**
- 单一包目录 `game_core/`，可独立 wheel 化
- 无 C 扩展、无平台特定代码
- 迭代 2 增量（speed_curve / toggle_pause / on_score 回调）均为纯 Python 函数，无新增依赖

### 4.4 可测试性（Testability）
- **零 GUI 依赖**：UT 全部在内存里跑，无需显示器/窗口
- **RNG 注入**：UT 可固定 seed 复现
- **纯函数化**：`step` / `toggle_pause` / `set_score_callback` 返回新对象，UT 可断言 `old == snapshot_before` 不被改
- **可枚举**：`width × height ≤ 300`（默认网格），暴力枚举所有位置组合做穷举 UT 可行
- **无时间/IO**：不需要 mock time.sleep、不需要 tmp_path
- **回调可观测**（C2-3）：UT 可传 `lambda s: events.append(s)` 验证得分时机/次数/参数；可传 `lambda s: raise RuntimeError("...")` 验证 core 不吞异常
- **暂停状态机分支完全可枚举**：RUN→PAUSED、PAUSED→RUN、OVER 各分支独立 UT

### 4.5 鲁棒性 / 韧性

| 场景 | 处理 | 迭代 |
|------|------|------|
| 反向输入（长度 ≥ 2） | 静默忽略（连续按 WS 不致死） | 1 |
| 反向输入（长度 == 1） | 允许按反向生效 | 1 |
| 同一节拍多次 set_direction | 取最后一次（pending_direction） | 1 |
| status==OVER 后 step | 抛 `InvalidStateError` | 1 |
| **status==PAUSED 后 step** | **抛 `InvalidStateError`（FR-12：暂停期不推进节拍）** | **2 新增** |
| **status==PAUSED 后 set_direction** | **静默忽略（FR-12：暂停期方向输入不生效）** | **2 新增** |
| **status==PAUSED 后 toggle_pause** | **返回 RUN（INV-8 清 pending_direction）** | **2 新增** |
| **status==RUN 后 toggle_pause** | **返回 PAUSED（INV-9：仅 status 翻转）** | **2 新增** |
| **status==OVER 后 toggle_pause** | **抛 `InvalidStateError`** | **2 新增** |
| **暂停前按 UP、点窗口失焦自动暂停、再点继续** | **INV-8：toggle_pause(PAUSED→RUN) 清 pending，继续后第一拍按原方向走，不会 180° 撞尾** | **2 新增** |
| 状态推进中食物生成冲突 | 排除蛇身后随机；全屏填满抛 RuntimeError | 1 |
| 网格宽高 < 4 或 0 | `__init__` 抛 `ValueError` | 1 |
| 难度传入非法值 | `Difficulty` 枚举约束，构造时类型即拦截 | 1 |
| **得分回调内抛异常** | **core 不捕获，异常向外抛；状态字段已正确更新为新 GameState** | **2 新增** |
| **得分回调为 None** | **静默，无副作用** | **2 新增** |
| **反复 toggle_pause** | **等价于 2 次（RUN↔PAUSED 翻转）；OVER 抛错** | **2 新增** |
| 初始 RNG 不传 | 默认 `random.Random()`（实例，非全局） | 1 |
| **`speed_curve` score 极大** | **钳制 `tick_ms >= MIN_TICK_MS=50`，不抛错**（如 MEDIUM score=100 → max(50, 160-4*100)=max(50,-240)=50） | **2 新增** |
| **`speed_curve` score 为负** | **直接代入公式**（如 EASY score=-1 → max(50, 250-4*-1)=max(50,254)=254）；**UT 不承诺负 score 业务语义，但函数不抛错** | **2 新增** |

### 4.6 错误处理矩阵（迭代 2 扩展）

| 错误情形 | 行为 | 迭代 |
|----------|------|------|
| `set_direction` 时 status==OVER | `InvalidStateError` | 1 |
| **`set_direction` 时 status==PAUSED** | **静默忽略，返回 self** | **2 新增** |
| `set_direction` 反向，长度 ≥ 2 | 静默忽略，返回 self | 1 |
| `set_direction` 反向，长度 == 1 | 允许（按反向生效），返回新 state | 1 |
| `step` 时 status==OVER | `InvalidStateError` | 1 |
| **`step` 时 status==PAUSED** | **`InvalidStateError`** | **2 新增** |
| **`toggle_pause` 时 status==OVER** | **`InvalidStateError`** | **2 新增** |
| `__init__` width<4 or height<4 | `ValueError` | 1 |
| `__init__` difficulty 非 Difficulty 枚举 | `TypeError`（枚举自动） | 1 |
| 食物生成时空闲格为 0 | `RuntimeError("No space for food")` | 1 |
| **得分回调抛异常** | **异常向外传；状态字段已正确更新（callable 抛错前 `copy()` 已完成）** | **2 新增** |

---

## 资源评估

| 资源 | 评估 | 迭代 |
|------|------|------|
| **CPU** | `step` 单次 O(W·H) 用于食物生成冲突检测（set 差集），默认 300 格 <0.1ms；`speed_curve` O(1)；移动 O(1)；`toggle_pause` O(1)。整体 CPU 占用 <1% 单核 | 1/2 |
| **内存** | `GameState` 单对象 <1KB；`Snapshot` 拷贝蛇身 tuple（W·H ≤ 300 个 Point ≈ 5KB）。千帧/秒不积压。**迭代 2 新增 `_score_callback` 引用（1 个对象指针）可忽略** | 1/2 |
| **存储** | 0（无 I/O） | 1 |
| **外部依赖** | 0（仅 Python 3.8+ 标准库） | 1 |
| **线程** | 非线程安全；调用方（app 主循环）单线程访问，UT 单线程跑 | 1 |
| **GIL** | 不影响（无阻塞 I/O、无 C 扩展） | 1 |
| **打包体积** | 0 增量（PyInstaller 不会把 core 单独算） | 1 |
| **回调开销** | `_score_callback is not None` 检查 O(1)；调用开销 = 用户函数本身（典型为 storage.save ~ 1ms 含原子写） | **2 新增** |

---

## UT 框架（FO TDD 依据）

### 5.1 测试组织（迭代 2 扩展）

```
tests/
└── test_game_core/
    ├── __init__.py
    ├── test_point.py                # Point 值对象
    ├── test_direction.py            # Direction 枚举
    ├── test_difficulty.py           # Difficulty.base_tick_ms 走 speed_curve(0, self)
    ├── test_state_init.py           # 构造、网格下限校验
    ├── test_state_set_direction.py  # set_direction 各输入（含长度 1 反向、PAUSED 期静默忽略、OVER 抛错）
    ├── test_state_step_move.py      # 普通移动
    ├── test_state_step_eat.py       # 吃食：score+1、不丢尾、新食物不在蛇身
    ├── test_state_step_collide_wall.py
    ├── test_state_step_collide_self.py
    ├── test_state_step_collide_tail.py
    ├── test_state_step_over_guard.py    # OVER 后 step 抛错
    ├── test_state_step_paused_guard.py  # 【迭代 2 新增】PAUSED 后 step 抛错
    ├── test_state_direction_pending.py
    ├── test_state_reversal_block.py
    ├── test_state_snapshot.py       # snapshot 不可变、tick_ms 走 speed_curve
    ├── test_state_determinism.py
    ├── test_state_food_spawn.py
    ├── test_state_pause.py          # 【迭代 2 新增】toggle_pause 全部分支（RUN↔PAUSED、OVER 抛错、INV-8 清 pending、INV-9 字段冻结）
    ├── test_state_score_callback.py # 【迭代 2 新增】on_score 回调时机/参数/异常不捕获/None 静默/替换回调
    ├── test_speed_curve.py          # 【迭代 2 新增】speed_curve 参数化（NFR-01 量化：HARD ≤ EASY*0.5、下限钳制、单调性）
    └── test_state_inv8_pending_clear.py  # 【迭代 2 新增】暂停前按 UP → 暂停 → 继续 → 第一拍按原方向走（非 UP）
```

> **统一使用 unittest**（对齐 v1 验证模式 + 迭代 1 已落地）。

### 5.2 桩与夹具（test_state_pause.py 等）

```python
import unittest
import random
from game_core import GameState, Difficulty, Direction

class _GameCoreBase(unittest.TestCase):
    """测试基类：setUp 内构造固定 RNG 的默认 state + 回调收集器"""

    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.score_events = []
        self.default_state = GameState(
            width=20, height=15,
            difficulty=Difficulty.MEDIUM,
            rng=self.rng,
            score_callback=lambda s: self.score_events.append(s),
        )

    def make_small_state(self, rng=None, difficulty=None):
        """5x5 网格，便于穷举"""
        return GameState(
            width=5, height=5,
            difficulty=difficulty or Difficulty.MEDIUM,
            rng=rng or random.Random(42),
        )
```

### 5.3 断言规范（沿用迭代 1 §5.3）

- **不变量优先**：每个 UT 至少断言一条 INV（1~10）
- **纯函数性质**：先取 `before = state.snapshot()`，再 `after = state.step()`，断言 `before == state.snapshot()`（state 自身未变）
- **覆盖分支**：每个 step 内部分支（撞墙/撞自身/吃食/普通移动/终态）独立测试
- **参数化**：方向枚举、难度枚举用 `subTest` 循环
- **UT 命名**：`test_{动作}_{场景}_{期望}`

### 5.4 必须覆盖的 UT 用例清单（FO 必写，迭代 1 + 迭代 2 合并）

#### 迭代 1 基线用例（21 条，沿用 §5.4）

| # | 场景 | 断言 |
|---|------|------|
| 1 | 初始构造 | 蛇长 3、初始方向 RIGHT、score=0、status=RUN、food 不在蛇身 |
| 2 | 普通前进 | step 后蛇头按方向移动、蛇尾移除、score 不变 |
| 3 | 吃食 | step 后蛇长+1、score+1、新食物不在蛇身 |
| 4 | 撞墙 | 头出界 → status=OVER，分数/蛇身不变 |
| 5 | 撞自身 | 头撞非尾身段 → status=OVER |
| 6 | 撞尾（不吃食） | 头撞旧尾且本 tick 不吃食 → 不结束，蛇身让行 |
| 6b | 撞尾（吃食） | 头撞旧尾且本 tick 吃食 → status=OVER |
| 7 | OVER 保护 | status=OVER 后 step 抛 InvalidStateError |
| 8 | OVER 保护 | status=OVER 后 set_direction 抛 InvalidStateError |
| 9a | 反向禁止（长度 ≥ 2） | set_direction(opposite) 后 step，蛇仍按原方向走 |
| 9b | 反向特例（长度 1） | 单节蛇身时 set_direction(opposite) 后 step，蛇按反向走 |
| 10 | 幂等 | set_direction(同方向) 返回值与 self.snapshot 相等 |
| 11 | pending 合并 | set_direction(UP) → set_direction(LEFT) → step，按 LEFT 走 |
| 12 | 固定 seed | 同 seed 两次构造 → 初始食物坐标一致 |
| 13 | snapshot 不可变 | snapshot 字段不能赋值（frozen dataclass） |
| 14 | 非法网格（< 4） | 抛 ValueError |
| 14b | 合法下限 4x4 | 构造成功、初始蛇身全部在界内 |
| 15 | 难度参数 | 三档 base_tick_ms = 250/160/100 |
| 15b | 参数化数据源 | 修改 `_DIFFICULTY_CURVE_PARAMS[EASY]["base"]` 后 `Difficulty.EASY.base_tick_ms` 返回新值 |
| 16 | 食物全屏 | 构造 snake 填满 5×5 → spawn_food 抛 RuntimeError |
| 17 | 帧内 set_direction 不立即变 direction | set_direction(UP) 后 state.direction 仍为 RIGHT |
| 18 | step 后清 pending | step 一次后 pending_direction=None |
| 19 | 端到端 100 步 | 固定 seed 跑 100 步，验证 score 变化曲线与蛇身长度一致 |
| 20 | snapshot.tick_ms (iter1) | 迭代 1：== difficulty.base_tick_ms |
| 21 | 语法兼容 3.8 | 用 python3.8 跑测试；确保无 PEP 604 / 内置泛型下标 |

#### 迭代 2 增量用例（14 条）

| # | 场景 | 断言 |
|---|------|------|
| 22 | **speed_curve NFR-01 量化** | `speed_curve(0, EASY)==250`、`speed_curve(0, MEDIUM)==160`、`speed_curve(0, HARD)==100` |
| 23 | **speed_curve HARD ≤ EASY\*0.5** | 对 `score in [0, 100]`，`speed_curve(score, HARD) <= speed_curve(score, EASY) * 0.5`（subTest 循环） |
| 24 | **speed_curve 单调不增** | 对 `score in [0, 100]`，`speed_curve(score+1, d) <= speed_curve(score, d)`（三档 subTest） |
| 25 | **speed_curve 下限钳制** | `speed_curve(100, MEDIUM) == MIN_TICK_MS == 50` |
| 26 | **snapshot.tick_ms 走 speed_curve** | 构造 state、step N 次吃到 score=N 的食物，snapshot.tick_ms == speed_curve(N, difficulty) |
| 27 | **toggle_pause RUN→PAUSED** | `default_state.toggle_pause().status == PAUSED` |
| 28 | **toggle_pause PAUSED→RUN** | `default_state.toggle_pause().toggle_pause().status == RUN` |
| 29 | **toggle_pause OVER 抛错** | 构造 OVER 状态 → `toggle_pause()` 抛 `InvalidStateError` |
| 30 | **toggle_pause 字段冻结（INV-9）** | `before = default_state.snapshot()` → `after = default_state.toggle_pause()` → `after.snake_body == before.snake_body` 且 `after.score == before.score` 且 `after.food == before.food` |
| 31 | **INV-8 暂停→继续 清 pending** | `state.set_direction(UP).toggle_pause().toggle_pause().pending_direction is None`（防暂停前按 UP 导致继续后第一拍 180° 撞尾） |
| 32 | **PAUSED 期 step 抛错** | `default_state.toggle_pause().step()` 抛 `InvalidStateError` |
| 33 | **PAUSED 期 set_direction 静默忽略** | `paused = default_state.toggle_pause()`；`after = paused.set_direction(LEFT)`；`after.status == PAUSED`、`after.pending_direction is None`、**无 InvalidStateError** |
| 34 | **PAUSED 期 set_direction 不入 pending** | 恢复 RUN 后第一拍按原 direction 走（不是 LEFT） |
| 35 | **PAUSED→RUN 恢复后第一拍按 INV-8 后方向走** | `state.set_direction(UP).toggle_pause().toggle_pause().step()`：第一步按 RIGHT（原 direction）走，不按 UP（INV-8 已清 pending） |
| 36 | **on_score 回调触发** | step 吃到食物 → `score_events == [1]`；再 step 吃到 → `[1, 2]` |
| 37 | **on_score 回调参数 = new_score** | 多次吃食 → events 与每次 new_score 严格对应 |
| 38 | **on_score 回调 None 静默** | `state = GameState(..., score_callback=None)`；step 吃食不抛错、score 字段正确更新 |
| 39 | **on_score 回调异常不捕获** | `state = GameState(..., score_callback=lambda s: raise RuntimeError("test"))`；`state.step()` 抛 `RuntimeError`；**状态字段已正确更新**（step 返回前的 new_state 已含新 score） |
| 40 | **on_score 回调替换** | `state = state.set_score_callback(new_cb)`；后续 step 吃食触发 new_cb，旧 cb 不再被调 |
| 41 | **on_score 回调非吃食不触发** | 普通移动 step → `score_events == []` |

### 5.5 覆盖率目标（迭代 2 提升）

- **行覆盖 ≥ 95%**（`state.py` 必须 100%；`params.py` 必须 100%）
- **分支覆盖 ≥ 92%**（迭代 1 90% 基础上 + toggle_pause 三分支、set_direction PAUSED/OVER 双分支、speed_curve score 边界）
- **不变量测试**：每条 INV 至少 1 个用例引用（INV-1~10 全覆盖）

### 5.6 UT 运行命令（沿用迭代 1 §5.6）

```bash
python3 -m unittest discover -s tests/test_game_core -v

pytest tests/test_game_core -v --cov=game_core --cov-branch --cov-fail-under=95
```

### 5.7 FO TDD 实施步骤（建议）

迭代 1 已落地的 §5.7 步骤（1~9）继续有效；迭代 2 增量：

1. 写 `test_speed_curve.py` → 跑（红）→ 写 `params.speed_curve` + `MIN_TICK_MS`（绿，覆盖 NFR-01 量化）
2. 调整 `Difficulty.base_tick_ms` property 走 `speed_curve(0, self)`（同步更新 `test_difficulty.py` #15b）
3. 写 `test_state_pause.py` → 跑（红）→ 写 `toggle_pause()`（绿，覆盖 RUN↔PAUSED、OVER 抛错、INV-8/9）
4. 写 `test_state_step_paused_guard.py` + 扩展 `test_state_set_direction.py`（PAUSED 分支）→ 跑（红）→ 改 `step` / `set_direction` 加 PAUSED 分支
5. 写 `test_state_inv8_pending_clear.py`（核心防呆 UT，验证暂停前按 UP → 继续后第一拍按原方向）→ 跑（红）→ `toggle_pause` 内部加 `pending_direction=None`
6. 写 `test_state_score_callback.py` → 跑（红）→ 写 `_score_callback` 字段、`set_score_callback` 方法、`step` 内回调触发（异常不捕获）
7. 写 `test_state_snapshot.py` #26 增量断言 `tick_ms == speed_curve(score, difficulty)` → 跑（红）→ `snapshot()` 内调 `speed_curve`
8. **严格 RED-GREEN-REFACTOR**，UT 写完先红，实现只补到变绿，**不要超前写未测代码**。

---

## 附录 A：迭代 2 → 迭代 3 增量接口预告（仅供 FO 留扩展点，不在本次实现）

- **食物扩展**：若迭代 3 gui-renderer 需"特殊食物"（加速/减速/加分），可扩 `Food` 加 `kind: FoodKind` 枚举；`spawn_food` 按 kind 概率分布；**接口新增字段，非破坏性**。
- **难度游戏中切换**：当前架构约束"难度游戏中不可切换"（FR-05 防规避），本设计**不预留**切换接口；如未来需支持，应走"开新局"语义（`new_game(difficulty)` 方法），不原地改 difficulty。
- **状态机扩展**：若迭代 4 需"死亡回放/慢动作回放"，可扩 `GameStatus` 加 `REPLAY`；`snapshot` 已 frozen，加枚举值不破坏既有 UT。
- **回调类型扩展**：若未来需"特殊食物事件"（区别于普通得分），可改 `ScoreCallback = Callable[[ScoreEvent], None]`；向后兼容（旧 callback 接 ScoreEvent 会失败时由 app 适配）。

接口扩展原则：默认参数 + 新增方法 + 新增枚举值，**不破坏迭代 2 既有签名**。

---

## 附录 B：迭代 1 r2 → 迭代 2 r1 修订对照表（便于复评核对）

| 评审 / 设计 ID | 级别 | 本文档修订位置 | 关键变化 |
|---------------|------|----------------|----------|
| C2-1 | 应实现 | §1.2 / §2.1 / §2.4 / §2.5 / §3.1 / §3.2 / §3.6 / §5.1 / §5.4 #22~26 | 新增 `speed_curve(score, difficulty)` 替代 `DIFFICULTY_PARAMS` 直读；公式 `max(50, base - k*score)`；`Difficulty.base_tick_ms` property 改走 `speed_curve(0, self)`；`Snapshot.tick_ms` 改走 `speed_curve(score, difficulty)`；`params.py` 新增 `_DIFFICULTY_CURVE_PARAMS` 内部常量 |
| C2-2 | 应实现 | §2.4 / §3.2 / §3.5 / §4.5 / §4.6 / §5.4 #27~30 | 新增 `toggle_pause()` 方法；RUN↔PAUSED 切换；OVER 抛错；其余字段冻结（INV-9） |
| C2-3 | 应实现 | §2.4 / §3.2 / §3.7 / §4.5 / §4.6 / §5.4 #36~41 | 新增 `_score_callback` 字段、`set_score_callback(cb)` 方法；step 吃食时触发；异常不捕获；None 静默；非吃食不触发 |
| C2-4 | 应实现 | §3.2 / §3.5 / §4.5 / §4.6 / §5.4 #32~35 | step 入口校验 RUN（含 PAUSED/OVER）；set_direction PAUSED 静默忽略；toggle_pause PAUSED→RUN 清 pending |
| C2-5 | 应实现 | §1.4 INV-8/9/10 + §3.2 toggle_pause 流程 + §3.5 状态机图 + §5.4 #31 | 新增 INV-8（清 pending）、INV-9（字段冻结）、INV-10（NFR-01 量化不变量） |
| C2-6 | 应实现 | §5.1 / §5.4 #22~41 | 新增 test_speed_curve.py / test_state_pause.py / test_state_score_callback.py / test_state_inv8_pending_clear.py / test_state_step_paused_guard.py；UT 总数 21 → 41；行/分支覆盖率标准提升 |
| C2-7 | 约束 | §3.5 / §4.5 | core 不引入窗口/焦点概念；app 监听 pygame 事件调 `toggle_pause()`；保持 NFR-05 零 GUI 依赖 |
| C2-8 | 约束 | §1.2 / §4.5 / §5.4 #22~25 | NFR-01 量化约束：score=0 时三档 250/160/100；任意 score `HARD ≤ EASY*0.5`；下限 50ms；speed_curve 单调不增 |
| 迭代 1 留档 | — | §1.2 / §2.7 | `DIFFICULTY_PARAMS`（迭代 1 形态）保留为内部常量但**不再作为 tick 来源**；`DirectionError` 占位**删除** |
