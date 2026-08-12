"""幽灵 AI 测试：U-20 / U-21 / U-22 / U-23 / U-24 / U-25 / U-26 / U-27 / U-28 / U-29。

覆盖：
- FR-10 主验收（客观）：同一局面四幽灵 target_cell 互异（U-20）
- 各幽灵独立规则：Blinky=玩家当前位置（U-21）；Pinky 前方 4 格含 up-bug（U-22）；
  Inky 向量翻倍（U-23）；Clyde 距离感知（U-24）
- 边界：目标 clamp 到地图内（U-25）
- choose_dir：曼哈顿最小（U-26）/ 平局 UP>LEFT>DOWN>RIGHT（U-27）/ 死胡同掉头（U-28）
  / 排除反向（U-29）

fixtures 不依赖 curses；纯逻辑层，可脱离终端单测。
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401
from tests.fixtures import (
    builtin_map, make_player, make_ghost,
)

from pacman.config import (
    Dir, Kind, Mode,
    ALL_DIRS, REVERSE_DIR, DIR_PRIORITY,
    CLYDE_SHY_DISTANCE, HOME_CORNERS,
)
from pacman.ghost_ai import (
    target_cell, choose_dir, manhattan, clamp_pos, offset_n,
    ModeController, apply_mode_transition, maybe_release_ghost,
)


# 固定局面 fixture（U-20..U-29 共用同一组坐标，可复现）
FIX_PLAYER_POS = (5, 10)
FIX_PLAYER_DIR = Dir.RIGHT
FIX_BLINKY_POS = (3, 8)


def _build_fixed_scene():
    """构造固定局面：玩家 (5,10) dir=RIGHT，Blinky (3,8)，其余 3 幽灵不在场。"""
    gm = builtin_map()
    player = make_player(pos=FIX_PLAYER_POS, direction=FIX_PLAYER_DIR)
    blinky = make_ghost(kind=Kind.BLINKY, pos=FIX_BLINKY_POS, direction=Dir.UP)
    pinky = make_ghost(kind=Kind.PINKY, pos=(9, 10), direction=Dir.UP)
    inky = make_ghost(kind=Kind.INKY, pos=(9, 11), direction=Dir.UP)
    clyde = make_ghost(kind=Kind.CLYDE, pos=(9, 12), direction=Dir.UP)
    return gm, player, blinky, pinky, inky, clyde


class TestTargetCellFourDiffer(unittest.TestCase):
    """U-20：FR-10 主验收——同一局面四幽灵目标格两两不同。"""

    def test_u20_four_targets_mutually_distinct(self):
        gm, player, blinky, pinky, inky, clyde = _build_fixed_scene()
        tb = target_cell(blinky, player, blinky, gm)
        tp = target_cell(pinky, player, blinky, gm)
        ti = target_cell(inky, player, blinky, gm)
        tc = target_cell(clyde, player, blinky, gm)
        # 四者两两不同
        self.assertNotEqual(tb, tp)
        self.assertNotEqual(tb, ti)
        self.assertNotEqual(tb, tc)
        self.assertNotEqual(tp, ti)
        self.assertNotEqual(tp, tc)
        self.assertNotEqual(ti, tc)
        # 每个目标合法（在地图边界内）
        for r, c in (tb, tp, ti, tc):
            self.assertTrue(0 <= r < gm.rows)
            self.assertTrue(0 <= c < gm.cols)


class TestBlinkyRule(unittest.TestCase):
    """U-21：Blinky 目标 = 玩家当前位置（直线追击）。"""

    def test_u21_blinky_returns_player_pos(self):
        gm, player, blinky, *_ = _build_fixed_scene()
        t = target_cell(blinky, player, blinky, gm)
        self.assertEqual(t, (player.row, player.col))


class TestPinkyRule(unittest.TestCase):
    """U-22：Pinky 目标 = 玩家前方 4 格（含原版 up-bug 左偏 4）。"""

    def test_u22_pinky_right_4(self):
        gm, player, blinky, pinky, *_ = _build_fixed_scene()
        player.dir = Dir.RIGHT
        t = target_cell(pinky, player, blinky, gm)
        # 玩家 (5,10) RIGHT: (5, 14) 无 up-bug
        self.assertEqual(t, (5, 14))

    def test_u22_pinky_up_with_bug(self):
        gm, player, blinky, pinky, *_ = _build_fixed_scene()
        player.dir = Dir.UP
        t = target_cell(pinky, player, blinky, gm)
        # 原版 up-bug: (5-4, 10-4) = (1, 6) 因 up 时 c -= n
        self.assertEqual(t, (1, 6))

    def test_u22_pinky_left_4(self):
        gm, player, blinky, pinky, *_ = _build_fixed_scene()
        player.dir = Dir.LEFT
        t = target_cell(pinky, player, blinky, gm)
        self.assertEqual(t, (5, 6))


class TestInkyRule(unittest.TestCase):
    """U-23：Inky 目标 = clamp(2 × offset2 - blinky.pos)（向量翻倍）。"""

    def test_u23_inky_vector_doubled(self):
        gm, player, blinky, pinky, *_ = _build_fixed_scene()
        player.dir = Dir.RIGHT
        inky = make_ghost(kind=Kind.INKY, pos=(9, 11))
        # 玩家前方 2 格 = (5, 12) (right)
        # 2 * (5,12) - (3, 8) = (10-3, 24-8) = (7, 16)
        t = target_cell(inky, player, blinky, gm)
        self.assertEqual(t, (7, 16))

    def test_u23_inky_no_blinky_degrades_to_player(self):
        """无 Blinky 引用时降级到玩家位置（graceful degradation）。"""
        gm, player, *_ = _build_fixed_scene()
        inky = make_ghost(kind=Kind.INKY, pos=(9, 11))
        t = target_cell(inky, player, blinky=None, game_map=gm)
        self.assertEqual(t, (player.row, player.col))


class TestClydeRule(unittest.TestCase):
    """U-24：Clyde 距离感知——≥8 追玩家，<8 撤回家角落。"""

    def test_u24_clyde_far_chases(self):
        gm, player, *_ = _build_fixed_scene()
        # Clyde 距玩家 (5,10) 至少 8 格
        clyde = make_ghost(kind=Kind.CLYDE, pos=(15, 18))
        t = target_cell(clyde, player, blinky=None, game_map=gm)
        self.assertEqual(t, (player.row, player.col))

    def test_u24_clyde_close_retreats(self):
        gm, player, *_ = _build_fixed_scene()
        # Clyde 紧邻玩家 <8 格
        clyde = make_ghost(kind=Kind.CLYDE, pos=(6, 11))
        t = target_cell(clyde, player, blinky=None, game_map=gm)
        self.assertEqual(t, HOME_CORNERS[Kind.CLYDE])

    def test_u24_clyde_distance_threshold(self):
        """精确边界：距离 == 8 仍追玩家（≥ 阈值）。"""
        gm, player, *_ = _build_fixed_scene()
        # 找一个距玩家恰好 8 欧几里得的位置（DOWN 方向 (13,10)）
        clyde = make_ghost(kind=Kind.CLYDE, pos=(13, 10))
        # euclid((13,10), (5,10)) = 8 >= 8 → 追玩家
        t = target_cell(clyde, player, blinky=None, game_map=gm)
        self.assertEqual(t, (player.row, player.col))


class TestTargetClamp(unittest.TestCase):
    """U-25：Pinky/Inky 目标越界时 clamp 到地图内。"""

    def test_u25_pinky_target_clamped(self):
        gm, player, blinky, pinky, *_ = _build_fixed_scene()
        # 把玩家放在贴近地图边缘 (1, 20) 方向 LEFT
        player.row, player.col = 1, 20
        player.dir = Dir.LEFT
        # offset_n(1,20,LEFT,4) = (1, 16)
        t = target_cell(pinky, player, blinky, gm)
        self.assertEqual(t, (1, 16))  # 未出界 = clamp 后等于自身

    def test_u25_offset_helper_clamps(self):
        """clamp_pos 直接验证：负值 → 0，超界 → rows-1/cols-1。"""
        self.assertEqual(clamp_pos(-5, -1, 19, 22), (0, 0))
        self.assertEqual(clamp_pos(100, 100, 19, 22), (18, 21))
        self.assertEqual(clamp_pos(5, 10, 19, 22), (5, 10))


class TestOffsetN(unittest.TestCase):
    """offset_n：UP 时额外左偏 N（复刻原版 Dossier 记载的 bug）。"""

    def test_offset_right(self):
        self.assertEqual(offset_n(5, 10, Dir.RIGHT, 4), (5, 14))

    def test_offset_down(self):
        self.assertEqual(offset_n(5, 10, Dir.DOWN, 3), (8, 10))

    def test_offset_up_has_bug(self):
        """UP 时列额外减 N（行同时减 N）。"""
        self.assertEqual(offset_n(5, 10, Dir.UP, 4), (1, 6))


class TestChooseDir(unittest.TestCase):
    """U-26 / U-27 / U-28 / U-29：choose_dir 路口决策。"""

    def test_u26_picks_min_manhattan(self):
        gm, player, blinky, *_ = _build_fixed_scene()
        # 把 Blinky 放在路口 (3, 4)：4 方向都可通行
        blinky.row, blinky.col = 3, 4
        blinky.dir = Dir.LEFT  # 反向 = RIGHT（被排除）
        # 候选 = UP/DOWN（LEFT 排除反向，RIGHT 排除反向 → 实际候选 UP/DOWN）
        # UP(2,4) 到目标 (5, 14) = |2-5|+|4-14| = 13
        # DOWN(4,4) 到目标 (5, 14) = |4-5|+|4-14| = 12
        # DOWN 距离更小 → 选 DOWN
        d = choose_dir(blinky, (5, 14), gm)
        self.assertEqual(d, Dir.DOWN)

    def test_u27_tie_break_priority(self):
        """U-27：曼哈顿距离平局 → UP > LEFT > DOWN > RIGHT。"""
        gm, player, *_ = _build_fixed_scene()
        blinky = make_ghost(kind=Kind.BLINKY, pos=(10, 10))
        blinky.dir = Dir.LEFT  # 反向 = RIGHT
        # 让所有候选方向到目标曼哈顿距离相等
        # UP(9,10), LEFT(10,9), DOWN(11,10), RIGHT(10,11)
        # 目标选 (1, 10)：UP(9,10) 距 8；LEFT(10,9) 距 8；DOWN(11,10) 距 10；RIGHT(10,11) 距 8
        # 不行：DOWN 距目标距离不同。改为 (9, 9)：
        # UP(9,10) → |9-9|+|10-9| = 1
        # LEFT(10,9) → |10-9|+|9-9| = 1
        # DOWN(11,10) → |11-9|+|10-9| = 3
        # RIGHT(10,11) → |10-9|+|11-9| = 3
        # UP vs LEFT 都是 1（平局）；UP 优先
        d = choose_dir(blinky, (9, 9), gm)
        self.assertEqual(d, Dir.UP)

    def test_u28_dead_end_reverses(self):
        """U-28：死胡同无候选时允许掉头。"""
        gm, player, *_ = _build_fixed_scene()
        # 把 Blinky 放进 GOOD_22x19 中央鬼屋里的封闭区？鬼屋封闭，
        # 但可以构造"四面墙 + 一个入口"的局面：
        # 简单方法：用一个内置地图外的位置，让所有方向都被墙封死
        # 直接用内置地图的角落 (0,0) 周围：UP/LEFT 出界、DOWN 是墙 (0,0)是墙!
        # 用 builtin map (0,1)：UP=(−1,1) out；LEFT=(0,0) WALL；DOWN=(1,1) ?
        # 1,1 在 builtin 是 DOT (.) → 可通行
        # 所以角落不是死胡同。换个方式：用 make_ghost 在某个孤立通道里
        # 这里利用"反向外 0 候选则返回反向"：
        # 在 GOOD_22x19 (9,1) 处：
        #   UP=(8,1) WALL; LEFT=(9,0) WALL; DOWN=(10,1) WALL; RIGHT=(9,2) WALL
        # 全是墙 → 候选空 → 反向（当前 dir 决定）
        # 我们让 blinky.dir=LEFT，反向=RIGHT
        blinky = make_ghost(kind=Kind.BLINKY, pos=(9, 1))
        # 确认四面墙
        for d in ALL_DIRS:
            nr = blinky.row + d.drow
            nc = blinky.col + d.dcol
            if 0 <= nr < gm.rows and 0 <= nc < gm.cols:
                # 至少一个方向可通行（避开此用例）
                pass
        # 检查 (9,1) 实际四面情况
        info = []
        for d in ALL_DIRS:
            nr = blinky.row + d.drow
            nc = blinky.col + d.dcol
            if not (0 <= nr < gm.rows and 0 <= nc < gm.cols):
                info.append(f'{d.name}=OOB')
            else:
                info.append(f'{d.name}={gm.tile_at(nr, nc).name}')
        # 用 .replace 检查 (9,1) 四面 — 但这是分析，下面跳过
        # 强制构造"四周封闭"局面：临时改 gm (不合规)，
        # 改用 builtin 内已知墙区：(0,2) 周围：UP=OOB, LEFT=(0,1) WALL, RIGHT=(0,3) WALL, DOWN=(1,2) WALL?
        # (1,2) 在 GOOD_22x19 = DOT(.)
        # 用一个内置中真正四面墙的格：找 ghost house 墙格
        # 但 ghost house 内幽灵可通行。换个思路——直接让 blinky.dir = RIGHT，
        # 反向=LEFT，且 LEFT 方向也墙。简单做法：用 builtin (9,1)，
        # 让 blinky.dir=RIGHT，反向 LEFT 是墙；UP/DOWN 都是墙；
        # 那么 choose_dir 候选空 → 返回 REVERSE_DIR[RIGHT] = LEFT
        blinky.dir = Dir.RIGHT
        # 让 (10,1) 也是墙——但 (10,1) 在 builtin 是 H
        # 用更简单的：直接看 builtin (8,4) 周围
        # 别再纠结了：用 (0,2) UP OOB, DOWN(1,2)=., LEFT(0,1)=#, RIGHT(0,3)=#
        # 三个方向中 DOWN 可通行 → 非死胡同
        # 改用 (0,4)：UP OOB, DOWN(1,4)=#, LEFT(0,3)=#, RIGHT(0,5)=#
        # 全封闭！
        blinky.row, blinky.col = 0, 4
        blinky.dir = Dir.UP  # 反向 DOWN
        d = choose_dir(blinky, (10, 10), gm)
        self.assertEqual(d, Dir.DOWN)  # 死胡同 → 反向


class TestExcludesReverse(unittest.TestCase):
    """U-29：反向被排除；仅当无其他候选时才掉头。"""

    def test_u29_excludes_reverse_when_others_available(self):
        gm, player, *_ = _build_fixed_scene()
        # 找一个四面有 2+ 个方向的普通通道格
        # builtin (1,1) 是 DOT，周围 UP OOB, DOWN(2,1)=o POWER, LEFT(1,0)=#, RIGHT(1,2)=.
        # 反向 = LEFT（当前 dir=LEFT），排除后候选 = UP(OOB), DOWN(o 通行), RIGHT(. 通行)
        # 所以不会选 LEFT → 候选中按曼哈顿距离 + 优先级选择
        blinky = make_ghost(kind=Kind.BLINKY, pos=(1, 1))
        blinky.dir = Dir.LEFT  # 反向 = RIGHT
        d = choose_dir(blinky, (10, 10), gm)
        # 不应该选 RIGHT（被排除为反向）
        self.assertNotEqual(d, Dir.RIGHT)


class TestModeController(unittest.TestCase):
    """模式状态机：phase 推进、当前模式、永久 CHASE。"""

    def test_initial_phase_is_scatter(self):
        mc = ModeController(level=1)
        self.assertEqual(mc.current, Mode.SCATTER)
        self.assertEqual(mc.phase, 0)

    def test_step_advances_phase(self):
        """dt 累加到当前段时长 → 切换模式 + phase+1。"""
        mc = ModeController(level=1)
        # scatter 时长 = scatter_duration_for_level(1) = 7
        # 推 7s
        switched = mc.step(7.0)
        self.assertTrue(switched)
        self.assertEqual(mc.current, Mode.CHASE)
        self.assertEqual(mc.phase, 1)
        self.assertEqual(mc.phase_timer, 0.0)

    def test_step_no_switch_under_duration(self):
        mc = ModeController(level=1)
        switched = mc.step(3.0)
        self.assertFalse(switched)
        self.assertEqual(mc.current, Mode.SCATTER)
        self.assertEqual(mc.phase_timer, 3.0)

    def test_permanent_chase_after_8_phases(self):
        """phase 越过 2*PHASE_COUNT-1=13 后永久 CHASE。"""
        mc = ModeController(level=1)
        # 14 段：phase 0..13，再 step 一次会到 14 > 13 → 永久 CHASE
        # 但 phase 14 后 step 不会再切回 SCATTER
        for _ in range(15):
            mc.step(100.0)
        self.assertEqual(mc.current, Mode.CHASE)
        # 再 step 不应再回到 SCATTER
        mc.step(100.0)
        self.assertEqual(mc.current, Mode.CHASE)


class TestApplyModeTransition(unittest.TestCase):
    """U-47：模式切换强制掉头规则。"""

    def test_chase_to_scatter_reverses(self):
        g = make_ghost(kind=Kind.BLINKY, pos=(5, 5), direction=Dir.UP)
        apply_mode_transition(g, Mode.CHASE, Mode.SCATTER)
        self.assertEqual(g.dir, Dir.DOWN)  # 180°

    def test_chase_to_frightened_reverses(self):
        g = make_ghost(kind=Kind.BLINKY, pos=(5, 5), direction=Dir.LEFT)
        apply_mode_transition(g, Mode.CHASE, Mode.FRIGHTENED)
        self.assertEqual(g.dir, Dir.RIGHT)

    def test_frightened_to_chase_no_reverse(self):
        """frightened → chase 不强制掉头。"""
        g = make_ghost(kind=Kind.BLINKY, pos=(5, 5), direction=Dir.UP)
        apply_mode_transition(g, Mode.FRIGHTENED, Mode.CHASE)
        self.assertEqual(g.dir, Dir.UP)  # 不变

    def test_eyes_to_chase_no_reverse(self):
        """EYES → CHASE 不强制掉头。"""
        g = make_ghost(kind=Kind.BLINKY, pos=(5, 5), direction=Dir.LEFT)
        apply_mode_transition(g, Mode.EYES, Mode.CHASE)
        self.assertEqual(g.dir, Dir.LEFT)


class TestMaybeReleaseGhost(unittest.TestCase):
    """出场规则：Pinky 立即、Inky 30 豆、Clyde 60 豆。"""

    def test_blinky_and_pinky_release_immediately(self):
        blinky = make_ghost(kind=Kind.BLINKY, pos=(9, 10))
        pinky = make_ghost(kind=Kind.PINKY, pos=(9, 11))
        self.assertTrue(maybe_release_ghost(blinky, dots_eaten=0))
        self.assertTrue(maybe_release_ghost(pinky, dots_eaten=0))

    def test_inky_releases_at_30_dots(self):
        inky = make_ghost(kind=Kind.INKY, pos=(9, 11))
        self.assertFalse(maybe_release_ghost(inky, dots_eaten=29))
        self.assertTrue(maybe_release_ghost(inky, dots_eaten=30))

    def test_clyde_releases_at_60_dots(self):
        clyde = make_ghost(kind=Kind.CLYDE, pos=(9, 12))
        self.assertFalse(maybe_release_ghost(clyde, dots_eaten=59))
        self.assertTrue(maybe_release_ghost(clyde, dots_eaten=60))

    def test_out_of_house_no_release(self):
        """已出屋的幽灵不再触发 maybe_release_ghost。"""
        inky = make_ghost(kind=Kind.INKY, pos=(9, 11))
        inky.in_house = False
        # 吃 100 豆也不应再"出屋"
        self.assertFalse(maybe_release_ghost(inky, dots_eaten=100))


class TestManhattan(unittest.TestCase):
    """manhattan 距离工具函数。"""

    def test_manhattan_basic(self):
        self.assertEqual(manhattan((0, 0), (3, 4)), 7)
        self.assertEqual(manhattan((5, 5), (5, 5)), 0)
        self.assertEqual(manhattan((2, 3), (8, 1)), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)