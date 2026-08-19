"""端到端 100 步回归测试：固定 seed 跑 100 步，验证 score 与蛇长一致。"""
import unittest
import random
from game_core import GameState, Difficulty, GameStatus


class TestEndToEnd(unittest.TestCase):
    """UT #19"""

    def test_100_steps_score_length_consistent(self):
        rng = random.Random(42)
        s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=rng)
        steps_done = 0
        for _ in range(100):
            if s.status == GameStatus.OVER:
                break
            s = s.step()
            steps_done += 1
        # 100 步内大概率未 OVER（20x15 网格大）；score 应等于（蛇长 - 3）
        self.assertEqual(s.score, len(s.snake.body) - 3)
        # 至少走了一步
        self.assertGreater(steps_done, 0)
        # snake body 长度 >= 3
        self.assertGreaterEqual(len(s.snake.body), 3)


if __name__ == "__main__":
    unittest.main()