"""state 模块：GameState 主控类与 spawn_food 内部函数。

实现 FR-01~05 玩法核心；NFR-05 零 GUI 依赖（仅标准库）。

关键约束：
- step()/set_direction() 返回新对象，不修改入参（纯函数语义）
- RNG 注入；默认实例 random.Random()（非全局）
- 网格下限 width>=4 且 height>=4（INV-7）
- 反向移动：长度 1 允许、长度 ≥2 静默忽略
- 撞自身判定：v1 一致——next_head in body_set AND NOT (next_head == 旧尾 AND NOT eating)
"""
from __future__ import annotations
import dataclasses
import random
from typing import Any, Optional, Tuple

from .types import (
    Direction, Difficulty, Food, GameStatus, Point, Snake, Snapshot,
)
from .errors import InvalidStateError


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
        "_last_step": None,
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
      - _last_step：Optional[int]（迭代 1 占位）

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
    _last_step: Optional[int]

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        # 区分"用户构造（少字段）"与"dataclasses.replace（全字段）"
        if "snake" in kwargs and "food" in kwargs and "rng" in kwargs:
            # dataclasses.replace 路径：直接写入全部字段
            for k, v in kwargs.items():
                object.__setattr__(self, k, v)
            return

        # 用户构造路径：仅接受 width/height/difficulty/rng/initial_direction
        allowed = {"width", "height", "difficulty", "rng", "initial_direction"}
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

        for k, v in _build_initial(width, height, difficulty, rng, initial_direction).items():
            object.__setattr__(self, k, v)

    # ---------- 只读便捷属性 ----------
    @property
    def head(self) -> Point:
        return self.snake.head

    # ---------- 命令式接口（返回新 GameState，不修改 self）----------

    def set_direction(self, d: Direction) -> "GameState":
        """登记期望方向；同一节拍多次调用以最后一次为准。

        规则：
          - status==OVER → InvalidStateError
          - d == direction（幂等）→ 返回 self
          - d == direction.opposite():
              * len(snake) == 1 → 允许（架构特例）
              * len(snake) >= 2 → 静默忽略
        """
        if self.status == GameStatus.OVER:
            raise InvalidStateError("Cannot set_direction on OVER state")

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

        1. 校验 status==RUN，否则抛 InvalidStateError
        2. d = pending_direction or direction
        3. next_head = head + d(d)
        4. 撞墙 → OVER，蛇身/食物/得分不变
        5. 撞自身（v1 一致规则）：
           next_head in body_set AND NOT (next_head == 旧尾 AND NOT eating)
        6. 吃食 → score+1, food 重生（排除蛇身）
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

        # 8. 提交 pending
        return dataclasses.replace(
            self,
            snake=new_snake,
            food=new_food,
            score=new_score,
            direction=d,
            pending_direction=None,
            status=GameStatus.RUN,
        )

    def snapshot(self) -> Snapshot:
        """返回不可变快照：供 renderer 读取。"""
        return Snapshot(
            snake_body=self.snake.body,
            food=self.food.pos,
            score=self.score,
            length=len(self.snake.body),
            status=self.status,
            difficulty=self.difficulty,
            tick_ms=self.difficulty.base_tick_ms,
        )