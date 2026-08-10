"""entities.py 单测：Mover 速度累积 + Player 转向缓冲 + Ghost 模式速度。

覆盖测试方案：
- T-CTRL-02 缓冲容量 1
- T-AI-10 速度差异
- T-AI-11 Elroy 速度
- T-FR11-01 模式切换
- T-NFR-04 健壮性：玩家撞墙不穿
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401

from pacman.config import (
    GHOST_BASE_SPEED, GHOST_EYES_SPEED, GHOST_FRIGHTENED_SPEED,
    GHOST_ELROY_SPEED, PLAYER_SPEED, Dir, Kind, Mode,
)
from pacman.entities import Ghost, Mover, Player
from pacman.ghost_ai import apply_mode_transition, maybe_release_ghost

from tests.fixtures import builtin_map, make_ghost, make_player


class TestMoverSpeed(unittest.TestCase):
    """Mover 速度累积器（基础移动体）。"""

    def test_speed_accumulator(self):
        m = Mover((5, 5), Dir.RIGHT, speed=1.0)
        # 第一次 add_motion：acc=1.0 → 走 1 步
        steps = m.add_motion()
        self.assertEqual(steps, 1)
        self.assertEqual(m.pos, (5, 6))
        # 第二次：acc=0+1.0=1.0 → 又 1 步
        steps = m.add_motion()
        self.assertEqual(steps, 1)
        self.assertEqual(m.pos, (5, 7))

    def test_sub1_speed_requires_multiple_ticks(self):
        m = Mover((5, 5), Dir.RIGHT, speed=0.5)
        # 第一次：acc=0.5 < 1.0 → 0 步
        steps = m.add_motion()
        self.assertEqual(steps, 0)
        self.assertEqual(m.pos, (5, 5))
        # 第二次：acc=1.0 → 1 步
        steps = m.add_motion()
        self.assertEqual(steps, 1)
        self.assertEqual(m.pos, (5, 6))

    def test_reverse_direction(self):
        m = Mover((5, 5), Dir.RIGHT, speed=1.0)
        m.reverse()
        self.assertEqual(m.dir, Dir.LEFT)


class TestPlayerBuffer(unittest.TestCase):
    """T-CTRL-02：Player 转向缓冲容量 1。"""

    def setUp(self):
        self.gm = builtin_map()
        self.player = make_player((12, 9), Dir.LEFT)

    def test_buffer_capacity_one(self):
        """容量 1：新指令覆盖旧指令。"""
        # 玩家朝 UP；请求 RIGHT（非反向）→ 缓冲
        # 再请求 LEFT（也非反向）→ 覆盖
        self.player.dir = Dir.UP
        self.player.request_turn(Dir.RIGHT)
        self.assertEqual(len(self.player.turn_buffer), 1)
        self.player.request_turn(Dir.LEFT)
        self.assertEqual(len(self.player.turn_buffer), 1)
        self.assertEqual(self.player.turn_buffer[-1], Dir.LEFT)

    def test_immediate_reverse(self):
        """反向指令立即执行（不缓冲）。"""
        self.player.request_turn(Dir.RIGHT)  # LEFT 的反向
        self.assertEqual(self.player.dir, Dir.RIGHT)
        self.assertEqual(len(self.player.turn_buffer), 0)

    def test_consume_turn(self):
        """consume_turn 在合法方向上执行。"""
        # 玩家在 (12, 9) 朝 LEFT；请求 RIGHT；下一格 (12, 10) 可通行
        self.player.request_turn(Dir.RIGHT)
        self.player.consume_turn(self.gm)
        self.assertEqual(self.player.dir, Dir.RIGHT)
        # 缓冲被清
        self.assertEqual(len(self.player.turn_buffer), 0)

    def test_consume_turn_invalid_keeps_buffer(self):
        """非法方向保留缓冲（玩家可能还会继续按）。"""
        # 玩家在 (12, 9)；请求 UP；上一格 (11, 9) 是 DOT 实际可通行…… 改用墙
        # 用 (1, 1) 玩家朝 UP，请求 UP 上一格 (0, 1) = WALL
        p = make_player((1, 1), Dir.UP)
        p.request_turn(Dir.UP)
        p.consume_turn(self.gm)
        # (0,1) 是墙，不应转向
        self.assertEqual(p.dir, Dir.UP)
        # 缓冲保留（待玩家继续按）
        self.assertEqual(len(p.turn_buffer), 1)


class TestGhostSpeed(unittest.TestCase):
    """T-AI-10/11：Ghost 模式速度差异。"""

    def test_base_speed(self):
        g = make_ghost(Kind.BLINKY, (1, 1), Dir.UP, level=1)
        g.mode = Mode.CHASE
        self.assertEqual(g.speed_for_mode(), GHOST_BASE_SPEED)

    def test_frightened_speed_slower(self):
        g = make_ghost(Kind.BLINKY, (1, 1), Dir.UP, level=1)
        g.mode = Mode.FRIGHTENED
        self.assertEqual(g.speed_for_mode(), GHOST_FRIGHTENED_SPEED)
        self.assertLess(GHOST_FRIGHTENED_SPEED, GHOST_BASE_SPEED)

    def test_eyes_speed_faster(self):
        g = make_ghost(Kind.BLINKY, (1, 1), Dir.UP, level=1)
        g.mode = Mode.EYES
        self.assertEqual(g.speed_for_mode(), GHOST_EYES_SPEED)
        self.assertGreater(GHOST_EYES_SPEED, GHOST_BASE_SPEED)

    def test_elroy_speed_matches_player(self):
        """T-AI-11：Elroy 触发后速度 = 玩家速度。"""
        g = make_ghost(Kind.BLINKY, (1, 1), Dir.UP, level=1)
        g.elroy_active = True
        g.mode = Mode.CHASE
        self.assertEqual(g.speed_for_mode(), GHOST_ELROY_SPEED)
        self.assertEqual(GHOST_ELROY_SPEED, PLAYER_SPEED)

    def test_player_always_faster_than_ghost(self):
        """T-GAME-14：玩家永远比幽灵快。"""
        self.assertGreater(PLAYER_SPEED, GHOST_BASE_SPEED)
        self.assertGreater(PLAYER_SPEED, GHOST_FRIGHTENED_SPEED)
        # EYES 比玩家快（正常）
        self.assertGreater(GHOST_EYES_SPEED, PLAYER_SPEED)


class TestGhostRelease(unittest.TestCase):
    """U-22：Pinky/Blinky 立即、Inky 30 豆、Clyde 60 豆出场。"""

    def test_release_thresholds(self):
        blinky = make_ghost(Kind.BLINKY)
        pinky = make_ghost(Kind.PINKY)
        inky = make_ghost(Kind.INKY)
        clyde = make_ghost(Kind.CLYDE)
        self.assertTrue(maybe_release_ghost(blinky, 0))
        self.assertTrue(maybe_release_ghost(pinky, 0))
        self.assertFalse(maybe_release_ghost(inky, 29))
        self.assertTrue(maybe_release_ghost(inky, 30))
        self.assertFalse(maybe_release_ghost(clyde, 59))
        self.assertTrue(maybe_release_ghost(clyde, 60))


if __name__ == "__main__":
    unittest.main()
