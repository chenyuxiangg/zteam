"""step 普通移动测试：蛇头前进、蛇尾移除、score 不变。"""
import unittest
import random
from game_core import GameState, Difficulty, Point, GameStatus


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng)


class TestStepMove(_Base):
    """UT #2"""

    def test_step_advances_head_right(self):
        before = self.s.snapshot()
        s2 = self.s.step()
        # 默认 RIGHT，body[0] = (10,7) -> (11,7)
        self.assertEqual(s2.snake.body[0], Point(11, 7))
        # 尾巴移除
        self.assertEqual(len(s2.snake.body), 3)
        # score 不变
        self.assertEqual(s2.score, 0)
        # 原 state 未变（纯函数）
        self.assertEqual(self.s.snapshot(), before)

    def test_step_pure_function(self):
        # step 不修改 self
        before_head = self.s.snake.body[0]
        _ = self.s.step()
        self.assertEqual(self.s.snake.body[0], before_head)

    def test_multiple_steps(self):
        s = self.s
        for _ in range(5):
            s = s.step()
        # 5 步后 head.x = 10 + 5 = 15
        self.assertEqual(s.snake.body[0].x, 15)


if __name__ == "__main__":
    unittest.main()