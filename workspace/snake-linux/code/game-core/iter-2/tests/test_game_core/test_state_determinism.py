"""确定性测试：固定 seed → 固定初始食物。"""
import unittest
import random
from game_core import GameState, Difficulty


class TestDeterminism(unittest.TestCase):
    """UT #12"""

    def test_same_seed_same_food(self):
        s1 = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        s2 = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        self.assertEqual(s1.food.pos, s2.food.pos)

    def test_different_seed_different_food(self):
        s1 = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        s2 = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=random.Random(43))
        # 不同 seed 大概率食物不同（也可能巧合相同，但概率极低）
        self.assertNotEqual(s1.food.pos, s2.food.pos)

    def test_default_rng_is_instance(self):
        # UT INV-6: 默认 rng 是 random.Random() 实例，非全局
        s = GameState(width=10, height=10, difficulty=Difficulty.EASY)
        # 内部 rng 属性不应是 None
        self.assertIsNotNone(s.rng)
        # 二次构造产生的食物应不同（实例独立）
        s2 = GameState(width=10, height=10, difficulty=Difficulty.EASY)
        self.assertNotEqual(s.food.pos, s2.food.pos)


if __name__ == "__main__":
    unittest.main()