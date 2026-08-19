"""Difficulty.base_tick_ms 从 DIFFICULTY_PARAMS 读取（单一数据源）。"""
import unittest
from game_core import Difficulty, DIFFICULTY_PARAMS


class TestDifficulty(unittest.TestCase):
    def test_three_levels(self):
        self.assertEqual(len(list(Difficulty)), 3)
        self.assertIn(Difficulty.EASY, DIFFICULTY_PARAMS)
        self.assertIn(Difficulty.MEDIUM, DIFFICULTY_PARAMS)
        self.assertIn(Difficulty.HARD, DIFFICULTY_PARAMS)

    def test_easy_base_tick_ms(self):
        # UT #15
        self.assertEqual(Difficulty.EASY.base_tick_ms, 250)

    def test_medium_base_tick_ms(self):
        self.assertEqual(Difficulty.MEDIUM.base_tick_ms, 160)

    def test_hard_base_tick_ms(self):
        self.assertEqual(Difficulty.HARD.base_tick_ms, 100)

    def test_property_reads_from_dict(self):
        # UT #15b：修改 DIFFICULTY_PARAMS 后 property 返回新值
        original = DIFFICULTY_PARAMS[Difficulty.EASY]["base_tick_ms"]
        try:
            DIFFICULTY_PARAMS[Difficulty.EASY]["base_tick_ms"] = 999
            self.assertEqual(Difficulty.EASY.base_tick_ms, 999)
        finally:
            DIFFICULTY_PARAMS[Difficulty.EASY]["base_tick_ms"] = original


if __name__ == "__main__":
    unittest.main()