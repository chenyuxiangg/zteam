"""types 模块：值对象与枚举定义。"""
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


@dataclass(frozen=True)
class Point:
    """网格坐标值对象（不可变）。y 向下，0,0 为左上角。"""
    x: int
    y: int


class Direction(Enum):
    """4 向枚举；opposite() 返回反向。"""
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

    @property
    def dx(self) -> int:
        return self.value[0]

    @property
    def dy(self) -> int:
        return self.value[1]

    def opposite(self) -> "Direction":
        # UP<->DOWN, LEFT<->RIGHT
        return _OPPOSITE[self]


_OPPOSITE = {
    Direction.UP: Direction.DOWN,
    Direction.DOWN: Direction.UP,
    Direction.LEFT: Direction.RIGHT,
    Direction.RIGHT: Direction.LEFT,
}


class Difficulty(Enum):
    """难度档位，绑定 base_tick_ms（迭代 2 起改走 speed_curve）。"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class GameStatus(Enum):
    """运行态机；迭代 1 仅 RUN/OVER，PAUSED 枚举占位但不暴露入口。"""
    RUN = "run"
    PAUSED = "paused"
    OVER = "over"


@dataclass(frozen=True)
class Snapshot:
    """不可变状态快照，供 renderer 读取。"""
    snake_body: Tuple[Point, ...]
    food: Point
    score: int
    length: int
    status: GameStatus
    difficulty: Difficulty
    tick_ms: int


@dataclass(frozen=True)
class Snake:
    """蛇身不可变 tuple；蛇头 = body[0]，蛇尾 = body[-1]。"""
    body: Tuple[Point, ...]

    @property
    def head(self) -> Point:
        return self.body[0]

    def __len__(self) -> int:
        return len(self.body)

    def with_head(self, new_head: Point) -> "Snake":
        """在头部插入新节点（移动未吃食），保留尾部。"""
        return Snake((new_head,) + self.body)

    def without_tail(self) -> "Snake":
        """去掉尾部（移动未吃食，与 with_head 配对）。"""
        return Snake(self.body[:-1])

    def with_head_no_tail_drop(self, new_head: Point) -> "Snake":
        """仅头部插入（吃食后不丢尾）。"""
        return Snake((new_head,) + self.body)

    def contains(self, p: Point) -> bool:
        return p in self.body


@dataclass(frozen=True)
class Food:
    """食物位置（不可变）。"""
    pos: Point