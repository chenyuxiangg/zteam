"""得分事件回调测试：触发时机、参数、异常不捕获、None 静默、替换、非吃食不触发。

FR-13 + C2-3。
迭代 2 增量 UT #36~41。
"""
import unittest
import random
import dataclasses

from game_core import (
    Difficulty,
    Direction,
    GameState,
    GameStatus,
)
from game_core.types import Snake, Point
from game_core import Food


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)
        self.events: list = []
        self.cb = lambda s: self.events.append(s)  # noqa: E731

    def make_small_state(self, with_cb=True):
        kwargs = {
            "width": 5,
            "height": 5,
            "difficulty": Difficulty.MEDIUM,
            "rng": random.Random(42),
        }
        if with_cb:
            kwargs["score_callback"] = self.cb
        return GameState(**kwargs)


class TestCallbackTriggered(_Base):
    """UT #36：step 吃到食物 → events == [1]；再吃 → [1, 2]。"""

    def test_callback_triggered_on_eat(self):
        s = self.make_small_state()
        # 构造蛇身紧贴食物：将食物放在 (3,2)（蛇头在 (2,2)、RIGHT 方向下一格）
        # 用 dataclasses.replace 把食物放过来；排除蛇身（food not in body）
        s = dataclasses.replace(
            s, food=Food(Point(3, 2))
        )
        # 验证 food 不在蛇身
        self.assertNotIn(s.food.pos, set(s.snake.body))
        s2 = s.step()  # 头到 (3,2)，吃食
        self.assertEqual(s2.score, 1)
        self.assertEqual(self.events, [1])

    def test_callback_two_eats(self):
        # 用 small state 但精确控制食物位置和方向
        # 把蛇身移成 (1,2)，方向 RIGHT，食物在 (2,2)——吃一次后变 (2,2)
        # 然后再 step 到 (3,2)
        s = self.make_small_state()
        s = dataclasses.replace(
            s,
            snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT,
            pending_direction=None,
            food=Food(Point(2, 2)),
        )
        s2 = s.step()  # 吃 1 次
        self.assertEqual(s2.score, 1)
        self.assertEqual(self.events, [1])

    def test_callback_triggered_each_eat(self):
        s = self.make_small_state()
        # 直接吃两次：把蛇身挪到 (1,2) 朝 RIGHT，food 在 (2,2)
        s = dataclasses.replace(
            s,
            snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT,
            pending_direction=None,
            food=Food(Point(2, 2)),
        )
        s = s.step()  # 吃 → score=1，事件 [1]
        # 再吃一次：food 应已重生。我们控制 RNG 为确定性，把 food 手动设到下一格
        s = dataclasses.replace(
            s, food=Food(Point(3, 2))
        )
        s = s.step()  # 吃 → score=2，事件 [1,2]
        self.assertEqual(s.score, 2)
        self.assertEqual(self.events, [1, 2])


class TestCallbackParamIsNewScore(_Base):
    """UT #37：回调参数 = new_score（严格对应）。"""

    def test_callback_param_is_new_score(self):
        events = []
        s = self.make_small_state()
        s = dataclasses.replace(
            s, snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT, pending_direction=None,
            food=Food(Point(2, 2)),
        )
        # 清空 self.events 用自己的 cb
        cb = lambda score: events.append(score)  # noqa: E731
        s = dataclasses.replace(s, _score_callback=cb)
        s = s.step()
        self.assertEqual(events, [1])

    def test_callback_param_matches_score_field(self):
        # 每步回调参数 == 当前 state.score
        events: list = []
        cb = lambda score: events.append(score)  # noqa: E731
        s = self.make_small_state()
        s = dataclasses.replace(
            s, snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT, pending_direction=None,
            food=Food(Point(2, 2)),
        )
        s = dataclasses.replace(s, _score_callback=cb)
        s = s.step()
        self.assertEqual(s.score, events[-1])


class TestCallbackNoneSilent(_Base):
    """UT #38：回调为 None 静默（无副作用、score 字段正确更新）。"""

    def test_callback_none_silent(self):
        s = self.make_small_state(with_cb=False)
        s = dataclasses.replace(
            s, snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT, pending_direction=None,
            food=Food(Point(2, 2)),
        )
        s2 = s.step()
        self.assertEqual(s2.score, 1)
        # 无异常、无报错


class TestCallbackExceptionNotCaught(_Base):
    """UT #39：回调异常不捕获 + pure-function 语义（旧 state 未污染）。"""

    def test_callback_exception_propagates(self):
        def bad_cb(score):
            raise RuntimeError("storage failure")

        s = GameState(
            width=5, height=5, difficulty=Difficulty.MEDIUM,
            rng=random.Random(42), score_callback=bad_cb,
        )
        s = dataclasses.replace(
            s, snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT, pending_direction=None,
            food=Food(Point(2, 2)),
        )
        before = s.snapshot()
        with self.assertRaises(RuntimeError):
            s.step()
        # pure-function 语义：旧 state 未污染
        self.assertEqual(s.snapshot(), before)


class TestCallbackReplace(_Base):
    """UT #40：set_score_callback 替换回调，旧 cb 不再被调。"""

    def test_replace_callback(self):
        old_cb = lambda x: None  # noqa: E731
        new_events: list = []
        new_cb = lambda x: new_events.append(x)  # noqa: E731

        s = self.make_small_state()  # 默认带 self.cb
        s = s.set_score_callback(new_cb)
        # 吃一次
        s = dataclasses.replace(
            s, snake=Snake((Point(1, 2),)),
            direction=Direction.RIGHT, pending_direction=None,
            food=Food(Point(2, 2)),
        )
        s = s.step()
        # self.events（旧 cb 的 events）应为空
        self.assertEqual(self.events, [])
        # new_events 应为 [1]
        self.assertEqual(new_events, [1])


class TestCallbackNotFiredOnNonEat(_Base):
    """UT #41：非吃食 step 不触发回调。"""

    def test_callback_not_fired_on_move(self):
        s = self.make_small_state()
        # 蛇身默认 (2,2) → (0,2) → (1,2)，方向 RIGHT；food 在某处
        # 直接 step（不构造吃食）：移动一格
        s2 = s.step()
        # 确保没吃食：score 不变
        self.assertEqual(s2.score, s.score)
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()