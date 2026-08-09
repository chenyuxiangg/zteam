"""map.py 单测。

覆盖测试方案：
- TC-A3 玩家/幽灵通道连通性
- TC-A5 非法地图矩阵（行宽 / 非法字符 / 缺 P / 能量豆不足 / 缺 H / 缺门 / 鬼屋未封闭）
- TC-X6 路径不存在
- TC-X7 非法字符定位
- TC-A4 合法自定义地图加载（用 GOOD_SMALL）
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests._path import code_dir

from pacman.map import GameMap, MapError, Pos, Tile

from tests.fixtures import (
    BAD_FEW_DOTS,
    BAD_FEW_POWER,
    BAD_HOUSE_OPEN,
    BAD_ILLEGAL_CHAR,
    BAD_NO_DOOR,
    BAD_NO_HOUSE,
    BAD_NO_PLAYER,
    BAD_VARIABLE_WIDTH,
    GOOD_22x19,
)


class TestBuiltinMap(unittest.TestCase):
    """内置 22×19 经典地图与 TC-A2 验收口径。"""

    @classmethod
    def setUpClass(cls):
        cls.m = GameMap.load(code_dir() / "pacman" / "data" / "map_classic.txt")

    def test_size(self):
        self.assertEqual(self.m.height, 19)
        self.assertEqual(self.m.width, 22)

    def test_initial_dots_total(self):
        # TC-A2：豆子总数 216（普通 212 + 能量 4）
        self.assertEqual(self.m.initial_dots, 216)

    def test_dot_count_split(self):
        dots = sum(1 for r in self.m._template for t in r if t is Tile.DOT)
        powers = sum(1 for r in self.m._template for t in r if t is Tile.POWER)
        self.assertEqual(dots, 212)
        self.assertEqual(powers, 4)

    def test_player_start(self):
        # TC-A2：玩家出生点 row12 col9~10（mid → col10）
        self.assertEqual(self.m.player_start, Pos(12, 10))

    def test_house_enclosure(self):
        # TC-A2：鬼屋 (row9 col7~14)
        self.assertEqual(self.m.house_cells, tuple(Pos(9, c) for c in range(7, 15)))
        # 门 (row10 col8~13)
        self.assertEqual(self.m.door_cells, tuple(Pos(10, c) for c in range(8, 14)))

    def test_ghost_home_midpoint(self):
        # ghost_home 取鬼屋排序后的中位 cell
        self.assertEqual(self.m.ghost_home, Pos(9, 11))

    def test_initial_dots_meets_minimum(self):
        # FR-02/TC-A2：豆子 ≥100
        self.assertGreaterEqual(self.m.initial_dots, 100)


class TestMapConnectivity(unittest.TestCase):
    """TC-A3：玩家/幽灵通道 BFS 连通性。"""

    @classmethod
    def setUpClass(cls):
        cls.m = GameMap.load(code_dir() / "pacman" / "data" / "map_classic.txt")
        # 计算可达集
        cls.player_reachable = cls.m._reachable(cls.m.player_start, False)
        cls.ghost_reachable = cls.m._reachable(cls.m.house_cells[0], True)

    def test_player_reach_all_passable(self):
        required = {
            Pos(r, c)
            for r, row in enumerate(self.m._template)
            for c, t in enumerate(row)
            if t in (Tile.EMPTY, Tile.DOT, Tile.POWER)
        }
        self.assertEqual(required - self.player_reachable, set())

    def test_ghost_reach_all_non_wall(self):
        required = {
            Pos(r, c)
            for r, row in enumerate(self.m._template)
            for c, t in enumerate(row)
            if t is not Tile.WALL
        }
        self.assertEqual(required - self.ghost_reachable, set())

    def test_door_only_for_ghost(self):
        # 玩家不可穿过门，鬼可以
        self.assertFalse(self.m.passable(Pos(10, 10), for_ghost=False))
        self.assertTrue(self.m.passable(Pos(10, 10), for_ghost=True))


class TestLoadValidCustomMap(unittest.TestCase):
    """TC-A4：合法自定义地图加载（绕过 terminal 尺寸约束）。"""

    def test_classic_22x19_loads(self):
        # TC-A4：用 GOOD_22x19 验证合法自定义地图加载
        m = GameMap.from_text(GOOD_22x19, source="<test>")
        self.assertEqual(m.height, 19)
        self.assertEqual(m.width, 22)
        # 至少 100 颗豆
        self.assertGreaterEqual(m.initial_dots, 100)


class TestInvalidMapVariants(unittest.TestCase):
    """TC-A5 / TC-X7：非法地图矩阵 → MapError（含定位信息）。"""

    def _assert_with_context(self, text: str, substring: str, source: str = "<test>"):
        with self.assertRaises(MapError) as ctx:
            GameMap.from_text(text, source=source)
        self.assertIn(substring, str(ctx.exception))

    def test_variable_width(self):
        self._assert_with_context(BAD_VARIABLE_WIDTH, "第 17 行宽度")

    def test_illegal_char_with_position(self):
        self._assert_with_context(BAD_ILLEGAL_CHAR, "非法字符")

    def test_no_player(self):
        self._assert_with_context(BAD_NO_PLAYER, "缺少玩家出生标记 P")

    def test_too_few_power(self):
        self._assert_with_context(BAD_FEW_POWER, "能量豆至少需要 4 个")

    def test_no_house(self):
        self._assert_with_context(BAD_NO_HOUSE, "缺少鬼屋 H")

    def test_no_door(self):
        self._assert_with_context(BAD_NO_DOOR, "缺少鬼屋门 -")

    def test_house_open(self):
        self._assert_with_context(BAD_HOUSE_OPEN, "鬼屋")

    def test_too_few_dots(self):
        self._assert_with_context(BAD_FEW_DOTS, "豆子总数至少需要 100")


class TestMissingFile(unittest.TestCase):
    """TC-X6：路径不存在 → MapError 含 '不存在'。"""

    def test_missing_path(self):
        with self.assertRaises(MapError) as ctx:
            GameMap.load(Path("/nonexistent/path/to.map"))
        self.assertIn("不存在", str(ctx.exception))


class TestTileQueries(unittest.TestCase):
    """通用查询语义：in_bounds / clamp / tile_at / consume / dots_left。"""

    def setUp(self):
        self.m = GameMap.load(code_dir() / "pacman" / "data" / "map_classic.txt")

    def test_in_bounds(self):
        self.assertTrue(self.m.in_bounds(Pos(0, 0)))
        self.assertTrue(self.m.in_bounds(Pos(18, 21)))
        self.assertFalse(self.m.in_bounds(Pos(-1, 0)))
        self.assertFalse(self.m.in_bounds(Pos(19, 0)))
        self.assertFalse(self.m.in_bounds(Pos(0, 22)))

    def test_clamp(self):
        self.assertEqual(self.m.clamp(Pos(-5, 100)), Pos(0, 21))
        self.assertEqual(self.m.clamp(Pos(50, -5)), Pos(18, 0))

    def test_tile_out_of_bounds_is_wall(self):
        self.assertIs(self.m.tile_at(Pos(-1, 0)), Tile.WALL)
        self.assertIs(self.m.tile_at(Pos(100, 100)), Tile.WALL)

    def test_consume_dot_decrements(self):
        before = self.m.dots_left()
        # 找一颗普通豆子
        for r in range(self.m.height):
            for c in range(self.m.width):
                if self.m.tile_at(Pos(r, c)) is Tile.DOT:
                    self.m.consume(Pos(r, c))
                    self.assertEqual(self.m.dots_left(), before - 1)
                    self.assertIs(self.m.tile_at(Pos(r, c)), Tile.EMPTY)
                    return
        self.fail("no dot found")

    def test_consume_empty_returns_empty(self):
        empty = Pos(1, 1)  # 必然是墙
        # 用一个 EMPTY 位置：地图第 1 行 (index 0) 是墙，找一个可达的空地
        for r in range(self.m.height):
            for c in range(self.m.width):
                if self.m.tile_at(Pos(r, c)) is Tile.EMPTY:
                    self.assertIs(self.m.consume(Pos(r, c)), Tile.EMPTY)
                    return
        self.fail("no empty cell")

    def test_passable_wall(self):
        # 玩家视角：墙不可穿
        self.assertFalse(self.m.passable(Pos(0, 0), for_ghost=False))
        self.assertFalse(self.m.passable(Pos(0, 0), for_ghost=True))


if __name__ == "__main__":
    unittest.main()
