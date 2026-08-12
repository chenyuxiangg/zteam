"""测试 fixtures：合法/非法地图矩阵 + 实体/对局工厂 + curses 桩。

设计原则：
- 只通过被测代码的公开 API 构造对象（避免直接访问下划线前缀的内部状态）；
- 非法地图落到 tmp 文件后走 load_map 完整路径（含三项离线判定）；
- 内置地图通过 PACMAN_CODE_DIR/data/map_classic.txt 直接读取（覆盖 code 阶段
  数据文件，与方案 §4.3 设计稿一致）。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator, Tuple

from tests._path import code_dir  # noqa: F401  (注入 sys.path)


# 必须先 import（在 _path 之后），否则找不到 pacman 包
from pacman.config import Config, Dir, Kind
from pacman.entities import Ghost, Player
from pacman.game import Game
from pacman.map import GameMap, MapError, Tile, load_map


# ---------------------------------------------------------------------------
# 合法地图：22×19、4 能量豆、≥100 普通豆、含鬼屋+门+玩家出生区+全部可达
# ---------------------------------------------------------------------------
# 注：以下字符串必须与 code/pacman-r1/pacman/data/map_classic.txt 完全一致；
# 这里再硬编码一份以保证 test 阶段不依赖运行时是否打包好 data 目录（极端
# 情况下 code 产物丢失 data 文件时仍能跑逻辑层单测）。

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
# 小规格合法地图（13×13）：用于 U-08/S-13 判定③（不同规格合法判定）
# ---------------------------------------------------------------------------
# 关键设计：13 列宽 × 13 行；外圈墙；内部 11×11 全通道；鬼屋 2×2 在 (7,5)(7,6)
# (8,5)(8,6)，门 - 在 (8,7) 邻接 (8,8)='.'；行 6, 7, 9 在 cols 4-7 全墙包围；
# 能量豆 ≥4 个（行 1 散布）。
GOOD_10x10 = (
    "#############\n"
    "#P.o.o.o.o..#\n"
    "#...........#\n"
    "#...........#\n"
    "#...........#\n"
    "#...........#\n"
    "#...####....#\n"
    "#....####...#\n"
    "#....#HH-...#\n"
    "#...####....#\n"
    "#...........#\n"
    "#...........#\n"
    "#############\n"
)

# 大规格合法地图（21×24）：在 22x19 经典外加 1 圈墙（行 0, 20 全墙；行 1, 19
# 在原首尾行两侧加 #）；用于 U-08 判定③多规格适用。
GOOD_28x31 = (
    "########################\n"
    "########################\n"
    "##........#..#........##\n"
    "##o.......#..#.......o##\n"
    "##....................##\n"
    "##.##.#....##....#.##.##\n"
    "##....#....##....#....##\n"
    "####.###.######.###.####\n"
    "####................####\n"
    "####.#.##########.#.####\n"
    "####.#.#HHHHHHHH#.#.####\n"
    "####.#.##------##.#.####\n"
    "####................####\n"
    "####......PP........####\n"
    "####.###.######.###.####\n"
    "##....#....##....#....##\n"
    "##.##.#....##....#.##.##\n"
    "##....................##\n"
    "##o.......#..#.......o##\n"
    "########################\n"
    "########################\n"
)


# ---------------------------------------------------------------------------
# 7 型非法地图：覆盖 E-05/U-02/U-03/U-05/U-07/E-06/E-07
# ---------------------------------------------------------------------------

# 1. 行宽不一致（第 17 行少 1 字符）→ U-02 / E-05
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

# 2. 非法字符（X）→ U-03 / E-05
BAD_ILLEGAL_CHAR = GOOD_22x19.replace(
    "#o.......#..#.......o#\n", "#o.......#..X.......o#\n", 1
)

# 3. 缺 P（出生点缺失）→ E-05
BAD_NO_PLAYER = GOOD_22x19.replace(
    "###......PP........###\n", "###................###\n", 1
)

# 4. 能量豆 <4（替换其中 1 行 o→.，仅剩 2 个能量豆）→ E-05
BAD_FEW_POWER = (
    GOOD_22x19
    .replace("#o.......#..#.......o#\n", "#........#..#........#\n", 1)
)

# 5. 缺 H（鬼屋消失）→ E-05
BAD_NO_HOUSE = GOOD_22x19.replace("HHHHHHHH", "########", 1)

# 6. 缺门（鬼屋邻接行被替换为通道，无 -）→ E-05
BAD_NO_DOOR = GOOD_22x19.replace(
    "###.#.##------##.#.###\n", "###.#.#........#.#.###\n", 1
)

# 7. 鬼屋堵死（鬼屋门 - 全替换为 #）→ U-07 / E-07
BAD_HOUSE_BLOCKED = GOOD_22x19.replace(
    "------", "######", 1  # 鬼屋门变墙，连通判定②失败
)

# 8. 地图过小 3×6（<5×5）→ E-05
BAD_TOO_SMALL_3x6 = (
    "######\n"
    "#P...#\n"
    "######\n"
)

# 9. 孤立豆格地图：合法结构 + 单点孤豆 → 判定①失败（E-06）
BAD_ISOLATED_DOT = (
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
# 实际无孤立豆格（基础地图已连通）；下面这个 BAD_ISOLATED_DOT 用一个明显的孤豆地图
# 会被替换：直接在经典图上加一行墙将一行圈起来。
# 简单做法：把 row 6 全行替换为墙，强制孤豆
BAD_ISOLATED_DOT = GOOD_22x19.replace(
    "###.###.######.###.###\n",
    "####################\n",
    1
)


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
    """内置 22×19 经典地图（从 code 阶段产物读取，覆盖数据文件真实加载路径）。"""
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
    """默认 level=1, lives=3, speed=1.0, ghosts=4；可注入 map/clock。"""
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
    """记录 addstr / erase / refresh / getmaxyx 调用并保留绘制缓冲。

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

    def nodelay(self, flag: bool):
        """记录但不真正设置非阻塞模式（Renderer 必需）。"""
        self._nodelay = flag

    def keypad(self, flag: bool):
        """记录但不真正启用 keypad（Renderer 必需）。"""
        self._keypad = flag

    def timeout(self, ms: int):
        """记录但不真正设置轮询超时（Renderer 必需）。"""
        self._timeout = ms

    def getch(self):
        """返回 -1（无输入）以让主循环持续推进。"""
        return -1

    def addstr(self, y: int, x: int, text: str, attr: int = 0):
        """记录 addstr 调用，并按行/列写入缓冲（覆盖原字符）。"""
        self.calls.append((y, x, text, attr))
        if not (0 <= y < self._lines):
            return
        for i, ch in enumerate(text):
            cc = x + i
            if 0 <= cc < self._cols:
                self._buffer[y][cc] = ch

    # curses 配置 API（被 renderer.__init__ 调用）
    def nodelay(self, flag: bool):
        self._nodelay = flag

    def keypad(self, flag: bool):
        self._keypad = flag

    def timeout(self, ms: int):
        self._timeout = ms

    def getch(self) -> int:
        """默认返回 -1（无输入）；测试可通过赋值覆盖。"""
        return getattr(self, "_next_key", -1)

    # 测试辅助 ------------------------------------------------------------
    @property
    def captured(self) -> str:
        return "\n".join(
            "".join(ch for ch in row if ch != "\x00").rstrip()
            for row in self._buffer
        )

    def contains(self, substring: str) -> bool:
        return substring in self.captured

    def line(self, row: int) -> str:
        return "".join(ch for ch in self._buffer[row] if ch != "\x00")


# ---------------------------------------------------------------------------
# 跨平台 curses 子模块桩（最小可注入；用于 test_renderer）
# ---------------------------------------------------------------------------

class CursesStub:
    """极简 curses 桩：暴露 Renderer 需要的常量 + has_colors=False。"""

    has_colors = staticmethod(lambda: False)

    COLOR_PAIR = lambda c: c  # 颜色对值（无颜色时不被使用）

    A_DIM = 0x100000
    A_BOLD = 0x200000
    A_REVERSE = 0x400000

    OK = 0
    ERR = -1

    @staticmethod
    def init_pair(*args, **kwargs):
        pass

    @staticmethod
    def start_color():
        pass

    @staticmethod
    def use_default_colors():
        pass

    @staticmethod
    def color_pair(n):
        return n

    @staticmethod
    def curs_set(visibility):
        return CursesStub.OK

    # 颜色常量（Renderer 不读，但 curses.error 类继承需要存在）
    COLOR_BLACK = 0
    COLOR_RED = 1
    COLOR_GREEN = 2
    COLOR_YELLOW = 3
    COLOR_BLUE = 4
    COLOR_MAGENTA = 5
    COLOR_CYAN = 6
    COLOR_WHITE = 7

    class error(Exception):
        pass


__all__ = [
    "GOOD_22x19", "GOOD_10x10", "GOOD_28x31",
    "BAD_VARIABLE_WIDTH", "BAD_ILLEGAL_CHAR", "BAD_NO_PLAYER",
    "BAD_FEW_POWER", "BAD_NO_HOUSE", "BAD_NO_DOOR",
    "BAD_HOUSE_BLOCKED", "BAD_TOO_SMALL_3x6", "BAD_ISOLATED_DOT",
    "write_map_tmp", "builtin_map", "make_player", "make_ghost",
    "build_game", "frozen_clock", "ScreenStub", "CursesStub",
]