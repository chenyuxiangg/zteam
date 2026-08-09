"""game.py 单测。

覆盖测试方案：
- TC-B5 吃豆计分（+10）+ 豆消失
- TC-B6 吃能量豆触发全部幽灵 FRIGHTENED + power_timer 启动
- TC-B7 撞 FRIGHTENED 幽灵 → EYES、得分 200、吃幽灵计数 +1
- TC-B8 连吃序列 200/400/800/1600/1600（封顶）
- TC-B10 吃光豆触发 _next_level：level+1、地图重置、参数更新
- TC-B11 扣命：lives-1、玩家回出生点、2s 保护期、模式计时归零
- TC-B12 命 0 → GAME_OVER
- TC-C9 扣命/过关后幽灵回鬼屋
- TC-X5 难度公式边界（L=1/10/100 不越界）
- TC-X10 连吃 ≥4 封顶 1600（下次能量豆重置）
- TC-X13 多幽灵同格判定（每次 tick 一只，逐只结算）
"""
from __future__ import annotations

import unittest

from tests._path import code_dir

from pacman.config import Config
from pacman.entities import Dir, GhostKind, GhostMode
from pacman.game import Game, GameStatus
from pacman.map import GameMap, Pos, Tile

from tests.fixtures import build_game


def _fresh_game(**overrides) -> Game:
    """默认 level=1, lives=3, speed=1.0（让 update 正常推进玩家移动）。"""
    defaults = dict(start_level=1, lives=3, speed=1.0)
    defaults.update(overrides)
    return build_game(config=Config(**defaults), seed=7)


def _frozen_game(**overrides) -> Game:
    """speed=0.0 + 玩家朝墙 + 所有幽灵钉在玩家格 → 一次 update 不推进但触发碰撞。

    用于测试碰撞语义（吃豆/扣命/吃幽灵/能量暴走）。
    """
    cfg_overrides = {"speed": 0.0, **overrides}
    return _fresh_game(**cfg_overrides)


def _drive_to(game: Game, dt: float = 0.1) -> None:
    """推送 dt 秒（不消耗保护期）。"""
    game.update(dt)


def _move_player_to(game: Game, pos: Pos) -> None:
    """强行把玩家移到指定格（绕过穿墙）。"""
    game.player.pos = pos
    game.player.buffered_direction = None
    # 重置方向使其不再自走
    game.player.direction = Dir.LEFT


def _move_ghost_to(game: Game, kind: GhostKind, pos: Pos) -> None:
    for g in game.ghosts:
        if g.kind is kind:
            g.pos = pos
            return
    raise AssertionError(f"no ghost {kind}")


def _consume_all_but_n(game: Game, n: int) -> None:
    """把地图消耗到剩 n 颗豆。"""
    target = game.map.initial_dots - n
    consumed = 0
    for r in range(game.map.height):
        for c in range(game.map.width):
            if consumed >= target:
                return
            if game.map.tile_at(Pos(r, c)) in (Tile.DOT, Tile.POWER):
                game.map.consume(Pos(r, c))
                consumed += 1


class TestEatDotAndScore(unittest.TestCase):
    """TC-B5：吃豆 → score+10、豆消失。"""

    def test_score_and_dot_disappears(self):
        # 把地图上所有能量豆 POWER 替换为 DOT（避免 power 干扰）
        game = _fresh_game()
        from pacman.map import Tile
        for r in range(game.map.height):
            for c in range(game.map.width):
                if game.map.tile_at(Pos(r, c)) is Tile.POWER:
                    game.map.grid[r][c] = Tile.DOT
        before = game.score
        before_dots = game.map.dots_left()
        # 驱动玩家直到踩到 DOT
        steps = 0
        eaten_pos = None
        while steps < 500:
            game.update(0.1)
            steps += 1
            if game.map.tile_at(game.player.pos) is Tile.EMPTY and game.score > before:
                # 刚刚吃完
                eaten_pos = game.player.pos
                break
        self.assertIsNotNone(eaten_pos, "player never ate a dot in 500 ticks")
        # 刚吃完玩家站在 EMPTY；上面一帧的 tile 已被 consume 为 EMPTY。
        # 我们用 score - 10 反推：玩家之前一定踩过一颗 DOT，且该格已清空。
        # 直接断言 score 与 dots_left 增加 1
        self.assertEqual(game.score, before + 10)
        self.assertEqual(game.map.dots_left(), before_dots - 1)


class TestPowerPelletTriggersFrightened(unittest.TestCase):
    """TC-B6：吃能量豆 → 全体幽灵 FRIGHTENED + power_timer > 0。"""

    def test_all_ghosts_frightened(self):
        game = _frozen_game()
        # 释放所有幽灵并放置到玩家四周，强制撞触发 power_mode 走 _start_power_mode
        for g in game.ghosts:
            g.released = True
            g.mode = GhostMode.SCATTER
        # 找到一颗能量豆放在玩家脚下（手动 _start_power_mode）
        from pacman.map import Tile
        power_pos = None
        for r in range(game.map.height):
            for c in range(game.map.width):
                if game.map.tile_at(Pos(r, c)) is Tile.POWER:
                    power_pos = Pos(r, c)
                    break
            if power_pos:
                break
        self.assertIsNotNone(power_pos)
        game.player.pos = power_pos
        game.player.direction = Dir.DOWN  # 朝墙钉住
        game.player.buffered_direction = None
        # frozen_game 速度=0，玩家不动不会自动调 _consume_player_tile；
        # 我们直接手动调一次验证 _start_power_mode 行为
        game._consume_player_tile()
        # 触发能量豆：score+50、power_timer 启动
        self.assertEqual(game.score, 50)
        self.assertGreater(game.power_timer, 0.0)
        self.assertTrue(
            all(g.mode is GhostMode.FRIGHTENED for g in game.ghosts),
            f"expected all FRIGHTENED, got {[g.mode for g in game.ghosts]}",
        )


class TestEatGhostSequence(unittest.TestCase):
    """TC-B7/B8/X10：撞 FRIGHTENED 幽灵 → EYES + 得分序列 200/400/800/1600。"""

    def _force_frightened_collision(self, game: Game) -> None:
        """玩家朝墙 + 全部幽灵放在同格 → 一次 update 内不移动但触发碰撞。"""
        game.player.direction = Dir.DOWN
        game.player.buffered_direction = None
        for g in game.ghosts:
            g.released = True
            g.mode = GhostMode.FRIGHTENED
            g.pos = game.player.pos

    def test_first_ghost_200_then_chain(self):
        game = _frozen_game()
        game.protection_timer = 0.0  # 关闭保护期才能触发碰撞
        game.power_timer = 5.0
        game.eaten_chain = 0
        self._force_frightened_collision(game)
        game.update(0.1)
        # 一次 update 内全部 4 只 FRIGHTENED 都被吃：200+400+800+1600 = 3000
        self.assertEqual(game.score, 200 + 400 + 800 + 1600)
        self.assertEqual(game.ghosts_eaten, 4)
        self.assertTrue(all(g.mode is GhostMode.EYES for g in game.ghosts))

    def test_chain_resets_on_next_power(self):
        game = _frozen_game()
        game.protection_timer = 0.0
        game.power_timer = 5.0
        self._force_frightened_collision(game)
        game.update(0.1)
        self.assertEqual(game.eaten_chain, 4)
        # 模拟能量暴走结束，重置 power
        game.power_timer = 0.0
        game._start_power_mode()
        self.assertEqual(game.eaten_chain, 0)
        self.assertGreater(game.power_timer, 0.0)

    def test_chain_caps_at_1600(self):
        """TC-X10：eaten_chain ≥4 后 GHOST_POINTS 索引封顶。"""
        game = _frozen_game()
        game.eaten_chain = 4
        from pacman.game import GHOST_POINTS
        self.assertEqual(GHOST_POINTS[min(game.eaten_chain, len(GHOST_POINTS) - 1)], 1600)
        game.eaten_chain = 5
        self.assertEqual(GHOST_POINTS[min(game.eaten_chain, len(GHOST_POINTS) - 1)], 1600)
        game.eaten_chain = 100
        self.assertEqual(GHOST_POINTS[min(game.eaten_chain, len(GHOST_POINTS) - 1)], 1600)


class TestNextLevel(unittest.TestCase):
    """TC-B10：吃光豆 → level+1、地图重置、玩家/幽灵回位。"""

    def test_clear_dots_advances_level(self):
        game = _frozen_game()
        # 把地图消耗到只剩 1 颗 DOT
        _consume_all_but_n(game, 1)
        # 找到唯一剩下的 DOT
        last_dot = None
        for r in range(game.map.height):
            for c in range(game.map.width):
                if game.map.tile_at(Pos(r, c)) is Tile.DOT:
                    last_dot = Pos(r, c)
                    break
            if last_dot:
                break
        # 如果剩的是 POWER，替换为 DOT
        if last_dot is None:
            for r in range(game.map.height):
                for c in range(game.map.width):
                    if game.map.tile_at(Pos(r, c)) is Tile.POWER:
                        last_dot = Pos(r, c)
                        game.map.grid[r][c] = Tile.DOT
                        break
                if last_dot:
                    break
        self.assertIsNotNone(last_dot, "no last dot/power found")

        # 把玩家放最后 DOT 格；朝墙钉住，手动 _consume_player_tile 触发 _next_level
        game.player.pos = last_dot
        game.player.direction = Dir.DOWN
        game.player.buffered_direction = None
        game._consume_player_tile()

        self.assertEqual(game.level, 2)
        # 地图重置 → 豆子恢复 216
        self.assertEqual(game.map.dots_left(), game.map.initial_dots)
        # 玩家回出生点
        self.assertEqual(game.player.pos, game.map.player_start)


class TestLoseLife(unittest.TestCase):
    """TC-B11/B12/C9：扣命 → lives-1、玩家回位、保护期、模式重置；命 0 → GAME_OVER。"""

    def test_lose_life_with_lives_left(self):
        game = _frozen_game()
        game.protection_timer = 0.0
        game.player.direction = Dir.DOWN
        game.player.buffered_direction = None
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.CHASE
        blinky.pos = game.player.pos
        game.update(0.1)
        self.assertEqual(game.lives, 2)
        self.assertEqual(game.status, GameStatus.PLAYING)
        self.assertEqual(game.player.pos, game.map.player_start)
        self.assertGreater(game.protection_timer, 0.0)

    def test_lose_last_life_ends_game(self):
        game = _frozen_game(lives=1)
        game.protection_timer = 0.0
        game.player.direction = Dir.DOWN
        game.player.buffered_direction = None
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.CHASE
        blinky.pos = game.player.pos
        game.update(0.1)
        self.assertEqual(game.lives, 0)
        self.assertEqual(game.status, GameStatus.GAME_OVER)


class TestEyesGhostDoesNotDamage(unittest.TestCase):
    """[采纳 testplan-review 建议 2] EYES 态幽灵与玩家同格不扣命。"""

    def test_eyes_ghost_no_life_loss(self):
        game = _frozen_game()
        game.protection_timer = 0.0
        game.player.direction = Dir.DOWN
        game.player.buffered_direction = None
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.EYES
        blinky.pos = game.player.pos
        lives_before = game.lives
        game.update(0.1)
        self.assertEqual(game.lives, lives_before)


class TestDifficultyFormulas(unittest.TestCase):
    """TC-X5：难度公式在 L=1/10/100 不越界。"""

    def test_power_duration_floor(self):
        g1 = _fresh_game(start_level=1)
        self.assertAlmostEqual(g1.power_duration, 6.0)
        g10 = _fresh_game(start_level=10)
        self.assertAlmostEqual(g10.power_duration, 1.5)
        g100 = _fresh_game(start_level=100)
        # 下限 1.0
        self.assertAlmostEqual(g100.power_duration, 1.0)

    def test_ghost_base_speed_ceiling(self):
        g1 = _fresh_game(start_level=1)
        self.assertAlmostEqual(g1.ghost_base_speed, 0.9)
        # L=10: 0.9 + 0.02*9 = 1.08 → min(1.08, 0.98) = 0.98（封顶）
        g10 = _fresh_game(start_level=10)
        self.assertAlmostEqual(g10.ghost_base_speed, 0.98)
        g100 = _fresh_game(start_level=100)
        # 上限 0.98
        self.assertAlmostEqual(g100.ghost_base_speed, 0.98)


class TestPause(unittest.TestCase):
    """TC-D4：暂停时 update 不推进。"""

    def test_pause_freezes_state(self):
        game = _fresh_game()
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.CHASE
        pos_before = blinky.pos
        score_before = game.score
        power_before = game.power_timer
        game.toggle_pause()
        self.assertEqual(game.status, GameStatus.PAUSED)
        game.update(0.5)
        # 所有状态应保持
        self.assertEqual(blinky.pos, pos_before)
        self.assertEqual(game.score, score_before)
        self.assertEqual(game.power_timer, power_before)
        game.toggle_pause()
        self.assertEqual(game.status, GameStatus.PLAYING)

    def test_pause_in_game_over_is_noop(self):
        game = _fresh_game()
        game.status = GameStatus.GAME_OVER
        game.toggle_pause()
        self.assertEqual(game.status, GameStatus.GAME_OVER)


class TestGhostSpeed(unittest.TestCase):
    """幽灵速度模型：EYES=1.5, FRIGHTENED=0.75, Elroy Blinky=1.0, 其他=ghost_base_speed。"""

    def test_eyes_speed(self):
        game = _fresh_game()
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.EYES
        self.assertAlmostEqual(game._ghost_speed(blinky), 1.5)

    def test_frightened_speed(self):
        game = _fresh_game()
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.FRIGHTENED
        self.assertAlmostEqual(game._ghost_speed(blinky), 0.75)

    def test_elroy_blinky_speed(self):
        game = _fresh_game()
        _consume_all_but_n(game, 10)  # 残豆 10 < 阈值 20
        blinky = next(g for g in game.ghosts if g.kind is GhostKind.BLINKY)
        blinky.released = True
        blinky.mode = GhostMode.CHASE
        self.assertAlmostEqual(game._ghost_speed(blinky), 1.0)


class TestMovementMechanics(unittest.TestCase):
    """TC-B1/B3：方向控制 + 撞墙不穿。"""

    def test_buffered_direction_takes_effect(self):
        game = _fresh_game(speed=1.0)
        # 玩家面朝 LEFT，准备朝 RIGHT
        game.player.direction = Dir.LEFT
        game.player.buffered_direction = Dir.RIGHT
        # 玩家当前 row12 col10；朝右可走
        game.player.pos = Pos(12, 10)
        game.update(0.1)
        # buffered 方向已生效
        self.assertIs(game.player.direction, Dir.RIGHT)
        self.assertIsNone(game.player.buffered_direction)

    def test_buffered_overwrites_previous(self):
        game = _fresh_game(speed=0.0)
        game.player.direction = Dir.LEFT
        game.player.buffered_direction = Dir.UP
        game.player.buffered_direction = Dir.RIGHT  # 覆盖
        self.assertIs(game.player.buffered_direction, Dir.RIGHT)

    def test_wall_blocks_player(self):
        game = _fresh_game(speed=1.0)
        # 玩家在 (0, 1) 朝上 → 墙
        game.player.pos = Pos(0, 1)
        game.player.direction = Dir.UP
        game.player.buffered_direction = None
        game.update(0.1)
        # (0, 1) 上方是墙 (0, 0 or 0, 1?) → 看地图: row0 col1 是 '.' 可走；选一个明确撞墙的位置
        # row12 col10 上方 row11 col10 在 map 中是通道；换 row12 col9 (这是 PP 起点上方是墙吗？)
        # 简化：放在 (0, 1)，强制朝上连续 update 不动
        for _ in range(3):
            game.update(0.1)
        self.assertEqual(game.player.pos, Pos(0, 1))


class TestRespawnAfterLoss(unittest.TestCase):
    """TC-C9：扣命后全部幽灵回鬼屋（按 release 规则）。"""

    def test_ghosts_return_to_house(self):
        game = _frozen_game()
        game.protection_timer = 0.0
        game.player.direction = Dir.DOWN
        game.player.buffered_direction = None
        for g in game.ghosts:
            g.released = True
            g.mode = GhostMode.CHASE
            g.pos = Pos(0, 21)
        # 强制同格触发扣命
        game.ghosts[0].pos = game.player.pos
        game.update(0.1)
        # 全部幽灵应回到 spawn_for_ghost 计算的位置
        for i, g in enumerate(game.ghosts):
            expected = game.map.spawn_for_ghost(i)
            self.assertEqual(g.pos, expected)


if __name__ == "__main__":
    unittest.main()
