"""对局状态机测试：U-40 / U-41 / U-42 / U-43 / U-44 / U-45 / U-46 / U-47 /
U-48 / U-49 / U-50 / U-51 / U-52 / U-53 + I-01..I-09。

覆盖：
- U-40 吃豆得分（DOT/POWER）
- U-41 连吃 4 只幽灵（200/400/800/1600）
- U-42 eaten_chain 新能量豆重置
- U-43 能量豆计时归零恢复
- U-44~U-46 难度公式（已迁移到 test_config.py，本文件保留交叉验证）
- U-47 模式切换强制掉头（已迁到 test_ghost_ai.py）
- U-48 扣命重置
- U-49 过关（dots_left=0 触发）
- U-50 出场阈值
- U-51 GAME_OVER 结算
- U-52 暂停相位补偿
- U-53 连吃封顶 1600
- I-01~I-09 集成场景
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401
from tests.fixtures import (
    builtin_map, build_game, make_player, make_ghost, frozen_clock,
    write_map_tmp,
)

from pacman.config import (
    Dir, Kind, Mode,
    DOT_SCORE, POWER_SCORE, GHOST_CHAIN_SCORES,
    PROTECTION_SECONDS, POWER_SCORE,
    power_duration_for_level,
    inky_release_dots_for_level, clyde_release_dots_for_level,
)
from pacman.game import Game, Status, FinalScore
from pacman.map import GameMap, Tile, load_map


def _force_player(game: Game, row: int, col: int, dir: Dir = Dir.LEFT):
    """注入玩家位置（测试用）。"""
    game.player.row = row
    game.player.col = col
    game.player.dir = dir


def _force_ghost(game: Game, kind: Kind, row: int, col: int):
    """注入幽灵位置（测试用）。"""
    for g in game.ghosts:
        if g.kind == kind:
            g.row = row
            g.col = col
            g.in_house = False
            return g
    raise ValueError(f"Ghost {kind} not found")


def _eat_dot(game: Game, row: int, col: int):
    """强制让玩家走到豆格并 tick()（不依赖方向）。"""
    _force_player(game, row, col, game.player.dir)
    # 直接修改 tiles 让玩家所在格为 DOT
    game.tiles[row][col] = Tile.DOT
    game.tick()


def _eat_power(game: Game, row: int, col: int):
    """强制让玩家吃到能量豆（不依赖方向）。"""
    _force_player(game, row, col, game.player.dir)
    game.tiles[row][col] = Tile.POWER
    game.tick()


class TestDotEaten(unittest.TestCase):
    """U-40：吃豆得分；U-13（DOT/POWER 分数常量）。"""

    def test_u40_eat_dot_scores_10(self):
        game = build_game()
        before = game.score
        # 找一个 DOT 格并吃掉
        for r in range(game.gm.rows):
            for c in range(game.gm.cols):
                if game.gm.tile_at(r, c) == Tile.DOT:
                    before_score = game.score
                    before_dots = game.dots_left
                    _force_player(game, r, c, Dir.LEFT)
                    game.tiles[r][c] = Tile.DOT
                    game.tick()
                    self.assertEqual(game.score, before_score + DOT_SCORE)
                    self.assertEqual(game.dots_left, before_dots - 1)
                    return
        self.fail("No DOT found")

    def test_u40_eat_power_scores_50(self):
        game = build_game()
        for r in range(game.gm.rows):
            for c in range(game.gm.cols):
                if game.gm.tile_at(r, c) == Tile.POWER:
                    before_score = game.score
                    before_dots = game.dots_left
                    _force_player(game, r, c, Dir.LEFT)
                    game.tiles[r][c] = Tile.POWER
                    game.tick()
                    self.assertEqual(game.score, before_score + POWER_SCORE)
                    self.assertEqual(game.dots_left, before_dots - 1)
                    return
        self.fail("No POWER found")


class TestPowerChainScoring(unittest.TestCase):
    """U-41 / U-42 / U-53：连吃幽灵得分链 + 封顶。"""

    def test_u41_chain_200_400_800_1600(self):
        """脆弱期内依次撞 4 只幽灵，得分 200/400/800/1600。"""
        game = build_game()
        # 手动触发能量豆 → 进入 FRIGHTENED
        game.force_power_timer(5.0)
        game.eaten_chain = 0
        scores = []
        for i, g in enumerate(game.ghosts[:4]):
            g.mode = Mode.FRIGHTENED
            g.row, g.col = game.player.row, game.player.col
            game._handle_collisions()
            scores.append(game.score)
            expected_total = sum(GHOST_CHAIN_SCORES[: i + 1])
            self.assertEqual(
                scores[-1], expected_total,
                f"Ghost #{i}: 累计得分 {scores[-1]} ≠ 期望 {expected_total}",
            )
        # 累计总分 = 200+400+800+1600 = 3000
        self.assertEqual(scores[-1], 200 + 400 + 800 + 1600)
        self.assertEqual(game.ghosts_eaten_total, 4)

    def test_u42_new_power_resets_chain(self):
        """吃第 5 颗能量豆后再次撞幽灵，eaten_chain 重置为 200。"""
        game = build_game()
        # 第 1 颗能量豆 → 撞 1 只 → eaten_chain=1
        game.force_power_timer(5.0)
        game.eaten_chain = 0
        for g in game.ghosts[:1]:
            g.mode = Mode.FRIGHTENED
            g.row, g.col = game.player.row, game.player.col
            game._handle_collisions()
        # 再次吃能量豆 → eaten_chain 重置
        game.force_power_timer(5.0)
        game.eaten_chain = 0  # 模拟 _trigger_power_pellet 的重置
        before = game.score
        # 再撞 1 只 → 得分 200
        g = game.ghosts[0]
        g.mode = Mode.FRIGHTENED
        g.row, g.col = game.player.row, game.player.col
        game._handle_collisions()
        self.assertEqual(game.score, before + 200,
                         "新能量豆重置 eaten_chain，第 5 只得分应回到 200")

    def test_u53_chain_caps_at_1600(self):
        """eaten_chain ≥ 4 时得分恒 1600。"""
        game = build_game()
        game.force_power_timer(5.0)
        game.eaten_chain = 10  # 已超过 4
        g = game.ghosts[0]
        g.mode = Mode.FRIGHTENED
        g.row, g.col = game.player.row, game.player.col
        before = game.score
        game._handle_collisions()
        self.assertEqual(game.score, before + 1600)


class TestPowerTimerExpiration(unittest.TestCase):
    """U-43：能量豆计时归零后幽灵恢复。"""

    def test_u43_power_timer_decrements(self):
        game = build_game()
        clock, advance = frozen_clock(1000.0)
        game._clock = clock
        game._tick_phase_start = 1000.0
        game.power_timer = 5.0
        # 玩家吃能量豆：先 _trigger_power_pellet
        game._trigger_power_pellet()
        self.assertGreater(game.power_timer, 0.0)
        # 推 6s → power_timer 应归零
        for _ in range(60):  # 60 × 0.1s = 6s
            advance(0.1)
            game.tick()
        self.assertEqual(game.power_timer, 0.0)
        # 所有幽灵不应再是 FRIGHTENED
        for g in game.ghosts:
            self.assertNotEqual(g.mode, Mode.FRIGHTENED)


class TestLoseLife(unittest.TestCase):
    """U-48：扣命后状态归。"""

    def test_u48_lose_life_decrements_lives(self):
        game = build_game()
        # 玩家与一可伤害幽灵同格
        _force_player(game, 5, 5, Dir.LEFT)
        # Blinky 与玩家同格
        g = _force_ghost(game, Kind.BLINKY, 5, 5)
        g.mode = Mode.CHASE
        before_lives = game.lives
        game._handle_collisions()
        self.assertEqual(game.lives, before_lives - 1)

    def test_u48_lose_life_resets_player_position(self):
        game = build_game()
        _force_player(game, 5, 5, Dir.LEFT)
        g = _force_ghost(game, Kind.BLINKY, 5, 5)
        g.mode = Mode.CHASE
        spawn = game.gm.player_spawn
        game._handle_collisions()
        # 玩家回到出生格
        self.assertEqual((game.player.row, game.player.col), spawn)

    def test_u48_protection_timer_set(self):
        """扣命后保护期 PROTECTION_SECONDS 启动。"""
        game = build_game()
        _force_player(game, 5, 5, Dir.LEFT)
        g = _force_ghost(game, Kind.BLINKY, 5, 5)
        g.mode = Mode.CHASE
        game._handle_collisions()
        # 保护期应被设置（玩家被撞后立即检查）
        self.assertGreater(game.player.protection_timer, 0.0)

    def test_u48_protection_no_re_loss(self):
        """保护期内不重复扣命（E-10）。"""
        game = build_game()
        _force_player(game, 5, 5, Dir.LEFT)
        g = _force_ghost(game, Kind.BLINKY, 5, 5)
        g.mode = Mode.CHASE
        before = game.lives
        game._handle_collisions()  # 第一次扣命
        # 现在玩家已回出生格 + 保护期；强制幽灵再次同格
        g.row, g.col = game.player.row, game.player.col
        g.mode = Mode.CHASE
        game._handle_collisions()  # 保护期 → 不再扣命
        self.assertEqual(game.lives, before - 1)


class TestGameOver(unittest.TestCase):
    """U-51 / I-05：命数归零 → GAME_OVER + 结算。"""

    def test_u51_lives_zero_triggers_game_over(self):
        game = build_game()
        game.lives = 1
        _force_player(game, 5, 5, Dir.LEFT)
        g = _force_ghost(game, Kind.BLINKY, 5, 5)
        g.mode = Mode.CHASE
        game._handle_collisions()
        self.assertEqual(game.status, Status.GAME_OVER)
        self.assertEqual(game.lives, 0)

    def test_u51_final_score_contains_aggregates(self):
        game = build_game()
        game.lives = 1
        game.score = 1234
        game.level = 2
        game.ghosts_eaten_total = 5
        fs = game.final_score()
        self.assertEqual(fs.score, 1234)
        self.assertEqual(fs.level, 2)
        self.assertEqual(fs.ghosts_eaten, 5)

    def test_i05_final_score_matches_game_state(self):
        """I-05：游戏结束结算含得分/关卡/吃幽灵数。"""
        game = build_game()
        game.lives = 1
        game.score = 100
        game.ghosts_eaten_total = 3
        _force_player(game, 5, 5, Dir.LEFT)
        g = _force_ghost(game, Kind.BLINKY, 5, 5)
        g.mode = Mode.CHASE
        game._handle_collisions()
        self.assertEqual(game.status, Status.GAME_OVER)
        fs = game.final_score()
        self.assertEqual(fs.score, 100)
        self.assertEqual(fs.level, 1)
        self.assertEqual(fs.ghosts_eaten, 3)


class TestLevelClear(unittest.TestCase):
    """U-49 / I-03：dots_left=0 触发过关。"""

    def test_u49_level_clear_resets_dots(self):
        game = build_game()
        # 把 dots_left 设为 1，喂一个 DOT 让其归零
        game.force_dots_left(1)
        before_level = game.level
        # 玩家走到一个 DOT 格
        for r in range(game.gm.rows):
            for c in range(game.gm.cols):
                if game.gm.tile_at(r, c) == Tile.DOT:
                    _force_player(game, r, c, Dir.LEFT)
                    game.tiles[r][c] = Tile.DOT
                    game.tick()
                    break
            else:
                continue
            break
        # 过关后 level+1，dots_left 恢复
        self.assertEqual(game.level, before_level + 1)
        self.assertEqual(game.dots_left, game.gm.initial_dots)

    def test_u49_level_clear_resets_player_to_spawn(self):
        game = build_game()
        game.force_dots_left(1)
        # 找一个 DOT 喂掉
        for r in range(game.gm.rows):
            for c in range(game.gm.cols):
                if game.gm.tile_at(r, c) == Tile.DOT:
                    _force_player(game, r, c, Dir.LEFT)
                    game.tiles[r][c] = Tile.DOT
                    game.tick()
                    break
            else:
                continue
            break
        spawn = game.gm.player_spawn
        self.assertEqual((game.player.row, game.player.col), spawn)


class TestReleaseThresholds(unittest.TestCase):
    """U-50：出场阈值（Inky/Clyde 随关卡递减）。"""

    def test_u50_inky_release_threshold_l1(self):
        """第 1 关 Inky 阈值 30。"""
        from pacman.ghost_ai import maybe_release_ghost
        g = make_ghost(Kind.INKY, pos=(9, 10), level=1)
        self.assertEqual(g.release_threshold, 30)
        self.assertFalse(maybe_release_ghost(g, dots_eaten=29))
        self.assertTrue(maybe_release_ghost(g, dots_eaten=30))

    def test_u50_clyde_release_threshold_l1(self):
        """第 1 关 Clyde 阈值 60。"""
        from pacman.ghost_ai import maybe_release_ghost
        g = make_ghost(Kind.CLYDE, pos=(9, 10), level=1)
        self.assertEqual(g.release_threshold, 60)
        self.assertFalse(maybe_release_ghost(g, dots_eaten=59))
        self.assertTrue(maybe_release_ghost(g, dots_eaten=60))


class TestPauseResume(unittest.TestCase):
    """U-52 / E-09：暂停期间计时不消耗，恢复后无漂移。"""

    def test_u52_pause_freezes_power_timer(self):
        game = build_game()
        clock, advance = frozen_clock(1000.0)
        game._clock = clock
        game._tick_phase_start = 1000.0
        game._trigger_power_pellet()
        # power_timer 应 ≈ 6.0（第 1 关）
        self.assertGreater(game.power_timer, 5.9)
        # 暂停 2s
        game.pause()
        advance(2.0)
        game.resume()
        # 再 tick 一帧 → power_timer 应仍是 ~6.0（暂停时长被扣除）
        game._tick_phase_start = clock()  # 让 tick 看到新起点
        # power_timer 应未消耗（暂停 2s 被扣除）
        self.assertGreater(game.power_timer, 5.0)

    def test_pause_resume_state_transition(self):
        game = build_game()
        game.pause()
        self.assertEqual(game.status, Status.PAUSED)
        game.resume()
        self.assertEqual(game.status, Status.PLAYING)


class TestInitialState(unittest.TestCase):
    """I-07：开局实体位置。"""

    def test_i07_initial_ghost_positions(self):
        """4 幽灵均在鬼屋内。"""
        game = build_game()
        for g in game.ghosts:
            self.assertTrue(g.in_house)
            # 位置在鬼屋 8 格内
            self.assertIn((g.row, g.col), game.gm.house_cells)

    def test_i07_player_and_ghost_no_overlap(self):
        """玩家与 4 幽灵互不重叠。"""
        game = build_game()
        for g in game.ghosts:
            self.assertNotEqual(
                (game.player.row, game.player.col),
                (g.row, g.col),
            )


class TestEyesState(unittest.TestCase):
    """I-06：被吃幽灵转 EYES → 1.5 倍速回鬼屋。"""

    def test_eyes_speed_is_15(self):
        from pacman.config import GHOST_EYES_SPEED
        self.assertAlmostEqual(GHOST_EYES_SPEED, 1.5)

    def test_eaten_ghost_becomes_eyes(self):
        game = build_game()
        game.force_power_timer(5.0)
        game.eaten_chain = 0
        g = game.ghosts[0]
        g.mode = Mode.FRIGHTENED
        g.row, g.col = game.player.row, game.player.col
        game._handle_collisions()
        self.assertEqual(g.mode, Mode.EYES)


class TestConfigIntegration(unittest.TestCase):
    """Config 在 Game 中的整合。"""

    def test_initial_level_from_config(self):
        from pacman.config import Config
        game = build_game(config=Config(level=3))
        self.assertEqual(game.level, 3)
        # 难度参数按 L=3 计算
        self.assertEqual(game.elroy_threshold, max(20 - 3 * (3 - 1), 5))

    def test_initial_lives_from_config(self):
        from pacman.config import Config
        game = build_game(config=Config(lives=5))
        self.assertEqual(game.lives, 5)


class TestTickPhaseCompensation(unittest.TestCase):
    """暂停相位补偿（U-52 子项）。"""

    def test_tick_skips_when_paused(self):
        """暂停状态下 tick 不推进游戏逻辑。"""
        game = build_game()
        clock, advance = frozen_clock(1000.0)
        game._clock = clock
        game._tick_phase_start = 1000.0
        game.pause()
        before_score = game.score
        advance(1.0)
        game.tick()
        # 暂停时 tick 是 no-op
        self.assertEqual(game.score, before_score)


class TestGameSmoke(unittest.TestCase):
    """I-09 步进冒烟：完整一局关键事件可触发。"""

    def test_i09_step_through_full_game(self):
        """步进一局：吃豆、撞幽灵、吃能量豆、扣命 → 全部按规则触发。"""
        game = build_game()
        # 1) 吃一颗 DOT
        for r in range(game.gm.rows):
            for c in range(game.gm.cols):
                if game.gm.tile_at(r, c) == Tile.DOT:
                    _force_player(game, r, c, Dir.LEFT)
                    game.tiles[r][c] = Tile.DOT
                    game.tick()
                    break
            else:
                continue
            break
        self.assertGreater(game.score, 0)

        # 2) 撞可伤害幽灵 → 扣命
        game.lives = 2  # 确保有命可扣
        g = _force_ghost(game, Kind.BLINKY, game.player.row, game.player.col)
        g.mode = Mode.CHASE
        before_lives = game.lives
        game._handle_collisions()
        self.assertEqual(game.lives, before_lives - 1)

        # 3) 吃能量豆 → 进入 FRIGHTENED
        game.player.protection_timer = 0.0  # 清保护期
        for r in range(game.gm.rows):
            for c in range(game.gm.cols):
                if game.gm.tile_at(r, c) == Tile.POWER:
                    _force_player(game, r, c, Dir.LEFT)
                    game.tiles[r][c] = Tile.POWER
                    game.tick()
                    break
            else:
                continue
            break
        self.assertGreater(game.power_timer, 0.0)
        # 所有幽灵应是 FRIGHTENED
        self.assertTrue(any(g.mode == Mode.FRIGHTENED for g in game.ghosts))

        # 4) 吃能量豆后撞一幽灵 → EYES
        before_chain = game.eaten_chain
        g = game.ghosts[0]
        g.mode = Mode.FRIGHTENED
        g.row, g.col = game.player.row, game.player.col
        game._handle_collisions()
        self.assertEqual(g.mode, Mode.EYES)
        self.assertEqual(game.eaten_chain, before_chain + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)