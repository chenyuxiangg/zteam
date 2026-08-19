"""step 撞自身测试：头撞非尾身段 → OVER。

直接用 monkey-patch 构造精确的 U 形蛇身场景，避免路径推演错误。
"""
import unittest
import random
from game_core import GameState, Difficulty, Point, GameStatus, Direction, Snake, Food
from dataclasses import replace


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)


class TestStepCollideSelf(_Base):
    """UT #5"""

    def test_hits_non_tail_body_segment(self):
        # 构造 5x5 蛇身 U 形：[(1,1),(1,2),(2,2),(2,1)] 朝 RIGHT
        # 下一步 RIGHT 头=(2,1) 撞中段 (2,1)? — body[3] 既是 body[-1] 也是新头位置——撞尾让行不 OVER
        # 改：body=[(1,1),(2,1),(2,2),(1,2)] 朝 RIGHT，下一步 RIGHT 头=(2,1) 撞 body[1] 中段 OVER
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=self.rng)
        # 上面构造 4 节蛇：验证 4-邻接 (1,1)-(2,1)-(2,2)-(1,2) 是合法路径（起点 L 形 OK）
        s = replace(
            s,
            snake=Snake((Point(1, 1), Point(2, 1), Point(2, 2), Point(1, 2))),
            direction=Direction.RIGHT,
            pending_direction=None,
            food=Food(Point(0, 0)),  # 远离头部
        )
        s_over = s.step()
        # next_head = (2,1) 在 body_set 中且不是 body[-1]=(1,2) 且不吃食 → OVER
        self.assertEqual(s_over.status, GameStatus.OVER)


if __name__ == "__main__":
    unittest.main()