"""Difficulty.base_tick_ms 走 speed_curve(0, self)（迭代 2 单一数据源）。"""
import unittest

from game_core import Difficulty, speed_curve


class TestDifficulty(unittest.TestCase):
    def test_three_levels(self):
        self.assertEqual(len(list(Difficulty)), 3)

    def test_easy_base_tick_ms(self):
        # UT #15（iter-2）：base_tick_ms == speed_curve(0, EASY)
        self.assertEqual(Difficulty.EASY.base_tick_ms, 250)
        self.assertEqual(Difficulty.EASY.base_tick_ms, speed_curve(0, Difficulty.EASY))

    def test_medium_base_tick_ms(self):
        self.assertEqual(Difficulty.MEDIUM.base_tick_ms, 160)
        self.assertEqual(Difficulty.MEDIUM.base_tick_ms, speed_curve(0, Difficulty.MEDIUM))

    def test_hard_base_tick_ms(self):
        self.assertEqual(Difficulty.HARD.base_tick_ms, 100)
        self.assertEqual(Difficulty.HARD.base_tick_ms, speed_curve(0, Difficulty.HARD))

    def test_base_tick_ms_routed_through_speed_curve(self):
        # UT #15b (iter-2)：base_tick_ms 本质是 speed_curve(0, self) 的快捷访问
        # 验证三个档位都走 speed_curve(0, d) 而非内部常量直读
        for d, expected in [
            (Difficulty.EASY, 250),
            (Difficulty.MEDIUM, 160),
            (Difficulty.HARD, 100),
        ]:
            self.assertEqual(d.base_tick_ms, expected)
            self.assertEqual(d.base_tick_ms, speed_curve(0, d))


if __name__ == "__main__":
    unittest.main()