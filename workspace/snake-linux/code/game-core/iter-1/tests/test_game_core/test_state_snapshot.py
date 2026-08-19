"""snapshot 测试：不可变、字段一致、tick_ms == difficulty.base_tick_ms。"""
import unittest
import random
from game_core import GameState, Difficulty, Snapshot, Point, GameStatus, Direction
from dataclasses import FrozenInstanceError


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng)


class TestSnapshot(_Base):
    """UT #13 + #20"""

    def test_snapshot_fields_consistent(self):
        snap = self.s.snapshot()
        self.assertEqual(snap.snake_body, self.s.snake.body)
        self.assertEqual(snap.food, self.s.food.pos)
        self.assertEqual(snap.score, self.s.score)
        self.assertEqual(snap.length, len(self.s.snake.body))
        self.assertEqual(snap.status, self.s.status)
        self.assertEqual(snap.difficulty, self.s.difficulty)

    def test_snapshot_is_frozen(self):
        snap = self.s.snapshot()
        with self.assertRaises(FrozenInstanceError):
            snap.score = 999  # type: ignore[misc]

    def test_snapshot_tick_ms_matches_difficulty(self):
        # UT #20: 迭代 1 tick_ms == difficulty.base_tick_ms
        for diff, expected in [
            (Difficulty.EASY, 250),
            (Difficulty.MEDIUM, 160),
            (Difficulty.HARD, 100),
        ]:
            s = GameState(width=10, height=10, difficulty=diff, rng=random.Random(0))
            self.assertEqual(s.snapshot().tick_ms, expected)


if __name__ == "__main__":
    unittest.main()