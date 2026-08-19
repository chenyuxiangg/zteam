"""食物生成测试：排除蛇身；饥饿极限（全屏=蛇）抛 RuntimeError。"""
import unittest
import random
from game_core import GameState, Difficulty, Point, Food, Snake, GameStatus
from dataclasses import replace
from game_core.state import spawn_food


class TestFoodSpawn(unittest.TestCase):
    """UT #16"""

    def test_food_never_on_snake(self):
        # 跑 200 步吃食场景：每步后食物都不在蛇身
        rng = random.Random(123)
        s = GameState(width=10, height=10, difficulty=Difficulty.MEDIUM, rng=rng)
        seen_food_on_snake = False
        for _ in range(200):
            if s.status == GameStatus.OVER:
                break
            s = s.step()
            if s.food.pos in set(s.snake.body):
                seen_food_on_snake = True
                break
        self.assertFalse(seen_food_on_snake)

    def test_full_grid_raises(self):
        # 全屏填满 5x5，spawn_food 抛 RuntimeError
        rng = random.Random(0)
        # body 覆盖全部 25 格
        body = tuple(Point(x, y) for y in range(5) for x in range(5))
        with self.assertRaises(RuntimeError):
            spawn_food(rng, 5, 5, body)


if __name__ == "__main__":
    unittest.main()