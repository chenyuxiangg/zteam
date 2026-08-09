"""玩家和幽灵实体模型。

职责：定义位置、方向、移动累积器、玩家输入缓冲和幽灵状态；对应开发方案 §3.2、§4.2、§5.2。
依赖：pacman.map.Pos 与 Python 标准库 dataclasses/enum。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .map import Pos


class Dir(Enum):
    UP = (-1, 0)
    LEFT = (0, -1)
    DOWN = (1, 0)
    RIGHT = (0, 1)

    @property
    def delta(self) -> Tuple[int, int]:
        return self.value

    @property
    def reverse(self) -> "Dir":
        return {
            Dir.UP: Dir.DOWN,
            Dir.DOWN: Dir.UP,
            Dir.LEFT: Dir.RIGHT,
            Dir.RIGHT: Dir.LEFT,
        }[self]


class GhostKind(Enum):
    BLINKY = "Blinky"
    PINKY = "Pinky"
    INKY = "Inky"
    CLYDE = "Clyde"


class GhostMode(Enum):
    SCATTER = "SCATTER"
    CHASE = "CHASE"
    FRIGHTENED = "FRIGHTENED"
    EYES = "EYES"


@dataclass
class Mover:
    pos: Pos
    spawn: Pos
    direction: Dir
    accumulator: float = 0.0

    def reset_position(self, direction: Dir) -> None:
        self.pos = self.spawn
        self.direction = direction
        self.accumulator = 0.0

    def add_motion(self, cells_per_tick: float, dt: float, tick_seconds: float = 0.1) -> int:
        """加入时间片并返回本次应移动的格数。"""
        self.accumulator += max(0.0, cells_per_tick) * max(0.0, dt) / tick_seconds
        steps = int(self.accumulator)
        if steps:
            self.accumulator -= steps
        return min(steps, 4)  # 防止调试器停顿后单帧跨越过多格


@dataclass
class Player(Mover):
    buffered_direction: Optional[Dir] = None

    def queue_direction(self, direction: Dir) -> None:
        self.buffered_direction = direction

    def reset_position(self, direction: Dir = Dir.LEFT) -> None:
        super().reset_position(direction)
        self.buffered_direction = None


@dataclass
class Ghost(Mover):
    kind: GhostKind = GhostKind.BLINKY
    mode: GhostMode = GhostMode.SCATTER
    home_corner: Pos = Pos(0, 0)
    released: bool = False
    release_dots: int = 0
    force_reverse: bool = False

    def reset_for_round(self, released: bool, release_dots: int) -> None:
        self.reset_position(Dir.UP)
        self.mode = GhostMode.SCATTER
        self.released = released
        self.release_dots = release_dots
        self.force_reverse = False
