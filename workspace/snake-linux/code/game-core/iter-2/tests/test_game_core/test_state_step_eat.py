"""step 吃食测试：score+1、不丢尾、新食物不在蛇身。"""
import unittest
import random
from game_core import GameState, Difficulty, Point, Direction


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)


class TestStepEat(_Base):
    """UT #3"""

    def test_step_eats_when_head_lands_on_food(self):
        # 用 5x5 网格确定性测：seed=42 跑一次取 food，再造一个初始 food 在蛇头下一步的状态
        # 简化做法：先跑 random.Random(42) 构造一次记下初始 food.pos
        s0 = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        initial_food = s0.food.pos
        # 直接构造一个新 state，把 food 放在蛇头下一步 RIGHT 的位置上 (3, 2)
        # 默认 5x5：body = [(2,2),(1,2),(0,2)]，头在 (2,2) 朝右，下一步 = (3,2)
        rng2 = random.Random(7)
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=rng2)
        # 通过 _food 直接赋值（构造测试钩子），这里改为造一个状态 food=(3,2)
        # 由于 GameState 没有 setter，我们采用 monkey-patch：替换 food 字段
        # 用 dataclasses.replace 需要 food 可被替换——这里借助 object.__setattr__ 因为 GameState 是 frozen dataclass
        from dataclasses import replace
        from game_core import Food
        s = replace(s, food=Food(Point(3, 2)))
        s2 = s.step()
        # 蛇长 +1
        self.assertEqual(len(s2.snake.body), 4)
        # score +1
        self.assertEqual(s2.score, 1)
        # 蛇头 = (3,2)
        self.assertEqual(s2.snake.body[0], Point(3, 2))
        # 新食物不在新蛇身
        self.assertNotIn(s2.food.pos, set(s2.snake.body))
        self.assertNotEqual(s2.food.pos, initial_food)  # 重新生成

    def test_eat_no_tail_drop(self):
        # 吃食后不丢尾：蛇长+1 且尾部保留
        from dataclasses import replace
        from game_core import Food
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=random.Random(7))
        s = replace(s, food=Food(Point(3, 2)))
        s2 = s.step()
        # 旧尾 (0,2) 应仍在 body 里（蛇变成 [(3,2),(2,2),(1,2),(0,2)]）
        self.assertEqual(s2.snake.body[-1], Point(0, 2))


if __name__ == "__main__":
    unittest.main()