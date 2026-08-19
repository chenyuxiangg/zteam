"""state 模块：GameState 主控类与 spawn_food 内部函数。

实现 FR-01~05 玩法核心 + 迭代 2 增量（speed_curve 集成 / toggle_pause / 得分回调）。
NFR-05 零 GUI 依赖（仅标准库）。

关键约束：
- step()/set_direction()/toggle_pause()/set_score_callback() 返回新对象，不修改入参（纯函数语义）
- RNG 注入；默认实例 random.Random()（非全局）
- 网格下限 width>=4 且 height>=4（INV-7）
- 反向移动：长度 1 允许、长度 ≥2 静默忽略
- 撞自身判定：v1 一致——next_head in body_set AND NOT (next_head == 旧尾 AND NOT eating)
- 暂停期：step 抛错，set_direction 静默忽略；toggle_pause 翻转 + INV-8 清 pending
- 得分回调：构造或 set_score_callback 注册；step 吃食触发；异常不捕获（pure-function 语义）
"""
from __future__ import annotations
import dataclasses
import random
from typing import Any, Optional, Tuple, Callable

from .types import (
    Direction, Difficulty, Food, GameStatus, Point, Snake, Snapshot,
)
from .errors import InvalidStateError
from .params import speed_curve


# 得分回调类型别名（仅文档，FO 须照此暴露）
ScoreCallback = Callable[[int], None]


def spawn_food(
    rng: random.Random,
    width: int,
    height: int,
    snake_body: Tuple[Point, ...],
) -> Food:
    """在非蛇身空闲格中随机生成新食物。

    排除蛇身后从 (W*H - len(body)) 个空闲格中随机选一个。
    若空闲格为空（全屏填满蛇）→ 抛 RuntimeError。
    """
    body_set = set(snake_body)
    free: list = []
    for y in range(height):
        for x in range(width):
            p = Point(x, y)
            if p not in body_set:
                free.append(p)
    if not free:
        raise RuntimeError("No space for food")
    return Food(rng.choice(free))


def _build_initial(
    width: int,
    height: int,
    difficulty: Difficulty,
    rng: Optional[random.Random],
    initial_direction: Direction,
    score_callback: Optional[ScoreCallback],
) -> dict:
    """构造初始字段 dict（供 GameState(**kwargs) 使用）。"""
    if width < 4 or height < 4:
        raise ValueError(
            f"Grid too small: width={width}, height={height} (minimum 4x4)"
        )

    cx = width // 2
    cy = height // 2
    snake = Snake((Point(cx, cy), Point(cx - 1, cy), Point(cx - 2, cy)))
    rng_instance: random.Random = rng if rng is not None else random.Random()
    food = spawn_food(rng_instance, width, height, snake.body)

    return {
        "width": width,
        "height": height,
        "difficulty": difficulty,
        "snake": snake,
        "direction": initial_direction,
        "pending_direction": None,
        "food": food,
        "score": 0,
        "status": GameStatus.RUN,
        "rng": rng_instance,
        "_score_callback": score_callback,
    }


@dataclasses.dataclass(frozen=True)
class GameState:
    """游戏主控：纯函数式状态推进。

    字段（不可变）：
      - width / height / difficulty：网格与难度
      - snake：Snake（不可变 tuple body）
      - direction / pending_direction：当前方向 / 待生效方向
      - food：Food
      - score：int
      - status：GameStatus
      - rng：random.Random（注入实例；INV-6：非全局）
      - _score_callback：Optional[Callable[[int], None]]（迭代 2 新增；field repr=False, compare=False）

    `__init__` 接受所有字段：构造时（只给 width/height/difficulty）走默认初始布局；
    dataclasses.replace 调用时（给全部字段）跳过默认布局构造。
    """
    width: int
    height: int
    difficulty: Difficulty
    snake: Snake
    direction: Direction
    pending_direction: Optional[Direction]
    food: Food
    score: int
    status: GameStatus
    rng: random.Random
    _score_callback: Optional[ScoreCallback] = dataclasses.field(
        default=None, repr=False, compare=False
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        # 区分"用户构造（少字段）"与"dataclasses.replace（全字段）"
        # dataclasses.replace 会传全部字段（除非显式 exclude）；我们检查 snake/food/rng 是否都给了
        if "snake" in kwargs and "food" in kwargs and "rng" in kwargs:
            # dataclasses.replace 路径：直接写入全部字段
            for k, v in kwargs.items():
                object.__setattr__(self, k, v)
            return

        # 用户构造路径：仅接受 width/height/difficulty/rng/initial_direction/score_callback
        allowed = {"width", "height", "difficulty", "rng", "initial_direction", "score_callback"}
        extra = set(kwargs.keys()) - allowed
        if extra:
            raise TypeError(f"Unexpected keyword arguments: {sorted(extra)}")
        if args:
            raise TypeError("GameState only accepts keyword arguments")

        width: int = kwargs["width"]
        height: int = kwargs["height"]
        difficulty: Difficulty = kwargs["difficulty"]
        rng: Optional[random.Random] = kwargs.get("rng", None)
        initial_direction: Direction = kwargs.get("initial_direction", Direction.RIGHT)
        score_callback: Optional[ScoreCallback] = kwargs.get("score_callback", None)

        for k, v in _build_initial(
            width, height, difficulty, rng, initial_direction, score_callback
        ).items():
            object.__setattr__(self, k, v)

    # ---------- 只读便捷属性 ----------
    @property
    def head(self) -> Point:
        return self.snake.head

    # ---------- 命令式接口（返回新 GameState，不修改 self）----------

    def set_direction(self, d: Direction) -> "GameState":
        """登记期望方向；同一节拍多次调用以最后一次为准。

        规则（迭代 2 扩展）：
          - status==OVER → InvalidStateError
          - status==PAUSED → 静默忽略（不入 pending，FR-12）
          - d == direction（幂等）→ 返回 self
          - d == direction.opposite():
              * len(snake) == 1 → 允许（架构特例）
              * len(snake) >= 2 → 静默忽略
        """
        if self.status == GameStatus.OVER:
            raise InvalidStateError("Cannot set_direction on OVER state")

        # 迭代 2：PAUSED 期静默忽略（FR-12）
        if self.status == GameStatus.PAUSED:
            return self

        if d == self.direction:
            return self  # 幂等

        if d == self.direction.opposite():
            if len(self.snake) == 1:
                # 长度 1 反向特例：按反向生效
                return dataclasses.replace(self, pending_direction=d)
            return self  # 静默忽略

        # 合法方向（含垂直于当前方向）
        return dataclasses.replace(self, pending_direction=d)

    def step(self) -> "GameState":
        """推进一个节拍（确定性规则，与 v1.0.0 行为一致）。

        1. 校验 status==RUN，否则抛 InvalidStateError（含 PAUSED、OVER）
        2. d = pending_direction or direction
        3. next_head = head + d(d)
        4. 撞墙 → OVER
        5. 撞自身（v1 一致规则）
        6. 吃食 → score+1, food 重生（排除蛇身），触发得分事件（异常不捕获）
        7. 普通移动 → 头进尾出
        8. 提交 pending_direction → direction（消费 pending）
        """
        if self.status != GameStatus.RUN:
            raise InvalidStateError(
                f"step() requires RUN status, current={self.status.value}"
            )

        d = self.pending_direction if self.pending_direction is not None else self.direction
        next_head = Point(self.head.x + d.dx, self.head.y + d.dy)
        eating = (next_head == self.food.pos)

        # 4. 撞墙
        if not (0 <= next_head.x < self.width and 0 <= next_head.y < self.height):
            return dataclasses.replace(
                self, status=GameStatus.OVER, pending_direction=None
            )

        # 5. 撞自身（v1 一致规则）
        body_set = set(self.snake.body)
        body_tail = self.snake.body[-1]
        if next_head in body_set and not (next_head == body_tail and not eating):
            return dataclasses.replace(
                self, status=GameStatus.OVER, pending_direction=None
            )

        # 6 / 7. 吃食 / 普通移动
        if eating:
            new_snake = self.snake.with_head_no_tail_drop(next_head)
            new_food = spawn_food(self.rng, self.width, self.height, new_snake.body)
            new_score = self.score + 1
        else:
            new_snake = self.snake.with_head(next_head).without_tail()
            new_food = self.food
            new_score = self.score

        # 8. 提交 pending → 新 state
        new_state = dataclasses.replace(
            self,
            snake=new_snake,
            food=new_food,
            score=new_score,
            direction=d,
            pending_direction=None,
            status=GameStatus.RUN,
        )

        # 得分事件回调（C2-3）：状态字段已更新为 new_state 后调用；
        # 异常不捕获，向外抛（pure-function 语义：new_state 不交付给调用方）
        if eating and self._score_callback is not None:
            self._score_callback(new_score)
        return new_state

    def toggle_pause(self) -> "GameState":
        """暂停/继续切换（FR-12）。

        规则：
          - status==OVER → InvalidStateError（终态不可暂停/恢复）
          - status==RUN → 返回 status=PAUSED 的新 GameState；其余字段冻结（INV-9）
          - status==PAUSED → 返回 status=RUN 的新 GameState；
            **pending_direction 清空为 None（INV-8）**；
            其余字段保持不变
        """
        if self.status == GameStatus.OVER:
            raise InvalidStateError("Cannot toggle_pause on OVER state")

        if self.status == GameStatus.PAUSED:
            # PAUSED → RUN：清 pending_direction（INV-8）
            return dataclasses.replace(
                self, status=GameStatus.RUN, pending_direction=None
            )

        # RUN → PAUSED：仅 status 翻转（INV-9）
        return dataclasses.replace(self, status=GameStatus.PAUSED)

    def set_score_callback(self, cb: Optional[ScoreCallback]) -> "GameState":
        """注册或清空得分回调（迭代 2 新增）。返回新 GameState，不修改 self。

        适用场景：app 在游戏开始前注册
          `lambda s: storage.save(max(s, storage.load()))`；
        替换回调（如重置时清空）：传 None。
        """
        return dataclasses.replace(self, _score_callback=cb)

    def snapshot(self) -> Snapshot:
        """返回不可变快照：供 renderer 读取。

        迭代 2 起：tick_ms = speed_curve(self.score, self.difficulty)。
        """
        return Snapshot(
            snake_body=self.snake.body,
            food=self.food.pos,
            score=self.score,
            length=len(self.snake.body),
            status=self.status,
            difficulty=self.difficulty,
            tick_ms=speed_curve(self.score, self.difficulty),
        )