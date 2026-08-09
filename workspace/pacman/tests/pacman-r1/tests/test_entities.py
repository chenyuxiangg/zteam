"""entities.py 单测：移动累积器、玩家缓冲、幽灵 reset。

覆盖测试方案：
- TC-B2 玩家输入缓冲队列容量 1（新覆盖旧）
- Mover 速度累积器：低 dt 不移动、累积到整数才走
"""
from __future__ import annotations

import unittest

from pacman.entities import Dir, GhostKind, GhostMode, Mover, Player
from pacman.map import Pos

from tests.fixtures import make_ghost, make_player


class TestMoverAccumulator(unittest.TestCase):
    """速度累积器：cells_per_tick=1.0, tick=0.1s。"""

    def test_partial_dt_no_step(self):
        m = Mover(pos=Pos(0, 0), spawn=Pos(0, 0), direction=Dir.UP)
        # dt=0.05 → 累积 0.5 → int 0 → 不动
        steps = m.add_motion(1.0, 0.05, tick_seconds=0.1)
        self.assertEqual(steps, 0)
        self.assertEqual(m.pos, Pos(0, 0))

    def test_full_dt_one_step(self):
        m = Mover(pos=Pos(0, 0), spawn=Pos(0, 0), direction=Dir.UP)
        steps = m.add_motion(1.0, 0.1, tick_seconds=0.1)
        self.assertEqual(steps, 1)
        self.assertEqual(m.pos, Pos(0, 0))  # add_motion 不移动 pos，只返步数

    def test_accumulator_residue(self):
        m = Mover(pos=Pos(0, 0), spawn=Pos(0, 0), direction=Dir.UP)
        # 0.15s 累积 1.5 → 走 1 步，余 ≈ 0.5（浮点 0.4999999999999998）
        m.add_motion(1.0, 0.15, tick_seconds=0.1)
        self.assertAlmostEqual(m.accumulator, 0.5)
        # 再 0.06s 累积 0.6 → 总 ≈ 1.1 → 走 1 步
        steps = m.add_motion(1.0, 0.06, tick_seconds=0.1)
        self.assertEqual(steps, 1)

    def test_step_cap_at_four(self):
        # 调试器停顿后单帧不能跨越过多格
        m = Mover(pos=Pos(0, 0), spawn=Pos(0, 0), direction=Dir.UP)
        steps = m.add_motion(1.0, 100.0, tick_seconds=0.1)
        self.assertLessEqual(steps, 4)

    def test_zero_dt_returns_zero(self):
        m = Mover(pos=Pos(0, 0), spawn=Pos(0, 0), direction=Dir.UP)
        steps = m.add_motion(1.0, 0.0, tick_seconds=0.1)
        self.assertEqual(steps, 0)

    def test_negative_dt_ignored(self):
        m = Mover(pos=Pos(0, 0), spawn=Pos(0, 0), direction=Dir.UP)
        steps = m.add_motion(1.0, -0.5, tick_seconds=0.1)
        self.assertEqual(steps, 0)


class TestPlayerBuffer(unittest.TestCase):
    """TC-B2：缓冲队列容量 1（新覆盖旧）。"""

    def test_queue_overwrites(self):
        p = make_player()
        p.queue_direction(Dir.UP)
        p.queue_direction(Dir.DOWN)
        self.assertIs(p.buffered_direction, Dir.DOWN)

    def test_reset_clears_buffer(self):
        p = make_player()
        p.queue_direction(Dir.RIGHT)
        p.reset_position()
        self.assertIsNone(p.buffered_direction)
        self.assertEqual(p.pos, p.spawn)


class TestGhostResetForRound(unittest.TestCase):
    """TC-C9：扣命/过关后 reset_for_round → 回 spawn、SCATTER、force_reverse 清。"""

    def test_reset(self):
        g = make_ghost(GhostKind.BLINKY, Pos(0, 21), Dir.DOWN, mode=GhostMode.CHASE)
        g.force_reverse = True
        g.released = True
        g.release_dots = 0
        g.reset_for_round(released=False, release_dots=30)
        self.assertEqual(g.pos, g.spawn)
        self.assertIs(g.direction, Dir.UP)
        self.assertIs(g.mode, GhostMode.SCATTER)
        self.assertFalse(g.released)
        self.assertEqual(g.release_dots, 30)
        self.assertFalse(g.force_reverse)


class TestDirReverseProperty(unittest.TestCase):
    def test_reverse(self):
        self.assertIs(Dir.UP.reverse, Dir.DOWN)
        self.assertIs(Dir.DOWN.reverse, Dir.UP)
        self.assertIs(Dir.LEFT.reverse, Dir.RIGHT)
        self.assertIs(Dir.RIGHT.reverse, Dir.LEFT)


if __name__ == "__main__":
    unittest.main()
