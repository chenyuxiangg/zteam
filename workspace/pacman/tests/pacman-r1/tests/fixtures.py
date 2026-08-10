"""测试 fixtures：合法/非法地图矩阵 + 实体/对局工厂。

设计原则：
- 只通过被测代码的**公开 API** 构造对象；
- 非法地图直接走 `pacman.map._parse_grid` + `load_map` 验证（用 tmp 文件落地后被 load_map 读取以覆盖真实加载路径）。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Iterator, Tuple

from tests._path import code_dir  # noqa: F401  (注入 sys.path)

from pacman.config import Config, Dir, Kind
from pacman.entities import Ghost, Player
from pacman.game import Game
from pacman.map import GameMap, MapError, Tile, load_map


# ---------------------------------------------------------------------------
# 合法地图：22×19、4 能量豆、≥100 普通豆、含鬼屋+门+玩家出生区+全部可达
# ---------------------------------------------------------------------------

GOOD_22x19 = (
    "######################\n"
    "#........#..#........#\n"
    "#o.......#..#.......o#\n"
    "#....................#\n"
    "#.##.#....##....#.##.#\n"
    "#....#....##....#....#\n"
    "###.###.######.###.###\n"
    "###................###\n"
    "###.#.##########.#.###\n"
    "###.#.#HHHHHHHH#.#.###\n"
    "###.#.##------##.#.###\n"
    "###................###\n"
    "###......PP........###\n"
    "###.###.######.###.###\n"
    "#....#....##....#....#\n"
    "#.##.#....##....#.##.#\n"
    "#....................#\n"
    "#o.......#..#.......o#\n"
    "######################\n"
)

# ---------------------------------------------------------------------------
# 6 型非法地图：行宽不一致 / 非法字符 / 缺 P / 能量豆 <4 / 缺 H / 缺门
# ---------------------------------------------------------------------------

# 1. 行宽不一致（第 17 行少 1 字符）
BAD_VARIABLE_WIDTH = (
    "######################\n"
    "#........#..#........#\n"
    "#o.......#..#.......o#\n"
    "#....................#\n"
    "#.##.#....##....#.##.#\n"
    "#....#....##....#....#\n"
    "###.###.######.###.###\n"
    "###................###\n"
    "###.#.##########.#.###\n"
    "###.#.#HHHHHHHH#.#.###\n"
    "###.#.##------##.#.###\n"
    "###................###\n"
    "###......PP........###\n"
    "###.###.######.###.###\n"
    "#....#....##....#....#\n"
    "#.##.#....##....#.##.#\n"
    "#...................\n"          # ← 短 1
    "#o.......#..#.......o#\n"
    "######################\n"
)

# 2. 非法字符（X）
BAD_ILLEGAL_CHAR = GOOD_22x19.replace("#o.......#..#.......o#\n", "#o.......#..X.......o#\n", 1)

# 3. 缺 P（出生点缺失）
BAD_NO_PLAYER = GOOD_22x19.replace("###......PP........###\n", "###................###\n", 1)

# 4. 能量豆 <4（把第三行 o 改 .）
BAD_FEW_POWER = (
    GOOD_22x19
    .replace("#o.......#..#.......o#\n", "#........#..#........#\n", 1)
    .replace("#o.......#..#.......o#\n", "#........#..#........#\n", 1)  # 仅 0 个能量豆
)

# 5. 缺 H（鬼屋消失，H 行改为等宽墙以触发"缺 H"而非"行宽不一致"）
BAD_NO_HOUSE = GOOD_22x19.replace("HHHHHHHH", "########", 1)

# 6. 缺门（鬼屋邻接行被替换为通道，无 -）
BAD_NO_DOOR = GOOD_22x19.replace("###.#.##------##.#.###\n", "###.#.#........#.#.###\n", 1)


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def write_map_tmp(text: str) -> str:
    """把地图文本写到 tmp，返回路径（调用方负责删除）。"""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="pacman_test_map_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def builtin_map() -> GameMap:
    """内置 22×19 经典地图。"""
    return load_map(str(code_dir() / "pacman" / "data" / "map_classic.txt"))


def make_player(pos: Tuple[int, int] = (12, 9), direction: Dir = Dir.LEFT) -> Player:
    p = Player(pos)
    p.dir = direction
    return p


def make_ghost(kind: Kind = Kind.BLINKY, pos: Tuple[int, int] = (9, 10),
               direction: Dir = Dir.UP, level: int = 1) -> Ghost:
    g = Ghost(kind, pos, level=level)
    g.dir = direction
    return g


def build_game(
    config: Config | None = None,
    game_map: GameMap | None = None,
    clock=None,
) -> Game:
    """默认 level=1, lives=3, speed=1.0；可注入 map/clock。"""
    if config is None:
        config = Config()
    if game_map is None:
        game_map = builtin_map()
    return Game(game_map, config, clock=clock)


def frozen_clock(start: float = 1000.0):
    """返回 (clock_fn, advance_fn)：clock_fn() 返回当前假时间；advance(dt) 推时间。"""
    state = {"t": start}

    def clock_fn() -> float:
        return state["t"]

    def advance(dt: float) -> None:
        state["t"] += dt

    return clock_fn, advance


# ---------------------------------------------------------------------------
# curses screen 桩（renderer 单测用）
# ---------------------------------------------------------------------------

class ScreenStub:
    """记录 addnstr / erase / refresh / getmaxyx 调用并保留绘制缓冲。

    不真正渲染，测试通过 ``captured`` 拿整屏字符串做断言。
    """

    def __init__(self, lines: int = 24, cols: int = 80):
        self._lines = lines
        self._cols = cols
        self._buffer: list[list[str]] = [["\x00"] * cols for _ in range(lines)]
        self.erase_count = 0
        self.refresh_count = 0
        self.calls: list[Tuple[int, int, str, int]] = []

    # curses API ----------------------------------------------------------
    def erase(self):
        self.erase_count += 1
        self._buffer = [["\x00"] * self._cols for _ in range(self._lines)]

    def refresh(self):
        self.refresh_count += 1

    def getmaxyx(self) -> Tuple[int, int]:
        return self._lines, self._cols

    def addnstr(self, row: int, col: int, text: str, n: int, attr: int = 0):
        self.calls.append((row, col, text, attr))
        if not (0 <= row < self._lines):
            return
        # 用 overlay 方式写入
        for i in range(min(n, len(text))):
            cc = col + i
            if 0 <= cc < self._cols:
                self._buffer[row][cc] = text[i]

    # 测试辅助 ------------------------------------------------------------
    @property
    def captured(self) -> str:
        return "\n".join("".join(ch for ch in row if ch != "\x00").rstrip() for row in self._buffer)

    def contains(self, substring: str) -> bool:
        return substring in self.captured

    def line(self, row: int) -> str:
        return "".join(ch for ch in self._buffer[row] if ch != "\x00")


__all__ = [
    "GOOD_22x19",
    "BAD_VARIABLE_WIDTH", "BAD_ILLEGAL_CHAR", "BAD_NO_PLAYER",
    "BAD_FEW_POWER", "BAD_NO_HOUSE", "BAD_NO_DOOR",
    "write_map_tmp", "builtin_map", "make_player", "make_ghost",
    "build_game", "frozen_clock", "ScreenStub",
]
