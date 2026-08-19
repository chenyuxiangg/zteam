"""speed_curve + MIN_TICK_MS 测试：NFR-01 量化保证、单调不增、三档独立下限。

FR：NFR-01 量化约束（困难档节拍 <= 简单档 50%）。
迭代 2 增量 UT #22~25。
"""
import unittest

from game_core import Difficulty, speed_curve, MIN_TICK_MS


class TestSpeedCurveScoreZero(unittest.TestCase):
    """UT #22：score=0 时三档节拍 = 250/160/100。"""

    def test_easy_score_zero(self):
        self.assertEqual(speed_curve(0, Difficulty.EASY), 250)

    def test_medium_score_zero(self):
        self.assertEqual(speed_curve(0, Difficulty.MEDIUM), 160)

    def test_hard_score_zero(self):
        self.assertEqual(speed_curve(0, Difficulty.HARD), 100)


class TestSpeedCurveNfr01Half(unittest.TestCase):
    """UT #23：任意 score 下 HARD <= EASY*0.5（subTest 循环）。"""

    def test_hard_le_easy_half(self):
        for score in range(0, 101):
            with self.subTest(score=score):
                easy = speed_curve(score, Difficulty.EASY)
                hard = speed_curve(score, Difficulty.HARD)
                self.assertLessEqual(hard, easy * 0.5)


class TestSpeedCurveMonotonic(unittest.TestCase):
    """UT #24：speed_curve 单调不增（score 越大、tick_ms 越小/持平）。"""

    def test_monotonic_non_increasing(self):
        for diff in Difficulty:
            for score in range(0, 101):
                with self.subTest(difficulty=diff.value, score=score):
                    cur = speed_curve(score, diff)
                    nxt = speed_curve(score + 1, diff)
                    self.assertLessEqual(nxt, cur)


class TestSpeedCurveMinFloor(unittest.TestCase):
    """UT #25：三档独立下限钳制（r2 修订：per-difficulty dict）。"""

    def test_min_tick_ms_dict(self):
        # MIN_TICK_MS 是 Dict[Difficulty, int]
        self.assertEqual(MIN_TICK_MS[Difficulty.EASY], 100)
        self.assertEqual(MIN_TICK_MS[Difficulty.MEDIUM], 80)
        self.assertEqual(MIN_TICK_MS[Difficulty.HARD], 50)

    def test_floor_at_large_score(self):
        # score 极大时钳到 per-difficulty 下限
        self.assertEqual(speed_curve(100, Difficulty.EASY), 100)
        self.assertEqual(speed_curve(100, Difficulty.MEDIUM), 80)
        self.assertEqual(speed_curve(100, Difficulty.HARD), 50)

    def test_floor_at_extreme_score(self):
        # score 远超钳制点仍不破下限
        self.assertEqual(speed_curve(10000, Difficulty.EASY), 100)
        self.assertEqual(speed_curve(10000, Difficulty.MEDIUM), 80)
        self.assertEqual(speed_curve(10000, Difficulty.HARD), 50)


class TestSpeedCurveIntermediate(unittest.TestCase):
    """区间内（未达下限前）值正确性。"""

    def test_easy_linear(self):
        # EASY: base=250, k=4
        self.assertEqual(speed_curve(1, Difficulty.EASY), 246)
        self.assertEqual(speed_curve(10, Difficulty.EASY), 210)
        self.assertEqual(speed_curve(20, Difficulty.EASY), 170)

    def test_medium_linear(self):
        # MEDIUM: base=160, k=4
        self.assertEqual(speed_curve(1, Difficulty.MEDIUM), 156)
        self.assertEqual(speed_curve(10, Difficulty.MEDIUM), 120)

    def test_hard_linear(self):
        # HARD: base=100, k=3
        self.assertEqual(speed_curve(1, Difficulty.HARD), 97)
        self.assertEqual(speed_curve(10, Difficulty.HARD), 70)


if __name__ == "__main__":
    unittest.main()