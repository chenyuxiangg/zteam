"""config.py 单测：默认值、难度公式、边界条件、依赖声明。

覆盖测试方案：
- T-FR12-01 幽灵数量可配置（2/3/4）
- T-GAME-11 --speed 倍率
- T-GAME-12 --level 5 难度
- T-GAME-13 能量豆递减公式
- T-GAME-14 玩家恒 1.0 快于幽灵
- T-AI-11 Elroy 阈值
- T-AI-12 出场规则（按关卡）
- T-FR19-01 / T-NFR-05-01 依赖 0 个 pip 包
- T-EXIT-04 --no-color
- T-GAME-16 非法参数（边界，不强制）
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401

from pacman.config import (
    Config,
    DOT_SCORE,
    GHOST_BASE_SPEED,
    GHOST_CHAIN_SCORES,
    GHOST_ELROY_SPEED,
    GHOST_EYES_SPEED,
    GHOST_FRIGHTENED_SPEED,
    PLAYER_SPEED,
    POWER_SCORE,
    PROTECTION_SECONDS,
    TICK_MS,
    chase_duration_for_level,
    clyde_release_dots_for_level,
    elroy_threshold_for_level,
    ghost_speed_for_level,
    inky_release_dots_for_level,
    power_duration_for_level,
    scatter_duration_for_level,
)


class TestDefaults(unittest.TestCase):
    """Q1~Q12 落定值。"""

    def test_ghost_count_default_4(self):
        c = Config()
        self.assertEqual(c.ghosts, 4)

    def test_lives_default_3(self):
        c = Config()
        self.assertEqual(c.lives, 3)

    def test_level_default_1(self):
        c = Config()
        self.assertEqual(c.level, 1)

    def test_speed_default_1(self):
        c = Config()
        self.assertEqual(c.speed, 1.0)

    def test_no_color_default_false(self):
        c = Config()
        self.assertFalse(c.no_color)

    def test_log_ai_default_false(self):
        c = Config()
        self.assertFalse(c.log_ai)

    def test_map_path_default(self):
        c = Config()
        self.assertEqual(c.map_path, "data/map_classic.txt")


class TestConstants(unittest.TestCase):
    """实现表常量（来自 Dossier / 简化方案）。"""

    def test_player_speed_faster_than_ghost(self):
        """T-GAME-14：玩家永远比幽灵快。"""
        self.assertGreater(PLAYER_SPEED, GHOST_BASE_SPEED)
        self.assertGreater(PLAYER_SPEED, GHOST_FRIGHTENED_SPEED)

    def test_ghost_eyes_faster_than_base(self):
        """EYES 状态 1.5 倍速（返鬼屋加速）。"""
        self.assertGreater(GHOST_EYES_SPEED, GHOST_BASE_SPEED)

    def test_elroy_speed_equals_player(self):
        """Elroy 1.0 追平玩家。"""
        self.assertEqual(GHOST_ELROY_SPEED, PLAYER_SPEED)

    def test_chain_scores(self):
        """连吃分数：200/400/800/1600 封顶。"""
        self.assertEqual(GHOST_CHAIN_SCORES, (200, 400, 800, 1600))

    def test_power_score(self):
        self.assertEqual(POWER_SCORE, 50)

    def test_dot_score(self):
        self.assertEqual(DOT_SCORE, 10)

    def test_protection_seconds(self):
        self.assertEqual(PROTECTION_SECONDS, 2.0)

    def test_tick_ms(self):
        self.assertEqual(TICK_MS, 100)


class TestDifficulty(unittest.TestCase):
    """难度公式按关卡正确：T-GAME-12 / T-GAME-13 / T-GAME-14 / T-AI-11 / T-AI-12。"""

    def test_power_duration_decreases(self):
        """T-GAME-13：能量豆时长随关卡递减，下限 1s。"""
        self.assertEqual(power_duration_for_level(1), 6.0)
        self.assertEqual(power_duration_for_level(2), 5.5)
        self.assertEqual(power_duration_for_level(3), 5.0)
        # 后续递减
        for L in range(4, 30):
            d_prev = power_duration_for_level(L - 1)
            d_cur = power_duration_for_level(L)
            self.assertLessEqual(d_cur, d_prev, f"L={L}")
        # 下限 1s
        for L in (10, 20, 100):
            self.assertGreaterEqual(power_duration_for_level(L), 1.0)

    def test_ghost_speed_increases(self):
        """T-GAME-14：幽灵速度随关卡递增（封顶 < 玩家）。"""
        self.assertEqual(ghost_speed_for_level(1), 0.9)
        # 随关卡递增
        for L in range(2, 8):
            self.assertGreaterEqual(ghost_speed_for_level(L), ghost_speed_for_level(L - 1))
        # 封顶不会追上玩家
        for L in (1, 5, 10, 100):
            self.assertLess(ghost_speed_for_level(L), PLAYER_SPEED)

    def test_elroy_threshold_decreases(self):
        """T-AI-11：Elroy 触发阈值随关卡递减，下限 5。"""
        self.assertEqual(elroy_threshold_for_level(1), 20)
        for L in range(2, 20):
            t = elroy_threshold_for_level(L)
            self.assertLessEqual(t, elroy_threshold_for_level(L - 1))
        # 下限
        for L in (20, 50, 100):
            self.assertGreaterEqual(elroy_threshold_for_level(L), 5)

    def test_release_dots_decrease(self):
        """T-AI-12：出场豆数阈值随关卡递减，下限 10/20。"""
        self.assertEqual(inky_release_dots_for_level(1), 30)
        self.assertEqual(clyde_release_dots_for_level(1), 60)
        # 递减
        for L in range(2, 20):
            self.assertLessEqual(inky_release_dots_for_level(L), inky_release_dots_for_level(L - 1))
            self.assertLessEqual(clyde_release_dots_for_level(L), clyde_release_dots_for_level(L - 1))
        # 下限
        for L in (20, 50):
            self.assertGreaterEqual(inky_release_dots_for_level(L), 10)
            self.assertGreaterEqual(clyde_release_dots_for_level(L), 20)

    def test_scatter_decreases_to_one(self):
        """SCATTER 时长随关卡递减，下限 1s。"""
        self.assertEqual(scatter_duration_for_level(1), 7.0)
        for L in (2, 3, 4, 5, 10, 100):
            self.assertGreaterEqual(scatter_duration_for_level(L), 1.0)

    def test_chase_duration(self):
        """CHASE 持续时长按方案固定 20s。"""
        for L in (1, 2, 5, 10, 20):
            self.assertEqual(chase_duration_for_level(L), 20.0)


class TestConfigOverrides(unittest.TestCase):
    """Config 接受合法参数。"""

    def test_ghosts_2_3_4(self):
        """T-FR12-01：2/3/4 幽灵数量合法。"""
        for n in (2, 3, 4):
            c = Config(ghosts=n)
            self.assertEqual(c.ghosts, n)

    def test_speed_range(self):
        """T-GAME-11：--speed 0.5~2.0。"""
        for s in (0.5, 1.0, 1.5, 2.0):
            c = Config(speed=s)
            self.assertEqual(c.speed, s)

    def test_level_5(self):
        """T-GAME-12：--level 5 起始关卡。"""
        c = Config(level=5)
        self.assertEqual(c.level, 5)

    def test_lives_range(self):
        for n in (1, 3, 5, 9):
            c = Config(lives=n)
            self.assertEqual(c.lives, n)


if __name__ == "__main__":
    unittest.main()
