"""step 撞墙测试：头出界 → OVER，分数/蛇身不变。"""
import unittest
import random
from game_core import GameState, Difficulty, Direction, Point, GameStatus


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)


class TestStepCollideWall(_Base):
    """UT #4"""

    def test_hits_wall_right(self):
        # 5x5：body = [(2,2),(1,2),(0,2)] 朝右，下一步 = (3,2) 仍合法；再下一步 = (4,2) 仍合法；
        # 第三步 = (5,2) 出界
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        s = s.step().step()  # 蛇头到 (4,2)
        s_over = s.step()  # 蛇头到 (5,2) 出界
        self.assertEqual(s_over.status, GameStatus.OVER)
        # 蛇身未变（撞墙 OVER 不变 snake/food/score）
        self.assertEqual(s_over.snake.body, s.snake.body)
        self.assertEqual(s_over.score, s.score)

    def test_hits_wall_left(self):
        # 强制让蛇朝左再撞：先 set_direction(LEFT) 然后走 3 步到 x=-1
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        s = s.set_direction(Direction.LEFT)
        s_over = s.step()  # 头从 (2,2) -> (1,2)；再 step 一次出界
        s_over = s_over.step()  # 0,2 仍合法
        s_over = s_over.step()  # -1,2 出界
        self.assertEqual(s_over.status, GameStatus.OVER)


if __name__ == "__main__":
    unittest.main()