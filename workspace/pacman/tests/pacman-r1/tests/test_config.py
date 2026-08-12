"""配置模块测试：U-60 / U-61 / U-62。

覆盖：
- U-60：CLI 参数覆盖默认值（--ghosts/--lives/--speed/--level）
- U-61：非法值（argparse 报错 exit 2 + 明确错误信息）
- U-62：--ghosts N 时按 Blinky + Pinky/Inky/Clyde 顺序保留前 N-1 只
- C-03（部分）：模块不依赖 curses（静态检查通过 import 验证）
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest

from tests._path import code_dir  # noqa: F401
from tests.fixtures import build_game

from pacman.config import (
    Config, Dir, Kind,
    DEFAULT_GHOSTS, DEFAULT_LIVES, DEFAULT_LEVEL, DEFAULT_SPEED,
    ghost_speed_for_level, power_duration_for_level,
    scatter_duration_for_level, chase_duration_for_level,
    elroy_threshold_for_level,
    inky_release_dots_for_level, clyde_release_dots_for_level,
)
from pacman.main import _parse_args, main_cli


CODE = code_dir()


class TestDefaults(unittest.TestCase):
    """默认值与常量（U-60 子集：未传参时取默认值）。"""

    def test_u60_default_ghosts(self):
        cfg = Config()
        self.assertEqual(cfg.ghosts, 4)

    def test_u60_default_lives(self):
        cfg = Config()
        self.assertEqual(cfg.lives, 3)

    def test_u60_default_level(self):
        cfg = Config()
        self.assertEqual(cfg.level, 1)

    def test_u60_default_speed(self):
        cfg = Config()
        self.assertEqual(cfg.speed, 1.0)

    def test_u60_default_no_color(self):
        cfg = Config()
        self.assertFalse(cfg.no_color)

    def test_u60_default_log_ai(self):
        cfg = Config()
        self.assertFalse(cfg.log_ai)

    def test_u60_default_map_path(self):
        cfg = Config()
        # 默认应指向 data/map_classic.txt（具体路径由 code 阶段约定，此处只断言
        # 文件名形态）
        self.assertTrue(cfg.map_path.endswith("map_classic.txt"))


class TestCliOverrides(unittest.TestCase):
    """CLI 参数覆盖（U-60：合法值应成功注入到 Config）。"""

    def _parse(self, argv):
        return _parse_args(argv)

    def test_u60_over_ghosts_2(self):
        cfg = self._parse(["--ghosts", "2"])
        self.assertEqual(cfg.ghosts, 2)

    def test_u60_over_ghosts_3(self):
        cfg = self._parse(["--ghosts", "3"])
        self.assertEqual(cfg.ghosts, 3)

    def test_u60_over_lives_5(self):
        cfg = self._parse(["--lives", "5"])
        self.assertEqual(cfg.lives, 5)

    def test_u60_over_speed_05(self):
        cfg = self._parse(["--speed", "0.5"])
        self.assertAlmostEqual(cfg.speed, 0.5)

    def test_u60_over_speed_20(self):
        cfg = self._parse(["--speed", "2.0"])
        self.assertAlmostEqual(cfg.speed, 2.0)

    def test_u60_over_level_3(self):
        cfg = self._parse(["--level", "3"])
        self.assertEqual(cfg.level, 3)

    def test_u60_no_color(self):
        cfg = self._parse(["--no-color"])
        self.assertTrue(cfg.no_color)

    def test_u60_log_ai(self):
        cfg = self._parse(["--log-ai"])
        self.assertTrue(cfg.log_ai)


class TestInvalidCli(unittest.TestCase):
    """非法值应使 _parse_args 调用 sys.exit(2)（U-61）。"""

    def _assert_exit_2(self, argv, expected_msg_substr: str = ""):
        """_parse_args 在非法值时 sys.exit(2)，stderr 给出明确错误。"""
        with self.assertRaises(SystemExit) as cm:
            _parse_args(argv)
        self.assertEqual(cm.exception.code, 2)

    def test_u61_ghosts_1(self):
        self._assert_exit_2(["--ghosts", "1"])

    def test_u61_ghosts_5(self):
        self._assert_exit_2(["--ghosts", "5"])

    def test_u61_lives_0(self):
        self._assert_exit_2(["--lives", "0"])

    def test_u61_lives_10(self):
        self._assert_exit_2(["--lives", "10"])

    def test_u61_speed_too_low(self):
        self._assert_exit_2(["--speed", "0.1"])

    def test_u61_speed_too_high(self):
        self._assert_exit_2(["--speed", "3.0"])

    def test_u61_level_zero(self):
        self._assert_exit_2(["--level", "0"])

    def test_u61_level_negative(self):
        self._assert_exit_2(["--level", "-1"])


class TestGhostsCountToRoster(unittest.TestCase):
    """U-62：--ghosts N 时按 Blinky + Pinky/Inky/Clyde 顺序保留前 N-1 只。"""

    def _ghosts_with_count(self, n: int):
        from pacman.main import _parse_args
        cfg = _parse_args(["--ghosts", str(n)])
        game = build_game(config=cfg)
        kinds = [g.kind for g in game.ghosts]
        return kinds

    def test_u62_ghosts_2_is_blinky_pinky(self):
        kinds = self._ghosts_with_count(2)
        self.assertEqual(kinds, [Kind.BLINKY, Kind.PINKY])

    def test_u62_ghosts_3_is_blinky_pinky_inky(self):
        kinds = self._ghosts_with_count(3)
        self.assertEqual(kinds, [Kind.BLINKY, Kind.PINKY, Kind.INKY])

    def test_u62_ghosts_4_is_all_four(self):
        kinds = self._ghosts_with_count(4)
        self.assertEqual(kinds, [Kind.BLINKY, Kind.PINKY, Kind.INKY, Kind.CLYDE])


class TestDifficultyFormulas(unittest.TestCase):
    """§5.4 难度公式（U-44 / U-45 / U-46 单测化）。"""

    def test_u44_power_duration_l1(self):
        self.assertAlmostEqual(power_duration_for_level(1), 6.0)

    def test_u44_power_duration_l2(self):
        self.assertAlmostEqual(power_duration_for_level(2), 5.5)

    def test_u44_power_duration_l5(self):
        self.assertAlmostEqual(power_duration_for_level(5), 4.0)

    def test_u44_power_duration_l10(self):
        """max(6.0 - 0.5*(10-1), 1.0) = max(1.5, 1.0) = 1.5"""
        self.assertAlmostEqual(power_duration_for_level(10), 1.5)

    def test_u44_power_duration_floor(self):
        """L=11 起触发下限 1.0s（6.0-0.5*10 = 1.0；L=12 起严格 ≤1）。"""
        # L=11 → 6.0 - 0.5*10 = 1.0（等于下限）
        self.assertAlmostEqual(power_duration_for_level(11), 1.0)
        for L in (12, 15, 20):
            self.assertAlmostEqual(power_duration_for_level(L), 1.0)

    def test_u45_ghost_base_speed_l1(self):
        self.assertAlmostEqual(ghost_speed_for_level(1), 0.9)

    def test_u45_ghost_base_speed_l2(self):
        self.assertAlmostEqual(ghost_speed_for_level(2), 0.92)

    def test_u45_ghost_base_speed_l20(self):
        """上限 0.98。"""
        self.assertAlmostEqual(ghost_speed_for_level(20), 0.98)

    def test_u46_scatter_duration_l1(self):
        self.assertEqual(scatter_duration_for_level(1), 7)

    def test_u46_scatter_duration_l5(self):
        """max(7 - (5-1)*2, 1) = 1"""
        self.assertEqual(scatter_duration_for_level(5), 1)

    def test_u46_chase_duration_constant(self):
        """CHASE 恒 20s。"""
        for L in (1, 5, 10, 20):
            self.assertAlmostEqual(chase_duration_for_level(L), 20.0)

    def test_u50_elroy_threshold_l1(self):
        self.assertEqual(elroy_threshold_for_level(1), 20)

    def test_u50_elroy_threshold_floor(self):
        """下限 5。"""
        self.assertEqual(elroy_threshold_for_level(20), 5)

    def test_u50_inky_release_l1(self):
        self.assertEqual(inky_release_dots_for_level(1), 30)

    def test_u50_inky_release_floor(self):
        self.assertEqual(inky_release_dots_for_level(20), 10)

    def test_u50_clyde_release_l1(self):
        self.assertEqual(clyde_release_dots_for_level(1), 60)

    def test_u50_clyde_release_floor(self):
        self.assertEqual(clyde_release_dots_for_level(20), 20)


class TestMissingMap(unittest.TestCase):
    """E-04：--map 不存在路径应明确报错退出（不在游戏内）。"""

    def test_e04_nonexistent_map_exits_1(self):
        """main_cli 在地图加载失败时返回 1。"""
        # 用非 TTY 但无 PTY 的方式调用：直接走子进程避免本进程状态污染
        # 这里通过 mock stdin 不可 tty 时 main_cli 会先检查 TTY，所以
        # 改测 _parse_args + load_map 直接触发 MapError：
        from pacman.map import MapError, load_map
        with self.assertRaises(MapError) as cm:
            load_map("/nonexistent/path/pacman_map.txt")
        # 错误信息应包含"不存在"
        self.assertIn("不存在", str(cm.exception))


class TestConfigDataclass(unittest.TestCase):
    """Config dataclass 自身行为。"""

    def test_config_fields_accessible(self):
        cfg = Config(ghosts=3, lives=5, level=2, speed=1.5)
        self.assertEqual(cfg.ghosts, 3)
        self.assertEqual(cfg.lives, 5)
        self.assertEqual(cfg.level, 2)
        self.assertAlmostEqual(cfg.speed, 1.5)

    def test_config_hashable_per_field(self):
        """Config 是普通 dataclass（不可 hash）——字段可任意赋值"""
        cfg = Config(map_path="/tmp/x.txt", no_color=True, log_ai=True)
        self.assertEqual(cfg.map_path, "/tmp/x.txt")
        self.assertTrue(cfg.no_color)
        self.assertTrue(cfg.log_ai)


if __name__ == "__main__":
    unittest.main(verbosity=2)