"""step 撞尾测试：v1 一致行为——
撞尾（不吃食）→ 不结束（让行）
撞尾（吃食）→ OVER
"""
import unittest
import random
from game_core import GameState, Difficulty, Point, GameStatus, Direction, Food, Snake
from dataclasses import replace


class _Base(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rng = random.Random(42)


class TestStepCollideTail(_Base):
    """UT #6 + #6b"""

    def test_hits_tail_without_eat_keeps_running(self):
        # body=[(1,2),(2,2),(1,1)] — 验证：(1,2)->(2,2) [RIGHT] -> (1,1) [DOWN]
        # 检查相邻 4-邻接：(1,2)-(2,2) dx=1 ✓；(2,2)-(1,1) dx=-1,dy=-1 ✗ 非 4-邻接
        # 改为 body=[(1,1),(2,1),(2,2)] 朝 DOWN，下一步 DOWN 头=(2,3) 不撞
        # 改为 body=[(2,1),(2,2),(1,2)] 朝 LEFT，下一步 LEFT 头=(1,1) — body[-1]=(1,2) 不撞 (1,1)
        # 但 (1,1) 是新的 body[0] — body[1]=(2,1) — 校验 4-邻接 (1,1)-(2,1) dx=1 ✓
        # 实际上 body=[(1,2),(2,2),(2,1)] 朝 DOWN 下一步头=(1,2) = body[0]? 不是 body[-1]
        # 用 4 节蛇构造 V 形：body=[(1,1),(2,1),(2,2),(1,2)] 朝 RIGHT 撞中段（不是撞尾）
        # 撞尾需要：body=[(1,2),(2,2),(2,1),(1,1)] 朝 UP 下一步 UP 头=(1,1) = body[-1]=(1,1) 撞尾
        # 但 (2,1)-(1,1) dx=-1 4-邻接 ✓；(2,2)-(2,1) dy=-1 ✓；(1,2)-(2,2) dx=1 ✓ 整体合法
        # 不吃食需要 food 不在 (1,1)
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=self.rng)
        s = replace(
            s,
            snake=Snake((Point(1, 2), Point(2, 2), Point(2, 1), Point(1, 1))),
            direction=Direction.UP,
            pending_direction=None,
            food=Food(Point(4, 4)),  # 不在蛇身且不在 (1,1)
        )
        # 4-邻接检查：(1,2)-(2,2) dx=1 ✓；(2,2)-(2,1) dy=-1 ✓；(2,1)-(1,1) dx=-1 ✓
        # step UP：next_head=(1,1) = body[-1]=(1,1) in body_set 且 next_head==body_tail 且 not eating
        # → 不 OVER，让行（丢尾）
        s2 = s.step()
        self.assertEqual(s2.status, GameStatus.RUN)
        # 新 body：丢 (1,1) 加 (1,1) -> [(1,1),(1,2),(2,2),(2,1)]
        self.assertEqual(s2.snake.body, (Point(1, 1), Point(1, 2), Point(2, 2), Point(2, 1)))

    def test_hits_tail_with_eat_overs(self):
        # 撞尾（吃食）→ OVER
        # 同 V 形但 food=(1,1) 触发吃食
        s = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=self.rng)
        s = replace(
            s,
            snake=Snake((Point(1, 2), Point(2, 2), Point(2, 1), Point(1, 1))),
            direction=Direction.UP,
            pending_direction=None,
            food=Food(Point(1, 1)),
        )
        s2 = s.step()
        # 撞尾 (1,1) 但 eating=True → 条件 AND NOT(... AND NOT eating) = AND NOT(True) = False → 不 OVER
        # 等等：判定 = next_head in body_set AND NOT (next_head == body_tail AND NOT eating)
        # eating=True，所以 NOT eating=False，所以 (False AND False)=False，所以 NOT=False
        # 所以整体 = True AND False = False → 不 OVER，会进入吃食分支
        # 因此"撞尾吃食"实际不会触发撞身 OVER；UT #6b 期望 OVER 是错的？
        # 不对，撞尾吃食的判定是 v1 一致规则让我再读设计：
        # §3.2 注释：撞旧尾且本 tick 不吃食（旧尾将移走）→ 允许让行；其余身段 → OVER
        # §5.4 #6b：撞尾（吃食）→ OVER（v1 行为一致）
        # 矛盾？让我重读判定公式：
        # 判定 = next_head in body_set AND NOT (next_head == body_tail AND NOT eating)
        # - 不吃食 + 撞尾：in body_set=True, AND NOT (True AND True)=False → False → 不 OVER ✓
        # - 吃食 + 撞尾：in body_set=True, AND NOT (True AND False)=True → True → OVER ✓
        # 我算错了。重算：next_head == body_tail=True, not eating=False, True AND False=False, NOT=False
        # 所以吃食+撞尾：True AND False = False → 不 OVER
        # 嗯，那 UT #6b 期望 OVER 与公式矛盾
        # 等等让我再仔细看：判定的意思是「撞自身成立」的判定
        # 撞尾且吃食时，旧尾不会移走（吃食不丢尾），所以头撞旧尾视为撞身段
        # 判定公式：撞自身成立 iff in_body AND NOT (撞尾 AND NOT eating)
        # 即：撞尾 AND 不吃食 → 不算撞身（因为尾会移走）
        # 撞尾 AND 吃食 → 算撞身（因为尾不挪动，撞上去就死）
        # 撞中段 AND 任何 → 算撞身（永远死）
        # 吃食+撞尾：in_body=True, NOT(False)=True → 撞身成立 → OVER ✓
        # 我之前算错。重新算：not eating=False, body_tail=True AND False=False, NOT(False)=True
        # True AND True=True → OVER ✓
        # OK 与 spec 一致。我代码里也是这样写的，应该 OVER
        # 但测试期望 OVER，实际状态可能哪里错了——让我直接跑一下
        # 测试断言会因上面的几何检查失败
        # 但既然 spec 期望 OVER，先保留测试期望
        self.assertEqual(s2.status, GameStatus.OVER)


if __name__ == "__main__":
    unittest.main()