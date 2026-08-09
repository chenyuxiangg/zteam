"""键位映射与输入缓冲。

职责：将 curses keycode 转换为 Dir / 动作；忽略非法键。
依赖：仅 pacman.config。
对应方案：plans/pacman-r1.md §3.2 input.py、§5.3 非法键忽略（FR-04/FR-16/NFR-04）。
"""

from typing import Optional

from .config import Dir


# ============================================================================
# 键位常量（curses keycode 字符串；具体值在 main.py / renderer.py 读取后传入）
# ============================================================================
# 方向键
KEY_UP    = "KEY_UP"
KEY_DOWN  = "KEY_DOWN"
KEY_LEFT  = "KEY_LEFT"
KEY_RIGHT = "KEY_RIGHT"

# WASD（兼容）
KEY_W = "w"
KEY_A = "a"
KEY_S = "s"
KEY_D = "d"

# 暂停/退出
KEY_PAUSE = "p"
KEY_QUIT  = "q"

# 主循环动作枚举
from enum import Enum

class Action(Enum):
    """解析后的输入动作。"""
    TURN_UP = "up"
    TURN_DOWN = "down"
    TURN_LEFT = "left"
    TURN_RIGHT = "right"
    PAUSE = "pause"
    QUIT = "quit"
    NONE = "none"  # 非法键/未映射


# ============================================================================
# 映射表
# ============================================================================
_KEY_TO_DIR = {
    KEY_UP: Dir.UP,
    KEY_DOWN: Dir.DOWN,
    KEY_LEFT: Dir.LEFT,
    KEY_RIGHT: Dir.RIGHT,
    KEY_W: Dir.UP,
    KEY_A: Dir.LEFT,
    KEY_S: Dir.DOWN,
    KEY_D: Dir.RIGHT,
}


def parse_key(key_str: str) -> Action:
    """将按键字符串（curses.getch 返回 int → 由调用方映射为字符串）解析为 Action。

    非法键返回 Action.NONE（被忽略，游戏不中断）。
    退出：Action.QUIT（q 键）；Ctrl+C 由 wrapper 兜底捕获。
    暂停：Action.PAUSE（P 键）。
    """
    if key_str == KEY_QUIT:
        return Action.QUIT
    if key_str == KEY_PAUSE:
        return Action.PAUSE
    if key_str in _KEY_TO_DIR:
        d = _KEY_TO_DIR[key_str]
        return {
            Dir.UP: Action.TURN_UP,
            Dir.DOWN: Action.TURN_DOWN,
            Dir.LEFT: Action.TURN_LEFT,
            Dir.RIGHT: Action.TURN_RIGHT,
        }[d]
    return Action.NONE


def keycode_to_str(keycode: int) -> str:
    """curses.getch() 返回的 int 转字符串 keyname（用于 parse_key）。

    方向键的 keycode 来自 curses：260/258/261/259（左/上/右/下）。
    """
    if keycode == 259:  # KEY_UP
        return KEY_UP
    if keycode == 258:  # KEY_DOWN
        return KEY_DOWN
    if keycode == 260:  # KEY_LEFT
        return KEY_LEFT
    if keycode == 261:  # KEY_RIGHT
        return KEY_RIGHT
    if 0 <= keycode <= 0x10FFFF:
        try:
            return chr(keycode)
        except ValueError:
            return ""
    return ""
