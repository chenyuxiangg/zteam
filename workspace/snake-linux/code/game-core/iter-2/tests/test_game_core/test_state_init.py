"""GameState 构造测试：初始蛇位置、初始方向、初始食物不在蛇身、score=0；网格下限校验。"""
import unittest
import random
from game_core import GameState, Difficulty, Direction, Point, GameStatus


class _GameCoreBase(unittest.TestCase):
    """测试基类：固定 RNG 的默认 state。"""

    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.default_state = GameState(
            width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng
        )

    def make_small_state(self, rng=None):
        return GameState(
            width=5, height=5, difficulty=Difficulty.MEDIUM, rng=rng or random.Random(42)
        )


class TestStateInit(_GameCoreBase):
    """UT #1 + #14 + #14b"""

    def test_initial_snake_length_3(self):
        self.assertEqual(len(self.default_state.snake.body), 3)

    def test_initial_direction_right(self):
        self.assertEqual(self.default_state.direction, Direction.RIGHT)

    def test_initial_score_zero(self):
        self.assertEqual(self.default_state.score, 0)

    def test_initial_status_run(self):
        self.assertEqual(self.default_state.status, GameStatus.RUN)

    def test_food_not_in_snake(self):
        self.assertNotIn(self.default_state.food.pos, set(self.default_state.snake.body))

    def test_initial_snake_position_centered_right(self):
        # 默认 20x15：body = [(10,7), (9,7), (8,7)]
        body = self.default_state.snake.body
        self.assertEqual(body, (Point(10, 7), Point(9, 7), Point(8, 7)))

    def test_grid_min_4x4_accepted(self):
        # UT #14b
        s = GameState(width=4, height=4, difficulty=Difficulty.EASY, rng=random.Random(0))
        for p in s.snake.body:
            self.assertTrue(0 <= p.x < 4)
            self.assertTrue(0 <= p.y < 4)

    def test_grid_3x3_rejected(self):
        # UT #14
        with self.assertRaises(ValueError):
            GameState(width=3, height=3, difficulty=Difficulty.EASY, rng=random.Random(0))

    def test_grid_3x15_rejected(self):
        with self.assertRaises(ValueError):
            GameState(width=3, height=15, difficulty=Difficulty.EASY, rng=random.Random(0))

    def test_grid_20x3_rejected(self):
        with self.assertRaises(ValueError):
            GameState(width=20, height=3, difficulty=Difficulty.EASY, rng=random.Random(0))


if __name__ == "__main__":
    unittest.main()