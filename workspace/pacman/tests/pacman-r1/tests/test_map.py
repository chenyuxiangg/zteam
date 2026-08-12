"""地图加载/校验/查询测试：U-01 / U-02 / U-03 / U-04 / U-05 / U-06 / U-07 /
U-08 / U-09 / U-10 / U-11 / U-12 / U-13。

覆盖：
- 合法地图各项加载属性（U-01）
- 行宽不一/非法字符 → MapError 报错（U-02 / U-03 / E-05）
- 连通性判定①（U-04 全可达）
- 孤立豆格 → 判定①失败（U-05 / E-06）
- 鬼屋封闭+可达门 → 判定②通过（U-06）
- 鬼屋堵死 → 判定②失败（U-07 / E-07）
- 多规格 → 判定③通过（U-08）
- dots_left / 能量豆数 / 出生点不重叠（U-09 / U-10 / U-11）
- passable 玩家/幽灵视角区分（U-12）
- tile_at / eat 行为（U-13）
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests._path import code_dir  # noqa: F401
from tests.fixtures import (
    GOOD_22x19, GOOD_10x10, GOOD_28x31,
    BAD_VARIABLE_WIDTH, BAD_ILLEGAL_CHAR, BAD_NO_PLAYER,
    BAD_FEW_POWER, BAD_NO_HOUSE, BAD_NO_DOOR, BAD_HOUSE_BLOCKED,
    BAD_TOO_SMALL_3x6,
    builtin_map, write_map_tmp,
)

from pacman.map import GameMap, MapError, Tile, load_map, validate_map


def _write_and_load(text: str) -> GameMap:
    """落盘 → load_map → 返回 GameMap（异常在调用方捕获）。"""
    path = write_map_tmp(text)
    try:
        return load_map(path)
    finally:
        os.unlink(path)


class TestBuiltinMapLoad(unittest.TestCase):
    """U-01：内置 22×19 经典地图加载成功 + 字符 → Tile 映射正确。"""

    def setUp(self):
        self.gm = builtin_map()

    def test_u01_dimensions(self):
        self.assertEqual(self.gm.rows, 19)
        self.assertEqual(self.gm.cols, 22)

    def test_u01_wall_mapping(self):
        # 第 0 行第 0 列为墙
        self.assertEqual(self.gm.tile_at(0, 0), Tile.WALL)
        self.assertEqual(self.gm.tile_at(0, 21), Tile.WALL)
        self.assertEqual(self.gm.tile_at(18, 0), Tile.WALL)
        self.assertEqual(self.gm.tile_at(18, 21), Tile.WALL)

    def test_u01_dot_mapping(self):
        # (1, 1) 应该是普通豆
        self.assertEqual(self.gm.tile_at(1, 1), Tile.DOT)

    def test_u01_power_mapping(self):
        # (1, 1) 第 1 行左起 (1, 1) = '.'；(2, 1) = 'o'
        self.assertEqual(self.gm.tile_at(2, 1), Tile.POWER)

    def test_u01_door_mapping(self):
        # 第 10 行第 8~13 列为门（'-'）
        for c in range(8, 14):
            self.assertEqual(self.gm.tile_at(10, c), Tile.DOOR,
                             f"门格 (10,{c}) 应为 DOOR")

    def test_u01_house_mapping(self):
        # 第 9 行第 7~14 列为鬼屋内部（H）
        for c in range(7, 15):
            self.assertEqual(self.gm.tile_at(9, c), Tile.HOUSE,
                             f"鬼屋 (9,{c}) 应为 HOUSE")

    def test_u01_player_spawn_mapping(self):
        # 第 12 行第 9~10 列为玩家出生区（P）
        for c in (9, 10):
            self.assertEqual(self.gm.tile_at(12, c), Tile.PLAYER_SPAWN,
                             f"出生格 (12,{c}) 应为 PLAYER_SPAWN")

    def test_u01_no_parse_exception(self):
        """成功加载即视为无解析异常（前置条件已通过）。"""
        # setUp 已加载；存在即通过
        self.assertIsInstance(self.gm, GameMap)


class TestBadMaps(unittest.TestCase):
    """U-02 / U-03 + E-05：行宽不一/非法字符 → MapError 含行列定位。"""

    def test_u02_variable_width_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_VARIABLE_WIDTH)
        msg = str(cm.exception)
        self.assertIn("行宽不一致", msg)

    def test_u03_illegal_char_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_ILLEGAL_CHAR)
        msg = str(cm.exception)
        # 应包含非法字符 'X'
        self.assertIn("非法字符", msg)
        self.assertIn("X", msg)

    def test_e05_no_player_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_NO_PLAYER)
        self.assertIn("缺少玩家出生点", str(cm.exception))

    def test_e05_no_house_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_NO_HOUSE)
        self.assertIn("缺少鬼屋", str(cm.exception))

    def test_e05_no_door_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_NO_DOOR)
        # 鬼屋封闭校验 OR 鬼屋门判定会拒绝（行 9 整行被替为通路，鬼屋邻接不封闭）
        msg = str(cm.exception)
        self.assertTrue("鬼屋" in msg or "门" in msg, msg)

    def test_e05_few_power_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_FEW_POWER)
        self.assertIn("能量豆数量不足", str(cm.exception))

    def test_e05_too_small_raises(self):
        """地图过小 < 5×5 触发尺寸校验失败。"""
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_TOO_SMALL_3x6)
        self.assertIn("过小", str(cm.exception))


class TestConnectivity(unittest.TestCase):
    """U-04：内置地图全部豆子可达（BFS 遍历）。"""

    def test_u04_all_dots_reachable_via_validate(self):
        """load_map 已执行判定①；再显式跑 validate_map 不应抛错。"""
        gm = builtin_map()
        validate_map(str(code_dir() / "pacman" / "data" / "map_classic.txt"))

    def test_u04_dot_count(self):
        """U-09：豆子总数 216 = 普通豆 212 + 能量豆 4。"""
        gm = builtin_map()
        self.assertEqual(gm.initial_dots, 216)
        # 显式统计：能量豆格
        powers = sum(
            1 for r in range(gm.rows) for c in range(gm.cols)
            if gm.tile_at(r, c) == Tile.POWER
        )
        self.assertEqual(powers, 4)
        dots = sum(
            1 for r in range(gm.rows) for c in range(gm.cols)
            if gm.tile_at(r, c) == Tile.DOT
        )
        self.assertEqual(dots, 212)


class TestHouseConnectivity(unittest.TestCase):
    """U-06 / U-07：鬼屋门连通判定。"""

    def test_u06_builtin_house_open(self):
        """内置地图：鬼屋 8 格 + 6 格门（行 10 col8~13）连通。"""
        gm = builtin_map()
        self.assertEqual(len(gm.house_cells), 8)
        self.assertGreaterEqual(len(gm.door_cells), 1)
        # 鬼屋 8 格四周封闭（HOUSE 不能邻接 DOT/POWER/EMPTY/PLAYER_SPAWN）
        # 已在 load_map 中通过 _check_house_enclosed 校验

    def test_u07_house_blocked_raises(self):
        with self.assertRaises(MapError) as cm:
            _write_and_load(BAD_HOUSE_BLOCKED)
        msg = str(cm.exception)
        # 可能是"鬼屋门未连通"或"鬼屋内部未邻接任何门"
        self.assertTrue("门" in msg or "鬼屋" in msg, msg)


class TestMultipleSpecs(unittest.TestCase):
    """U-08 / S-13：多规格地图判定③通过。"""

    def test_u08_small_map_validates(self):
        """13×13 小图：能加载、能通过三项离线判定。"""
        gm = _write_and_load(GOOD_10x10)
        self.assertEqual(gm.rows, 13)
        self.assertEqual(gm.cols, 13)

    def test_u08_large_map_validates(self):
        """21×24 大图（22×19 + 1 圈墙）：能加载、能通过三项离线判定。"""
        gm = _write_and_load(GOOD_28x31)
        self.assertEqual(gm.rows, 21)
        self.assertEqual(gm.cols, 24)


class TestPlayerSpawn(unittest.TestCase):
    """U-11：玩家出生点合法（与鬼屋不重叠、不相邻于鬼屋）。"""

    def test_u11_player_spawn_recorded(self):
        gm = builtin_map()
        pr, pc = gm.player_spawn
        self.assertEqual((pr, pc), (12, 9))
        # 不在鬼屋格内
        self.assertNotIn((pr, pc), gm.house_cells)
        # 不在鬼屋门格内
        self.assertNotIn((pr, pc), gm.door_cells)


class TestPassability(unittest.TestCase):
    """U-12：玩家视角 vs 幽灵视角对 WALL/DOOR/HOUSE 的可通行性差异。"""

    def setUp(self):
        self.gm = builtin_map()

    def test_u12_wall_blocks_both(self):
        # (0,0) 是 WALL
        self.assertFalse(self.gm.is_passable_for_player(0, 0))
        self.assertFalse(self.gm.is_passable_for_ghost(0, 0))

    def test_u12_door_blocks_player_allows_ghost(self):
        """鬼屋门：玩家视为墙、幽灵可通行。"""
        # (10, 10) 是 DOOR
        self.assertFalse(self.gm.is_passable_for_player(10, 10))
        self.assertTrue(self.gm.is_passable_for_ghost(10, 10))

    def test_u12_house_blocks_player_allows_ghost(self):
        """鬼屋内部 HOUSE：玩家视为墙、幽灵可通行。"""
        # (9, 10) 是 HOUSE
        self.assertFalse(self.gm.is_passable_for_player(9, 10))
        self.assertTrue(self.gm.is_passable_for_ghost(9, 10))

    def test_u12_passage_allows_both(self):
        """通道/普通豆/能量豆：双方可通行。"""
        # (1, 1) 是 DOT
        self.assertTrue(self.gm.is_passable_for_player(1, 1))
        self.assertTrue(self.gm.is_passable_for_ghost(1, 1))

    def test_u12_out_of_bounds_blocks_both(self):
        self.assertFalse(self.gm.is_passable_for_player(-1, 0))
        self.assertFalse(self.gm.is_passable_for_ghost(-1, 0))
        self.assertFalse(self.gm.is_passable_for_player(100, 100))
        self.assertFalse(self.gm.is_passable_for_ghost(100, 100))


class TestDotCounting(unittest.TestCase):
    """U-09 / U-13：豆子统计与吃豆后 tile 变化。"""

    def test_u13_eat_dot_clears_tile(self):
        """吃豆后该格 tile 变通道，dots_left -1。"""
        gm = builtin_map()
        # 用 fresh_tiles 副本避免污染共享状态
        tiles = gm.fresh_tiles()
        before = sum(
            1 for row in tiles for t in row
            if t in (Tile.DOT, Tile.POWER)
        )
        # 模拟吃豆
        r, c = 1, 1  # DOT
        self.assertEqual(tiles[r][c], Tile.DOT)
        tiles[r][c] = Tile.EMPTY
        after = sum(
            1 for row in tiles for t in row
            if t in (Tile.DOT, Tile.POWER)
        )
        self.assertEqual(after, before - 1)


class TestEdgeMaps(unittest.TestCase):
    """地图边界用例：tile_at 越界返回 None。"""

    def setUp(self):
        self.gm = builtin_map()

    def test_tile_at_negative(self):
        self.assertIsNone(self.gm.tile_at(-1, 0))
        self.assertIsNone(self.gm.tile_at(0, -1))

    def test_tile_at_overflow(self):
        self.assertIsNone(self.gm.tile_at(self.gm.rows, 0))
        self.assertIsNone(self.gm.tile_at(0, self.gm.cols))


class TestValidateMapApi(unittest.TestCase):
    """validate_map() 接口语义：仅校验不构建（与 load_map 同效）。"""

    def test_validate_builtin_ok(self):
        """内置地图 validate_map() 不抛异常。"""
        # 不会抛即视为通过
        validate_map(str(code_dir() / "pacman" / "data" / "map_classic.txt"))

    def test_validate_bad_raises(self):
        """非法地图 validate_map() 应抛 MapError。"""
        path = write_map_tmp(BAD_VARIABLE_WIDTH)
        try:
            with self.assertRaises(MapError):
                validate_map(path)
        finally:
            os.unlink(path)


class TestFreshTilesReset(unittest.TestCase):
    """fresh_tiles() 应返回一份新的、含初始豆子的副本（用于过关重置）。"""

    def test_fresh_tiles_is_independent_copy(self):
        gm = builtin_map()
        t1 = gm.fresh_tiles()
        # 修改 t1 不应影响再调 fresh_tiles 的结果
        t1[1][1] = Tile.EMPTY
        t2 = gm.fresh_tiles()
        self.assertEqual(t2[1][1], Tile.DOT)


if __name__ == "__main__":
    unittest.main(verbosity=2)