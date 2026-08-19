"""INV-8 专项测试 — 暂停前按 UP → 暂停 → 继续 → 第一拍按原方向走。

合并 §5.4 UT #35 与设计 §1.4 INV-8 不变量。
"""
import unittest
import random

from game_core import Difficulty, Direction, GameState, Point


class TestInv8PendingClear(unittest.TestCase):
    """INV-8：toggle_pause PAUSED→RUN 必须清 pending_direction。"""

    def setUp(self):
        self.rng = random.Random(42)
        self.s = GameState(
            width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng
        )

    def test_set_up_then_pause_resume_first_step_original_direction(self):
        # 暂停前按 UP
        s = self.s.set_direction(Direction.UP)
        self.assertEqual(s.pending_direction, Direction.UP)
        # 暂停
        s = s.toggle_pause()
        # 暂停期再按 DOWN（应被静默忽略，pending 保持 UP）
        s_paused_after_input = s.set_direction(Direction.DOWN)
        # pending 不被覆盖（DOWN 是 RIGHT 的正交，应入 pending，但 FR-12 暂停期忽略）
        # 实际上 RUN 状态下 s 已有 pending=UP（set_direction UP 之后）
        # RUN→PAUSED 不清 pending（仅 PAUSED→RUN 才清）
        # 暂停期 set_direction 被静默忽略 → pending 保持原值 UP
        self.assertEqual(s_paused_after_input.pending_direction, Direction.UP)
        # 继续（INV-8 清 pending）
        s_resumed = s_paused_after_input.toggle_pause()
        self.assertIsNone(s_resumed.pending_direction)
        # 第一拍 step：按原 direction=RIGHT 走（不是 UP、也不是 DOWN）
        s_next = s_resumed.step()
        self.assertEqual(s_next.snake.body[0], Point(11, 7))
        self.assertEqual(s_next.direction, Direction.RIGHT)

    def test_pending_cleared_after_resume(self):
        # 直接 set+pause+pause：中间不涉及 paused 期输入
        s = self.s.set_direction(Direction.UP)
        s = s.toggle_pause()  # PAUSED
        s = s.toggle_pause()  # RUN（INV-8 清 pending）
        self.assertIsNone(s.pending_direction)


if __name__ == "__main__":
    unittest.main()