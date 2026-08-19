"""toggle_pause 状态机测试：RUN↔PAUSED 切换；OVER 抛错；INV-8/9。

FR-12：暂停/继续；C2-2/C2-4/C2-5。
迭代 2 增量 UT #27~31。
"""
import unittest
import random

from game_core import (
    Difficulty,
    Direction,
    GameState,
    GameStatus,
    InvalidStateError,
)


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.s = GameState(
            width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng
        )


class TestTogglePauseRunToPaused(_Base):
    """UT #27：toggle_pause RUN→PAUSED。"""

    def test_pause_from_run(self):
        paused = self.s.toggle_pause()
        self.assertEqual(paused.status, GameStatus.PAUSED)


class TestTogglePausePausedToRun(_Base):
    """UT #28：toggle_pause PAUSED→RUN。"""

    def test_resume_from_paused(self):
        s2 = self.s.toggle_pause().toggle_pause()
        self.assertEqual(s2.status, GameStatus.RUN)


class TestTogglePauseOverGuard(_Base):
    """UT #29：toggle_pause OVER 抛错。"""

    def test_toggle_pause_on_over_raises(self):
        # 构造 OVER：撞墙
        # 默认 20x15、初始 RIGHT，头在 (10,7)；造一个右墙的 state
        import dataclasses
        from game_core.types import Snake, Point
        from game_core import Food
        # 让头朝右即将撞墙：把蛇头挪到最右
        s_near_wall = dataclasses.replace(
            self.s,
            snake=Snake((Point(19, 7), Point(18, 7), Point(17, 7))),
            direction=Direction.RIGHT,
            pending_direction=None,
            food=Food(Point(0, 0)),
        )
        # 但 (0,0) 是食物，先把食物清掉确保撞墙而非吃食
        s_near_wall = dataclasses.replace(
            s_near_wall, food=Food(Point(5, 0))  # 不在蛇身上也不在撞墙路径
        )
        over_state = s_near_wall.step()
        self.assertEqual(over_state.status, GameStatus.OVER)
        with self.assertRaises(InvalidStateError):
            over_state.toggle_pause()


class TestTogglePauseFieldFreeze(_Base):
    """UT #30：toggle_pause 字段冻结（INV-9：仅 status 翻转，其余不变）。"""

    def test_pause_does_not_change_other_fields(self):
        before = self.s.snapshot()
        paused = self.s.toggle_pause()
        # 通过 snapshot 比较（snake_body / food / score 等字段在 snapshot 内）
        paused_snap = paused.snapshot()
        self.assertEqual(paused_snap.snake_body, before.snake_body)
        self.assertEqual(paused_snap.food, before.food)
        self.assertEqual(paused_snap.score, before.score)
        self.assertEqual(paused_snap.length, before.length)
        self.assertEqual(paused_snap.difficulty, before.difficulty)
        # 校验 direction 字段：GameState 内部 direction 与 pending 不应被 toggle_pause 改
        self.assertEqual(self.s.direction, paused.direction)
        self.assertIsNone(paused.pending_direction)


class TestTogglePauseInv8PendingClear(_Base):
    """UT #31：INV-8 暂停→继续 清 pending_direction（防暂停前按 UP 撞尾）。"""

    def test_resume_clears_pending(self):
        # 暂停前按 UP（pending_direction=UP）
        s_pending = self.s.set_direction(Direction.UP)
        self.assertEqual(s_pending.pending_direction, Direction.UP)
        # 暂停
        s_paused = s_pending.toggle_pause()
        self.assertEqual(s_paused.status, GameStatus.PAUSED)
        # 继续（INV-8 清 pending）
        s_resumed = s_paused.toggle_pause()
        self.assertEqual(s_resumed.status, GameStatus.RUN)
        self.assertIsNone(s_resumed.pending_direction)


class TestTogglePauseTwice(_Base):
    """反复 toggle_pause 等价于两次翻转（仅 OVER 抛错）。"""

    def test_two_toggles_back_to_run(self):
        s2 = self.s.toggle_pause().toggle_pause()
        self.assertEqual(s2.status, GameStatus.RUN)
        s3 = s2.toggle_pause().toggle_pause()
        self.assertEqual(s3.status, GameStatus.RUN)


if __name__ == "__main__":
    unittest.main()