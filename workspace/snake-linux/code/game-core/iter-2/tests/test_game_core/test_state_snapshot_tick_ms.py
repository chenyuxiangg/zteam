"""snapshot.tick_ms 走 speed_curve 增量测试（UT #26）。

迭代 2 起：Snapshot.tick_ms == speed_curve(score, difficulty)。
"""
import unittest
import random
import dataclasses

from game_core import (
    Difficulty,
    Direction,
    GameState,
    speed_curve,
)
from game_core.types import Snake, Point
from game_core import Food


class TestSnapshotTickMsFromSpeedCurve(unittest.TestCase):
    """UT #26：构造 → step N 次吃到 score=N → snapshot.tick_ms == speed_curve(N, difficulty)。"""

    def test_tick_ms_score_zero(self):
        rng = random.Random(42)
        s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=rng)
        snap = s.snapshot()
        self.assertEqual(snap.tick_ms, speed_curve(0, Difficulty.MEDIUM))
        self.assertEqual(snap.tick_ms, 160)

    def test_tick_ms_after_eat(self):
        # 吃一次后 score=1，tick_ms 应等于 speed_curve(1, MEDIUM) = 156
        rng = random.Random(42)
        s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=rng)
        # 构造吃食：把蛇身凑到食物旁
        s = dataclasses.replace(
            s, snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT, pending_direction=None,
            food=Food(Point(2, 2)),
        )
        s = s.step()
        self.assertEqual(s.score, 1)
        self.assertEqual(s.snapshot().tick_ms, speed_curve(1, Difficulty.MEDIUM))
        self.assertEqual(s.snapshot().tick_ms, 156)

    def test_tick_ms_per_difficulty(self):
        for diff, base_tick in [
            (Difficulty.EASY, 250),
            (Difficulty.MEDIUM, 160),
            (Difficulty.HARD, 100),
        ]:
            s = GameState(width=10, height=10, difficulty=diff, rng=random.Random(0))
            self.assertEqual(s.snapshot().tick_ms, base_tick)


if __name__ == "__main__":
    unittest.main()