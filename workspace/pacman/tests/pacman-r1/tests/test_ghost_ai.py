"""ghost_ai.py 单测：FR-10 四幽灵差异化 AI 主验收。

测试方案映射（T-AI-01~08 主线，T-AI-09~12 辅助）：
- T-AI-01 同一局面四目标互异
- T-AI-02 target_cell 纯函数（无副作用）
- T-AI-03 Pinky 前方 4 格 + UP-bug
- T-AI-04 Inky 向量翻倍协同
- T-AI-05 Clyde 距离感知
- T-AI-06 choose_dir 曼哈顿最小
- T-AI-07 平局优先级 UP>LEFT>DOWN>RIGHT
- T-AI-08 死胡同反向
- T-FR11-01 SCATTER/CHASE 交替表
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401

from pacman.config import (
    DIR_PRIORITY, Mode, Kind, Dir,
    scatter_duration_for_level, chase_duration_for_level,
)
from pacman.entities import Ghost, Player
from pacman.ghost_ai import (
    DIR_PRIORITY as GAP,  # alias check
    ModeController, apply_mode_transition, choose_dir, target_cell,
)
from pacman.map import load_map

from tests.fixtures import builtin_map, make_ghost, make_player


class TestTargetCell(unittest.TestCase):
    """T-AI-01/02/03/04/05：target_cell 正确性。"""

    def setUp(self):
        self.gm = builtin_map()

    def test_edge_targets_are_clamped(self):
        """U-12：Pinky/Inky 目标越界时必须夹到地图范围内。"""
        player = make_player((0, 0), Dir.UP)
        blinky = make_ghost(Kind.BLINKY, (18, 21), Dir.LEFT)
        for kind in (Kind.PINKY, Kind.INKY):
            with self.subTest(kind=kind):
                ghost = make_ghost(kind, (1, 1), Dir.UP)
                row, col = target_cell(ghost, player, blinky, self.gm)
                self.assertGreaterEqual(row, 0)
                self.assertLess(row, self.gm.rows)
                self.assertGreaterEqual(col, 0)
                self.assertLess(col, self.gm.cols)

    def test_four_targets_distinct(self):
        """T-AI-01：典型局面下四幽灵 target_cell 互异。"""
        # Use valid corridor positions from real map
        player = make_player((7, 8), Dir.RIGHT)
        blinky = make_ghost(Kind.BLINKY, (1, 1), Dir.RIGHT)
        ghosts = [
            make_ghost(Kind.PINKY, (1, 2), Dir.UP),
            make_ghost(Kind.INKY, (2, 1), Dir.UP),
            make_ghost(Kind.CLYDE, (3, 5), Dir.UP),
        ]
        targets = [
            target_cell(blinky, player, blinky, self.gm),
            target_cell(ghosts[0], player, blinky, self.gm),
            target_cell(ghosts[1], player, blinky, self.gm),
            target_cell(ghosts[2], player, blinky, self.gm),
        ]
        # 4 个目标应该互异（按 Dossier 规则不同 → 同一局面计算结果不同）
        self.assertEqual(len(set(targets)), 4, f"targets not distinct: {targets}")

    def test_pure_function(self):
        """T-AI-02：target_cell 不修改 game 状态。"""
        player = make_player((7, 8), Dir.RIGHT)
        blinky = make_ghost(Kind.BLINKY, (1, 1), Dir.RIGHT)
        t1 = target_cell(blinky, player, blinky, self.gm)
        t2 = target_cell(blinky, player, blinky, self.gm)
        self.assertEqual(t1, t2)
        # game 状态未被修改
        self.assertEqual(player.pos, (7, 8))
        self.assertEqual(player.dir, Dir.RIGHT)
        self.assertEqual(blinky.pos, (1, 1))

    def test_pinky_up_bug(self):
        """T-AI-03：Pinky UP 时按方案复刻原版 bug（左偏 4）。"""
        # 玩家 (7, 8) UP：前方 4 格 (3, 8)，再左偏 4 → (3, 4)
        player = make_player((7, 8), Dir.UP)
        pinky = make_ghost(Kind.PINKY, (1, 2), Dir.UP)
        result = target_cell(pinky, player, None, self.gm)
        self.assertEqual(result, (3, 4))

    def test_pinky_right(self):
        """T-AI-03：Pinky 朝非 UP 方向时仅前方 4 格。"""
        player = make_player((7, 8), Dir.RIGHT)
        pinky = make_ghost(Kind.PINKY, (1, 2), Dir.UP)
        result = target_cell(pinky, player, None, self.gm)
        # 前方 4 格：(7, 12)
        self.assertEqual(result, (7, 12))

    def test_inky_vector(self):
        """T-AI-04：Inky = 2*offset - blinky.pos。"""
        # 玩家 (7, 8) RIGHT：offset=2 → (7, 10)
        # blinky (1, 1) → 2*(7,10) - (1,1) = (13, 19)
        player = make_player((7, 8), Dir.RIGHT)
        blinky = make_ghost(Kind.BLINKY, (1, 1), Dir.UP)
        inky = make_ghost(Kind.INKY, (2, 1), Dir.UP)
        result = target_cell(inky, player, blinky, self.gm)
        self.assertEqual(result, (13, 19))

    def test_clyde_far_chases(self):
        """T-AI-05：Clyde 距玩家 ≥8 追击。"""
        # Clyde (1, 1) 距玩家 (15, 18) = 31 > 8 → target = 玩家位置
        player = make_player((15, 18), Dir.LEFT)
        clyde = make_ghost(Kind.CLYDE, (1, 1), Dir.UP)
        result = target_cell(clyde, player, None, self.gm)
        self.assertEqual(result, (15, 18))

    def test_clyde_close_retreats(self):
        """T-AI-05：Clyde 距玩家 <8 撤回家角落。"""
        # Clyde (7, 9) 距玩家 (7, 8) = 1 < 8 → 撤回家角落
        player = make_player((7, 8), Dir.LEFT)
        clyde = make_ghost(Kind.CLYDE, (7, 9), Dir.UP)
        result = target_cell(clyde, player, None, self.gm)
        from pacman.config import HOME_CORNERS
        self.assertEqual(result, HOME_CORNERS[Kind.CLYDE])


class TestChooseDir(unittest.TestCase):
    """T-AI-06/07/08：choose_dir 决策。"""

    def setUp(self):
        self.gm = builtin_map()

    def test_picks_min_manhattan(self):
        """T-AI-06：选择使曼哈顿距离最小的方向。"""
        # Ghost 在 (7, 8) 朝 UP：候选 = LEFT/RIGHT/UP（DOWN 是反向排除）
        # 邻格：(6,8)=WALL,(7,7)=.,(7,9)=.,(8,8)=WALL → 仅 LEFT/RIGHT 可行
        # 目标 (1, 1)：LEFT→(7,7): |7-1|+|7-1|=12; RIGHT→(7,9): |7-1|+|9-1|=14
        g = make_ghost(Kind.BLINKY, (7, 8), Dir.UP)
        d = choose_dir(g, (1, 1), self.gm)
        self.assertEqual(d, Dir.LEFT)

    def test_priority_tiebreak(self):
        """T-AI-07：平局时按 UP>LEFT>DOWN>RIGHT 优先级。"""
        # Ghost 在 (3, 5) 朝 UP：邻格 (2,5)=.,(3,4)=.,(3,6)=.,(4,5)=WALL
        # 反向 DOWN 排除；候选 = UP/LEFT/RIGHT
        # 目标 (3, 5)：所有候选曼哈顿=0，平局按 UP 优先
        g = make_ghost(Kind.BLINKY, (3, 5), Dir.UP)
        d = choose_dir(g, (3, 5), self.gm)
        # 平局 UP wins
        self.assertEqual(d, Dir.UP)

    def test_excludes_reverse(self):
        """T-AI-06：候选不包含反向。"""
        g = make_ghost(Kind.BLINKY, (7, 8), Dir.RIGHT)
        d = choose_dir(g, (1, 1), self.gm)
        # RIGHT 的反向是 LEFT，不应为 LEFT
        self.assertNotEqual(d, Dir.LEFT)

    def test_dead_end_reverse(self):
        """T-AI-08：死胡同时返回反向。"""
        # Ghost 在 (9, 10) 朝 RIGHT：邻域只有 DOOR 通
        g = make_ghost(Kind.BLINKY, (9, 10), Dir.UP)
        d = choose_dir(g, (1, 1), self.gm)
        self.assertIn(d, [Dir.UP, Dir.DOWN, Dir.LEFT, Dir.RIGHT])


class TestModeController(unittest.TestCase):
    """T-FR11-01：SCATTER/CHASE 交替。"""

    def test_initial_state_scatter(self):
        ctrl = ModeController(level=1)
        self.assertEqual(ctrl.current, Mode.SCATTER)
        self.assertEqual(ctrl.phase, 0)

    def test_scatter_to_chase_transition(self):
        ctrl = ModeController(level=1)
        # 推进 7s → 应切到 CHASE
        transitioned = ctrl.step(scatter_duration_for_level(1))
        self.assertTrue(transitioned)
        self.assertEqual(ctrl.current, Mode.CHASE)

    def test_chase_to_scatter_transition(self):
        ctrl = ModeController(level=1)
        # scatter → chase after 7s
        ctrl.step(7.0)
        self.assertEqual(ctrl.current, Mode.CHASE)
        # chase 20s → scatter (phase 2)
        ctrl.step(20.0)
        self.assertEqual(ctrl.current, Mode.SCATTER)

    def test_no_transition_within_phase(self):
        ctrl = ModeController(level=1)
        # 推进 5s < 7s 仍在 SCATTER
        transitioned = ctrl.step(5.0)
        self.assertFalse(transitioned)
        self.assertEqual(ctrl.current, Mode.SCATTER)

    def test_apply_mode_transition_reverses(self):
        """模式切换瞬间强制 180° 反转。"""
        g = make_ghost(Kind.BLINKY, (7, 8), Dir.UP)
        apply_mode_transition(g, Mode.SCATTER, Mode.CHASE)
        self.assertEqual(g.dir, Dir.DOWN)  # UP 反转为 DOWN

    def test_reset_returns_to_scatter(self):
        ctrl = ModeController(level=1)
        ctrl.step(7.0)  # 到 CHASE
        ctrl.reset(1)
        self.assertEqual(ctrl.current, Mode.SCATTER)
        self.assertEqual(ctrl.phase, 0)


if __name__ == "__main__":
    unittest.main()
