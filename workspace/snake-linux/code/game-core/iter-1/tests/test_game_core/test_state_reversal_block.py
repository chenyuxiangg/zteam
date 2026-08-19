"""反向输入测试：长度 ≥ 2 静默忽略；长度 1 允许（架构特例）。"""
import unittest
import random
from game_core import GameState, Difficulty, Point, Direction, Food
from dataclasses import replace
from game_core import Snake


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)


class TestReversalBlock(_Base):
    """UT #9a + #9b"""

    def test_reversal_blocked_when_length_2_or_more(self):
        # UT #9a: 默认蛇长 3，set_direction(LEFT)（反向于 RIGHT）后 step，蛇仍按 RIGHT 走
        s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng)
        s2 = s.set_direction(Direction.LEFT).step()
        # 蛇头应朝右走 (+1)
        self.assertEqual(s2.snake.body[0].x, 11)
        self.assertEqual(s2.direction, Direction.RIGHT)

    def test_reversal_allowed_when_length_1(self):
        # UT #9b: 长度 1 时反向允许
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=self.rng)
        # 强制蛇身长度 1
        s = replace(
            s,
            snake=Snake((Point(2, 2),)),
            direction=Direction.RIGHT,
            pending_direction=None,
            food=Food(Point(4, 4)),
        )
        s2 = s.set_direction(Direction.LEFT)
        # pending 应被设为 LEFT（不是忽略）
        self.assertEqual(s2.pending_direction, Direction.LEFT)
        s3 = s2.step()
        # 蛇头从 (2,2) 走到 (1,2)
        self.assertEqual(s3.snake.body[0], Point(1, 2))


if __name__ == "__main__":
    unittest.main()