"""game.py 单测：对局闭环（吃豆/能量/反击/扣命/过关/结算/暂停）。

测试方案映射（核心 P0 + 部分 P1/P2）：
- T-GAME-01 吃豆 +10
- T-GAME-02 能量豆 +50 + FRIGHTENED
- T-GAME-03 吃幽灵 +200
- T-GAME-04 连吃链 200/400/800/1600 封顶
- T-GAME-05 能量限时恢复
- T-GAME-06 扣命流程
- T-GAME-07 GAME_OVER
- T-GAME-08 过关推进
- T-GAME-09 撞墙不穿
- T-GAME-10 幽灵两态碰撞
- T-AI-13 双幽灵同格
- T-AI-14 幽灵互不冲突
- T-GAME-15 保护期
- T-GAME-17 暂停相位补偿
- T-GAME-18 连吃 ≥5 封顶
- T-UI-01 暂停
- T-FR12-01 2/3 幽灵
- T-FR13-01 扣命后幽灵重置
- T-FR17-01 结算
- T-FR08-01 连闯关
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401

from pacman.config import (
    Config, Dir, Kind, Mode,
    GHOST_CHAIN_SCORES, PROTECTION_SECONDS, DOT_SCORE, POWER_SCORE,
)
from pacman.game import FinalScore, Game, Status
from pacman.map import Tile

from tests.fixtures import build_game, frozen_clock, make_ghost, make_player


class TestDotEating(unittest.TestCase):
    """T-GAME-01：吃豆 +10、豆消失。"""

    def test_dot_score(self):
        g = build_game()
        # 把玩家放到豆格 (12, 8) 上，再走一步到 (12, 7) 触发吃豆
        g.player.set_pos((12, 8))
        g.player.dir = Dir.LEFT
        g.tick()
        # 玩家 (12, 7) 应该是 DOT，吃到 → +10
        self.assertEqual(g.score, 10)
        self.assertEqual(g.dots_left, 215)
        # tile (12, 7) 变 EMPTY
        self.assertEqual(g.tiles[12][7], Tile.EMPTY)


class TestPowerPellet(unittest.TestCase):
    """T-GAME-02/03/04/05/18：能量豆与反击 + 连吃链 + 限时恢复 + 封顶。"""

    def _eat_power_and_check(self):
        """辅助：让玩家吃一颗能量豆（位于 (2, 1)），断言 power_timer 与 ghost 状态。"""
        g = build_game()
        # 把玩家放到能量豆格 (2, 1)
        g.player.set_pos((2, 1))
        g.player.dir = Dir.UP
        # 触发一次 _handle_dot_eating（player.move 不会触发，靠 tick）
        # player (2,1) 朝 UP → next pos (1,1) 可通行 → 走一步到 (1,1)
        # 先手动触发 _handle_dot_eating
        g._handle_dot_eating()
        return g

    def test_power_pellet_triggers_frightened(self):
        """T-GAME-02：吃能量豆 +50，全员 FRIGHTENED，power_timer 启动。"""
        g = self._eat_power_and_check()
        self.assertEqual(g.score, POWER_SCORE)
        self.assertGreater(g.power_timer, 0.0)
        # 全部幽灵进入 FRIGHTENED
        for ghost in g.ghosts:
            self.assertEqual(ghost.mode, Mode.FRIGHTENED)

    def test_eat_ghost_first(self):
        """T-GAME-03：吃第一个幽灵 +200。"""
        g = build_game()
        # 玩家到能量豆格
        g.player.set_pos((2, 1))
        g._handle_dot_eating()
        self.assertEqual(g.eaten_chain, 0)
        # 把一只幽灵（BLINKY）放到玩家同格
        ghost = g.ghosts[0]
        ghost.mode = Mode.FRIGHTENED
        ghost.set_pos(g.player.pos)
        # 触发碰撞
        g._handle_collisions()
        self.assertEqual(ghost.mode, Mode.EYES)
        self.assertEqual(g.score, POWER_SCORE + GHOST_CHAIN_SCORES[0])  # 50 + 200
        self.assertEqual(g.eaten_chain, 1)

    def test_chain_and_cap(self):
        """T-GAME-04：连吃链 + 封顶。"""
        g = build_game()
        # 吃能量豆
        g.player.set_pos((2, 1))
        g._handle_dot_eating()
        base = g.score
        # 依次吃 4 只幽灵
        for i, ghost in enumerate(g.ghosts):
            ghost.mode = Mode.FRIGHTENED
            ghost.set_pos(g.player.pos)
            g._handle_collisions()
            expected = GHOST_CHAIN_SCORES[min(i, 3)]
            self.assertEqual(g.score - base, sum(GHOST_CHAIN_SCORES[:i+1]),
                             f"after eating {i+1}, score delta wrong")

    def test_chain_cap_5(self):
        """T-GAME-18：连吃 ≥5 仍封顶 1600（实际上限 4 幽灵；验证 chain ≥4 恒 1600）。"""
        g = build_game()
        g.player.set_pos((2, 1))
        g._handle_dot_eating()
        # 模拟 chain=4 后再尝试（即使幽灵被吃成 EYES，再放一只 FRIGHTENED 同格）
        g.eaten_chain = 4
        ghost = make_ghost(Kind.BLINKY, g.player.pos, Dir.UP, level=1)
        ghost.mode = Mode.FRIGHTENED
        g.ghosts.append(ghost)
        before = g.score
        g._handle_collisions()
        # 第 5 只得分 = GHOST_CHAIN_SCORES[3] = 1600
        self.assertEqual(g.score - before, GHOST_CHAIN_SCORES[3])

    def test_two_ghosts_same_cell(self):
        """T-AI-13：两只 FRIGHTENED 幽灵同格 → 都变 EYES，按序 200/400。"""
        g = build_game()
        g.player.set_pos((2, 1))
        g._handle_dot_eating()
        g1 = g.ghosts[0]
        g2 = g.ghosts[1]
        g1.mode = Mode.FRIGHTENED
        g2.mode = Mode.FRIGHTENED
        g1.set_pos(g.player.pos)
        g2.set_pos(g.player.pos)
        g._handle_collisions()
        # 第一只被吃 +200（chain=1）
        # 第二只被吃 +400（chain=2）
        # 但代码只处理一次 tick 后第一只被吃
        # _handle_collisions 是单次碰撞循环：每只独立判定
        # 实际上同一 tick 两只都同格，第一次循环 g1 被吃，第二次循环 g2 被吃
        # eaten_chain 第二次会 +1
        self.assertEqual(g1.mode, Mode.EYES)
        self.assertEqual(g2.mode, Mode.EYES)
        # score: 50 + 200 + 400 = 650
        self.assertEqual(g.score, POWER_SCORE + 200 + 400)

    def test_power_timer_expires(self):
        """T-GAME-05：能量限时结束 → 幽灵恢复可伤害。"""
        clock, advance = frozen_clock(1000.0)
        g = build_game(clock=clock)
        g.player.set_pos((2, 1))
        g._handle_dot_eating()
        # 把一只幽灵设为 FRIGHTENED
        ghost = g.ghosts[0]
        ghost.mode = Mode.FRIGHTENED
        # 推 6s
        for _ in range(60):  # 60 × 0.1s
            advance(0.1)
            g.tick()
        # 限时结束 → 幽灵恢复
        for gg in g.ghosts:
            if gg.mode == Mode.FRIGHTENED:
                self.fail(f"ghost {gg.kind} still FRIGHTENED after 6s")


class TestLoseLife(unittest.TestCase):
    """T-GAME-06/07/15：扣命 + GAME_OVER + 保护期。"""

    def test_lose_life_reset(self):
        """T-GAME-06：扣命 -1 + 玩家回出生点 + 保护期。"""
        g = build_game()
        # 触发扣命：幽灵与玩家同格
        g.ghosts[0].set_pos(g.player.pos)
        lives_before = g.lives
        g._handle_collisions()
        self.assertEqual(g.lives, lives_before - 1)
        self.assertEqual(g.player.pos, g.gm.player_spawn)
        self.assertEqual(g.player.protection_timer, PROTECTION_SECONDS)

    def test_game_over(self):
        """T-GAME-07：命数 =1 时再次被撞 → GAME_OVER。"""
        g = build_game(config=Config(lives=1))
        g.ghosts[0].set_pos(g.player.pos)
        g._handle_collisions()
        self.assertEqual(g.status, Status.GAME_OVER)
        self.assertEqual(g.lives, 0)
        # final_score
        fs = g.final_score()
        self.assertIsInstance(fs, FinalScore)
        self.assertEqual(fs.level, 1)
        self.assertEqual(fs.score, 0)

    def test_protection_period(self):
        """T-GAME-15：保护期内不判定扣命。"""
        clock, advance = frozen_clock(1000.0)
        g = build_game(clock=clock)
        g.ghosts[0].set_pos(g.player.pos)
        # 设置保护期
        g.player.protection_timer = 2.0
        lives_before = g.lives
        g._handle_collisions()
        # 保护期 → 不扣命
        self.assertEqual(g.lives, lives_before)
        # 幽灵仍在 CHASE/SCATTER 态（没被吃）
        self.assertIn(g.ghosts[0].mode, [Mode.CHASE, Mode.SCATTER])

    def test_ghost_reset_after_lose_life(self):
        """T-FR13-01：扣命后全幽灵回鬼屋。"""
        g = build_game()
        g.ghosts[0].set_pos(g.player.pos)
        g._handle_collisions()
        # 全部幽灵应回到鬼屋（in_house=True 或位置在 house_cells）
        for ghost in g.ghosts:
            self.assertTrue(ghost.in_house or ghost.pos in g.gm.house_cells,
                            f"ghost {ghost.kind} not in house: {ghost.pos}")


class TestLevelClear(unittest.TestCase):
    """T-GAME-08 / T-FR08-01：过关推进 + 连闯关。"""

    def test_clear_dots_triggers_next_level(self):
        g = build_game()
        # 强制剩余豆子 = 0
        g.force_dots_left(0)
        g.tick()
        self.assertEqual(g.level, 2)
        # 新一关豆子全恢复
        self.assertEqual(g.dots_left, g.gm.initial_dots)

    def test_two_levels(self):
        """T-FR08-01：连续闯关。"""
        g = build_game()
        # 第 1 关强制清豆 → L2
        g.force_dots_left(0)
        g.tick()
        self.assertEqual(g.level, 2)
        # 第 2 关再清豆 → L3
        g.force_dots_left(0)
        g.tick()
        self.assertEqual(g.level, 3)


class TestMovement(unittest.TestCase):
    """T-GAME-09/10 / T-AI-14：移动 + 碰撞。"""

    def test_player_cannot_walk_wall(self):
        """T-GAME-09：玩家撞墙不穿。"""
        g = build_game()
        # 玩家在 (7, 8) 朝 UP，(6, 8) = WALL
        g.player.set_pos((7, 8))
        g.player.dir = Dir.UP
        before = g.player.pos
        g.tick()
        # 玩家无法进入墙（仍是 (7, 8)）
        self.assertEqual(g.player.pos, before)

    def test_player_cannot_enter_house_or_door(self):
        """U-32：鬼屋门/鬼屋对玩家均不可通行。"""
        g = build_game()
        for target in list(g.gm.door_cells)[:1] + list(g.gm.house_cells)[:1]:
            with self.subTest(target=target):
                self.assertFalse(g.gm.is_passable_for_player(*target))

    def test_chase_vs_frightened_same_cell(self):
        """T-GAME-10：幽灵两态碰撞分支正确。"""
        g = build_game()
        # CHASE 态同格 → 扣命
        g.ghosts[0].set_pos(g.player.pos)
        g.ghosts[0].mode = Mode.CHASE
        lives_before = g.lives
        g._handle_collisions()
        self.assertEqual(g.lives, lives_before - 1)
        # 重新构造场景
        g = build_game()
        g.player.set_pos((7, 8))  # 移开
        g.ghosts[0].set_pos(g.player.pos)
        g.ghosts[0].mode = Mode.FRIGHTENED
        score_before = g.score
        g._handle_collisions()
        # FRIGHTENED 态 → 吃幽灵
        self.assertGreater(g.score, score_before)
        self.assertEqual(g.ghosts[0].mode, Mode.EYES)

    def test_eyes_pass_through_player(self):
        """T-AI-14：EYES 状态不与玩家冲突。"""
        g = build_game()
        g.ghosts[0].set_pos(g.player.pos)
        g.ghosts[0].mode = Mode.EYES
        lives_before = g.lives
        g._handle_collisions()
        self.assertEqual(g.lives, lives_before)
        # 仍是 EYES
        self.assertEqual(g.ghosts[0].mode, Mode.EYES)


class TestPause(unittest.TestCase):
    """T-UI-01 / T-GAME-17：暂停 + 相位补偿。"""

    def test_pause_resume(self):
        g = build_game()
        g.pause()
        self.assertEqual(g.status, Status.PAUSED)
        g.resume()
        self.assertEqual(g.status, Status.PLAYING)

    def test_pause_does_not_advance(self):
        """暂停时不推进游戏状态。"""
        clock, advance = frozen_clock(1000.0)
        g = build_game(clock=clock)
        g.pause()
        advance(1.0)  # 暂停中推 1s
        g.tick()  # 不应推进
        # 玩家位置不变
        self.assertEqual(g.player.pos, g.gm.player_spawn)

    def test_pause_phase_compensation(self):
        """T-GAME-17：暂停后 power_timer 不漂移。"""
        clock, advance = frozen_clock(1000.0)
        g = build_game(clock=clock)
        # 吃能量豆
        g.player.set_pos((2, 1))
        g._handle_dot_eating()
        initial_power = g.power_timer
        # 推进 1s（非暂停）
        for _ in range(10):
            advance(0.1)
            g.tick()
        after_1s = g.power_timer
        # 暂停 10s
        g.pause()
        for _ in range(100):
            advance(0.1)
        g.resume()
        # 恢复后再推 0.1s
        advance(0.1)
        g.tick()
        # power_timer 应仅减少 1.1s（不含暂停的 10s）
        # 实际减少 ≈ 1.1s
        delta = initial_power - g.power_timer
        self.assertAlmostEqual(delta, 1.1, places=1)


class TestGhostCountConfig(unittest.TestCase):
    """T-FR12-01：2/3/4 幽灵数量。"""

    def test_two_ghosts(self):
        g = build_game(config=Config(ghosts=2))
        self.assertEqual(len(g.ghosts), 2)
        # BLINKY + PINKY
        self.assertEqual(g.ghosts[0].kind, Kind.BLINKY)
        self.assertEqual(g.ghosts[1].kind, Kind.PINKY)

    def test_three_ghosts(self):
        g = build_game(config=Config(ghosts=3))
        self.assertEqual(len(g.ghosts), 3)
        self.assertEqual(g.ghosts[2].kind, Kind.INKY)

    def test_four_ghosts(self):
        g = build_game(config=Config(ghosts=4))
        self.assertEqual(len(g.ghosts), 4)
        self.assertEqual(g.ghosts[3].kind, Kind.CLYDE)


if __name__ == "__main__":
    unittest.main()
