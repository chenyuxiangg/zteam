"""键盘输入归一化。

职责：把 WASD、方向键、暂停和退出键映射为领域动作；对应开发方案 §3.2、§5.2。
依赖：pacman.entities.Dir；方向键常量由 main 注入，避免逻辑模块依赖 curses。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from .entities import Dir


class Command(Enum):
    DIRECTION = "direction"
    PAUSE = "pause"
    QUIT = "quit"


@dataclass(frozen=True)
class InputAction:
    command: Command
    direction: Optional[Dir] = None


_CHAR_DIRECTIONS: Dict[int, Dir] = {
    ord("w"): Dir.UP,
    ord("W"): Dir.UP,
    ord("a"): Dir.LEFT,
    ord("A"): Dir.LEFT,
    ord("s"): Dir.DOWN,
    ord("S"): Dir.DOWN,
    ord("d"): Dir.RIGHT,
    ord("D"): Dir.RIGHT,
}


def map_key(
    key: int,
    *,
    key_up: int,
    key_left: int,
    key_down: int,
    key_right: int,
) -> Optional[InputAction]:
    direction = _CHAR_DIRECTIONS.get(key)
    if direction is None:
        direction = {
            key_up: Dir.UP,
            key_left: Dir.LEFT,
            key_down: Dir.DOWN,
            key_right: Dir.RIGHT,
        }.get(key)
    if direction is not None:
        return InputAction(Command.DIRECTION, direction)
    if key in (ord("p"), ord("P")):
        return InputAction(Command.PAUSE)
    if key in (ord("q"), ord("Q")):
        return InputAction(Command.QUIT)
    return None
