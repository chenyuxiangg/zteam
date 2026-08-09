"""config.py 单测。

覆盖测试方案：
- TC-X2 --ghosts 非法值（1/5/abc）→ 报错
- TC-X3 --lives 0/10 报错
- TC-X4 --speed 0/2.5/-1 报错
- TC-N7 0 条 pip 命令即可运行（间接验证 requirements.txt 不存在非空依赖）
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests._path import code_dir

from pacman.config import (
    MIN_TERM_COLS,
    MIN_TERM_LINES,
    TICK_SECONDS,
    Config,
    build_parser,
    parse_args,
)


class TestDefaults(unittest.TestCase):
    """Q1~Q12 落定值 + 端默认行为。"""

    def test_default_ghost_count(self):
        cfg = parse_args([])
        self.assertEqual(cfg.ghost_count, 4)

    def test_default_lives(self):
        cfg = parse_args([])
        self.assertEqual(cfg.lives, 3)

    def test_default_speed(self):
        cfg = parse_args([])
        self.assertAlmostEqual(cfg.speed, 1.0)

    def test_default_no_color(self):
        cfg = parse_args([])
        self.assertFalse(cfg.no_color)

    def test_default_start_level(self):
        cfg = parse_args([])
        self.assertEqual(cfg.start_level, 1)

    def test_default_map_is_builtin(self):
        cfg = parse_args([])
        self.assertEqual(cfg.map_path.name, "map_classic.txt")
        self.assertTrue(cfg.map_path.exists())

    def test_tick_seconds(self):
        self.assertAlmostEqual(TICK_SECONDS, 0.1)

    def test_min_terminal_size(self):
        # NFR-04：终端 ≥80×24
        self.assertEqual(MIN_TERM_COLS, 80)
        self.assertEqual(MIN_TERM_LINES, 24)


class TestOverrides(unittest.TestCase):
    """合法参数生效。"""

    def test_ghosts_2_3_4(self):
        for n in (2, 3, 4):
            cfg = parse_args([f"--ghosts={n}"])
            self.assertEqual(cfg.ghost_count, n)

    def test_lives_boundary(self):
        for n in (1, 9):
            cfg = parse_args([f"--lives={n}"])
            self.assertEqual(cfg.lives, n)

    def test_speed_boundary(self):
        for s in (0.5, 2.0):
            cfg = parse_args([f"--speed={s}"])
            self.assertAlmostEqual(cfg.speed, s)

    def test_level_override(self):
        cfg = parse_args(["--level=10"])
        self.assertEqual(cfg.start_level, 10)

    def test_no_color_flag(self):
        cfg = parse_args(["--no-color"])
        self.assertTrue(cfg.no_color)

    def test_map_path_override(self):
        cfg = parse_args(["--map=/tmp/foo.map"])
        self.assertEqual(str(cfg.map_path), "/tmp/foo.map")


class TestInvalidArgs(unittest.TestCase):
    """TC-X2/X3/X4：非法 CLI 参数 → SystemExit + 报错信息。"""

    def assert_cli_error(self, argv: list):
        with self.assertRaises(SystemExit):
            parse_args(argv)

    def test_ghosts_invalid_choices(self):
        for v in ("1", "5", "abc", "0"):
            self.assert_cli_error([f"--ghosts={v}"])

    def test_lives_out_of_range(self):
        for v in ("0", "10", "-1"):
            self.assert_cli_error([f"--lives={v}"])

    def test_lives_non_integer(self):
        self.assert_cli_error(["--lives=abc"])

    def test_speed_out_of_range(self):
        for v in ("0", "2.5", "-1", "0.4", "2.1"):
            self.assert_cli_error([f"--speed={v}"])

    def test_speed_non_numeric(self):
        self.assert_cli_error(["--speed=fast"])

    def test_level_below_one(self):
        self.assert_cli_error(["--level=0"])

    def test_level_non_integer(self):
        self.assert_cli_error(["--level=abc"])

    def test_unknown_flag(self):
        self.assert_cli_error(["--nope"])


class TestConfigDataclassFrozen(unittest.TestCase):
    """Config 是 frozen dataclass → 修改属性应抛错。"""

    def test_frozen(self):
        cfg = Config()
        with self.assertRaises(Exception):
            cfg.lives = 5  # type: ignore[misc]


class TestParserHelpHasNoSideEffect(unittest.TestCase):
    def test_help(self):
        # --help 触发 SystemExit，但 parser 应当无其他副作用
        with self.assertRaises(SystemExit):
            parse_args(["--help"])


if __name__ == "__main__":
    unittest.main()
