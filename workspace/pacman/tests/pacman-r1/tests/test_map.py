"""map.py 单测：覆盖 FR-02 内置地图规格 + FR-03 三项离线判定 + 6 型非法地图拦截。

测试方案映射：
- T-MAP-01~03 三项离线判定 → TestBuiltinMap / TestConnectivityAndDoor
- T-MAP-04 6 型非法地图 → TestInvalidMap
- T-MAP-05 28×31 自定义 → TestCustomMap28x31Valid
- T-MAP-06 路径不存在 → TestMissingFile
- T-FR02-01 22×19/216 豆 → TestBuiltinMap
"""
from __future__ import annotations

import os
import unittest

from tests._path import code_dir  # noqa: F401

from pacman.map import MapError, Tile, load_map

from tests.fixtures import (
    BAD_FEW_POWER, BAD_ILLEGAL_CHAR, BAD_NO_DOOR, BAD_NO_HOUSE, BAD_NO_PLAYER,
    BAD_VARIABLE_WIDTH, GOOD_22x19, builtin_map, write_map_tmp,
)


# ---------------------------------------------------------------------------
# 28×31 合规格地图（程序化构造 + 字符串常量）
# 布局参照经典 22×19：H 行 + 门行 + 走廊，4 能量豆 + 充足普通豆 + PP 出生区
# ---------------------------------------------------------------------------

LARGE_28x31 = (
    "############################\n"
    "#..........................#\n"
    "#.......###.......###......#\n"
    "#..........................#\n"
    "#.......###.......###......#\n"
    "#..........................#\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##HHHHHHHH####.######\n"
    "######.##--------####.######\n"
    "######.##........####.######\n"
    "######.######.#.#####.######\n"
    "#............PP............#\n"
    "#.......###.......###......#\n"
    "#..........................#\n"
    "#.......###.......###......#\n"
    "#o........................o#\n"
    "#o........................o#\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "######.##############.######\n"
    "############################\n"
)


class TestBuiltinMap(unittest.TestCase):
    """T-FR02-01 / T-FR02-02：内置 22×19 经典地图。"""

    def setUp(self):
        self.gm = builtin_map()

    def test_dimensions(self):
        self.assertEqual(self.gm.rows, 19)
        self.assertEqual(self.gm.cols, 22)

    def test_dot_count_216(self):
        self.assertEqual(self.gm.initial_dots, 216)

    def test_player_spawn_inside_arena(self):
        r, c = self.gm.player_spawn
        self.assertEqual((r, c), (12, 9))
        self.assertEqual(self.gm.tile_at(r, c), Tile.PLAYER_SPAWN)

    def test_ghost_house_enclosed_with_door(self):
        self.assertGreaterEqual(len(self.gm.house_cells), 1)
        self.assertGreaterEqual(len(self.gm.door_cells), 1)

    def test_spawn_not_adjacent_to_house(self):
        """T-FR02-02：玩家出生区与鬼屋不相邻。"""
        sr, sc = self.gm.player_spawn
        for hr, hc in self.gm.house_cells:
            d = abs(sr - hr) + abs(sc - hc)
            self.assertGreaterEqual(d, 2, f"spawn {(sr,sc)} too close to house {(hr, hc)}")


class TestConnectivityAndDoor(unittest.TestCase):
    """T-MAP-01/02/03：三项离线判定对内置地图均通过。"""

    def test_load_succeeds(self):
        gm = load_map(str(code_dir() / "pacman" / "data" / "map_classic.txt"))
        self.assertGreater(gm.initial_dots, 100)

    def test_load_succeeds_for_good_text(self):
        p = write_map_tmp(GOOD_22x19)
        try:
            gm = load_map(p)
            self.assertEqual(gm.initial_dots, 216)
        finally:
            os.unlink(p)

    def test_is_passable_player_excludes_house(self):
        gm = builtin_map()
        hr, hc = next(iter(gm.house_cells))
        self.assertFalse(gm.is_passable_for_player(hr, hc))
        self.assertFalse(gm.is_passable_for_player(0, 0))


class TestInvalidMap(unittest.TestCase):
    """T-MAP-04：6 型非法地图逐一被 load_map 拦截（MapError 异常）。"""

    def _assert_rejected(self, text: str, hint_substr: str = ""):
        p = write_map_tmp(text)
        try:
            with self.assertRaises(MapError) as ctx:
                load_map(p)
            if hint_substr:
                self.assertIn(hint_substr, str(ctx.exception))
        finally:
            os.unlink(p)

    def test_variable_row_width(self):
        self._assert_rejected(BAD_VARIABLE_WIDTH, "行宽")

    def test_illegal_char(self):
        self._assert_rejected(BAD_ILLEGAL_CHAR, "非法字符")

    def test_no_player_spawn(self):
        self._assert_rejected(BAD_NO_PLAYER, "P")

    def test_too_few_power_pellets(self):
        self._assert_rejected(BAD_FEW_POWER, "能量豆")

    def test_no_ghost_house(self):
        self._assert_rejected(BAD_NO_HOUSE, "H")

    def test_no_door(self):
        self._assert_rejected(BAD_NO_DOOR, "门")


class TestMissingFile(unittest.TestCase):
    """T-MAP-06：--map 指向不存在文件。"""

    def test_nonexistent_path_raises(self):
        with self.assertRaises(MapError) as ctx:
            load_map("/tmp/pacman_definitely_does_not_exist_xyz_12345.txt")
        self.assertIn("不存在", str(ctx.exception))


class TestCustomMap28x31Valid(unittest.TestCase):
    """T-MAP-05：28×31 合规格自定义地图加载通过三项离线判定。"""

    def test_load_succeeds(self):
        p = write_map_tmp(LARGE_28x31)
        try:
            gm = load_map(p)
            self.assertEqual(gm.rows, 31)
            self.assertEqual(gm.cols, 28)
            self.assertGreaterEqual(gm.initial_dots, 100)
            self.assertGreaterEqual(len(gm.house_cells), 1)
            self.assertGreaterEqual(len(gm.door_cells), 1)
            # 出生点 PP 存在
            self.assertEqual(gm.tile_at(gm.player_spawn[0], gm.player_spawn[1]), Tile.PLAYER_SPAWN)
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
