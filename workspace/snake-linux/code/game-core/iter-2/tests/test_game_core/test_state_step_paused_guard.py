"""PAUSED 期 step 抛错；set_direction 静默忽略 + 不入 pending（INV-8/9）。

FR-12；C2-4。
迭代 2 增量 UT #32~35。
"""
import unittest
import random
import dataclasses

from game_core import (
    Difficulty,
    Direction,
    GameState,
    GameStatus,
    InvalidStateError,
)
from game_core.types import Snake, Point
from game_core import Food


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.s = GameState(
            width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng
        )
        self.paused = self.s.toggle_pause()


class TestStepOnPaused(_Base):
    """UT #32：PAUSED 期 step 抛错。"""

    def test_step_on_paused_raises(self):
        with self.assertRaises(InvalidStateError):
            self.paused.step()


class TestSetDirectionOnPaused(_Base):
    """UT #33：PAUSED 期 set_direction 静默忽略（无报错、不入 pending）。"""

    def test_set_direction_on_paused_ignored(self):
        # paused.snapshot() 不变
        before = self.paused.snapshot()
        after = self.paused.set_direction(Direction.LEFT)
        # 不抛错
        self.assertEqual(after.status, GameStatus.PAUSED)
        # 不入 pending
        self.assertIsNone(after.pending_direction)
        # 状态字段冻结（INV-9）
        after_snap = after.snapshot()
        self.assertEqual(after_snap.snake_body, before.snake_body)
        self.assertEqual(after_snap.food, before.food)
        self.assertEqual(after_snap.score, before.score)


class TestSetDirectionOnPausedNotInPending(_Base):
    """UT #34：PAUSED 期 set_direction 后恢复 RUN，第一拍按原 direction 走（非新输入）。"""

    def test_paused_set_direction_does_not_leak_into_pending(self):
        # 暂停期按 LEFT
        s = self.paused.set_direction(Direction.LEFT)
        self.assertIsNone(s.pending_direction)
        # 恢复 RUN
        s_resumed = s.toggle_pause()
        self.assertEqual(s_resumed.status, GameStatus.RUN)
        # 第一拍 step：按原 direction=RIGHT 走（不是 LEFT）
        s_next = s_resumed.step()
        # 头从 (10,7) -> (11,7) 朝 RIGHT
        self.assertEqual(s_next.snake.body[0], Point(11, 7))
        self.assertEqual(s_next.direction, Direction.RIGHT)


class TestInv8PauseUpResumeFirstDirection(_Base):
    """UT #35：暂停前按 UP → 暂停 → 继续 → 第一拍按原 direction 走（INV-8 已清 pending）。"""

    def test_inv8_pending_cleared_on_resume(self):
        s2 = self.s.set_direction(Direction.UP)  # pending=UP
        self.assertEqual(s2.pending_direction, Direction.UP)
        # 暂停
        s3 = s2.toggle_pause()
        self.assertEqual(s3.status, GameStatus.PAUSED)
        # 继续 → INV-8 清 pending
        s4 = s3.toggle_pause()
        self.assertIsNone(s4.pending_direction)
        # 第一拍 step：按原 direction=RIGHT 走，不是 UP
        s5 = s4.step()
        self.assertEqual(s5.snake.body[0], Point(11, 7))
        self.assertEqual(s5.direction, Direction.RIGHT)


if __name__ == "__main__":
    unittest.main()