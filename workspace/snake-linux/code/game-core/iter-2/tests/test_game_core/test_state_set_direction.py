"""set_direction + pending 合并测试：同节拍多次 set_direction 取最后一次；幂等；帧内不立即变 direction。"""
import unittest
import random
from game_core import GameState, Difficulty, Point, Direction


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=self.rng)


class TestSetDirection(_Base):
    """UT #10 + #11 + #17"""

    def test_set_direction_same_is_idempotent(self):
        before = self.s.snapshot()
        s2 = self.s.set_direction(Direction.RIGHT)
        self.assertEqual(s2.snapshot(), before)

    def test_pending_overrides_on_step(self):
        # UT #11: set_direction(UP) -> set_direction(LEFT) -> step
        # LEFT 是当前方向 RIGHT 的反向，被静默忽略；最后生效的合法 pending 是 UP
        s = self.s.set_direction(Direction.UP).set_direction(Direction.LEFT)
        s2 = s.step()
        # 头从 (10,7) -> (10,6) 朝 UP（LEFT 被忽略，UP 仍生效）
        self.assertEqual(s2.snake.body[0], Point(10, 6))
        self.assertEqual(s2.direction, Direction.UP)

    def test_pending_merges_orthogonal(self):
        # 同节拍多次 set_direction（合法正交方向）取最后一次
        s = self.s.set_direction(Direction.UP).set_direction(Direction.LEFT)
        # 注意 LEFT 是 RIGHT 的反向被忽略；改用正交测试
        s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
        s = s.set_direction(Direction.UP).set_direction(Direction.DOWN)
        s2 = s.step()
        # DOWN 覆盖 UP
        self.assertEqual(s2.direction, Direction.DOWN)

    def test_set_direction_does_not_change_direction_immediately(self):
        # UT #17: set_direction(UP) 后 state.direction 仍为 RIGHT（pending 隔离）
        s2 = self.s.set_direction(Direction.UP)
        self.assertEqual(s2.direction, Direction.RIGHT)
        # pending_direction 是隔离的
        self.assertIsNotNone(s2.pending_direction)
        self.assertEqual(s2.pending_direction, Direction.UP)

    def test_step_clears_pending(self):
        # UT #18: step 后 pending=None，新 set_direction 不被旧 pending 污染
        s = self.s.set_direction(Direction.UP)
        s = s.step()  # 消费 pending，direction 变 UP
        self.assertEqual(s.direction, Direction.UP)
        self.assertIsNone(s.pending_direction)
        # 新 set_direction：LEFT 是 UP 的反向（D正交），是合法正交方向 → pending=LEFT
        s2 = s.set_direction(Direction.LEFT)
        self.assertEqual(s2.pending_direction, Direction.LEFT)
        # 再 step 应按 LEFT 走（不是继承 UP）
        before_head = s2.snake.body[0]
        s3 = s2.step()
        # 头从 (10,6) -> (9,6) 朝 LEFT
        self.assertEqual(s3.snake.body[0].x, before_head.x - 1)
        self.assertEqual(s3.direction, Direction.LEFT)


if __name__ == "__main__":
    unittest.main()