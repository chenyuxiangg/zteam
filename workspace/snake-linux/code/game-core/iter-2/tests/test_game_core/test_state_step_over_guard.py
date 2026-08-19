"""step OVER 保护测试：OVER 后 step/set_direction 抛 InvalidStateError。"""
import unittest
import random
from game_core import (
    GameState, Difficulty, Direction, InvalidStateError, GameStatus
)


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)


class TestStepOverGuard(_Base):
    """UT #7 + #8"""

    def test_step_after_over_raises(self):
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=self.rng)
        # 走到墙边撞墙 OVER
        s = s.step().step().step()  # OVER
        self.assertEqual(s.status, GameStatus.OVER)
        with self.assertRaises(InvalidStateError):
            s.step()

    def test_set_direction_after_over_raises(self):
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=self.rng)
        s = s.step().step().step()  # OVER
        with self.assertRaises(InvalidStateError):
            s.set_direction(Direction.UP)


if __name__ == "__main__":
    unittest.main()