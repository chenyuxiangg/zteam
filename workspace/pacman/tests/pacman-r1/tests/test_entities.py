"""实体测试：U-30 / U-31 / U-32 / U-33。

覆盖：
- Mover 速度累积器：speed=0.9 → 100 tick 走 90 格（U-30）
- Player 输入缓冲：deque maxlen=1（新指令覆盖旧指令，U-31）
- Player 撞墙不穿：非法方向不入队 / 不执行（U-32）
- 玩家沿墙持续移动：永不进 WALL 格（U-33）

fixtures 不依赖 curses；纯逻辑层，可脱离终端单测。
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401
from tests.fixtures import builtin_map, make_player

from pacman.entities import Mover, Player
from pacman.config import Dir, PLAYER_SPEED


class TestMoverSpeedAccumulator(unittest.TestCase):
    """U-30：速度累积器精度——speed=N 走 tick 次应得约 N×speed 步（浮点累积正确）。"""

    def test_u30_speed_09_in_11_ticks(self):
        """speed=0.9, 11 tick → 9 格（0.9×11=9.9 → 9 步，acc 留 0.9）。"""
        gm = builtin_map()
        # (3, 1) 是 row 3 长通道起点，向右可走 19 格
        m = Mover(pos=(3, 1), dir_=Dir.RIGHT, speed=0.9)
        steps = 0
        for _ in range(11):
            steps += m.add_motion(gm)
        self.assertEqual(steps, 9)
        self.assertAlmostEqual(m.acc, 0.9, places=6)

    def test_u30_speed_10_in_11_ticks(self):
        """speed=1.0, 11 tick → 11 格（精确，无累积误差）。"""
        gm = builtin_map()
        m = Mover(pos=(3, 1), dir_=Dir.RIGHT, speed=1.0)
        steps = 0
        for _ in range(11):
            steps += m.add_motion(gm)
        self.assertEqual(steps, 11)
        self.assertEqual((m.row, m.col), (3, 12))
        self.assertAlmostEqual(m.acc, 0.0, places=6)

    def test_u30_speed_05_acc_correctness(self):
        """speed=0.5, 10 tick → 5 格（整除无误差）。"""
        gm = builtin_map()
        m = Mover(pos=(3, 1), dir_=Dir.RIGHT, speed=0.5)
        steps = 0
        for _ in range(10):
            steps += m.add_motion(gm)
        self.assertEqual(steps, 5)
        self.assertAlmostEqual(m.acc, 0.0, places=6)

    def test_u30_acc_caps_at_four(self):
        """防大 dt 跳帧：累积器封顶 4。"""
        gm = builtin_map()
        m = Mover(pos=(1, 1), dir_=Dir.RIGHT, speed=0.9)
        m.speed = 100.0
        steps = m.add_motion(gm)
        self.assertLessEqual(steps, 4)
        self.assertLess(m.acc, 4.0)



class TestMoverReverse(unittest.TestCase):
    """Mover.reverse 180° 掉头。"""

    def test_reverse(self):
        m = Mover(pos=(0, 0), dir_=Dir.UP, speed=1.0)
        m.reverse()
        self.assertEqual(m.dir, Dir.DOWN)
        m.reverse()
        self.assertEqual(m.dir, Dir.UP)


class TestPlayerTurnBuffer(unittest.TestCase):
    """U-31：玩家输入缓冲 deque maxlen=1——新指令覆盖旧指令。"""

    def test_u31_new_overwrites_old(self):
        gm = builtin_map()
        p = Player(pos=(1, 1))
        p.dir = Dir.RIGHT
        # 第一个指令 UP（合法）
        p.request_turn(Dir.UP)
        # 第二个指令 LEFT（合法）应覆盖 UP
        p.request_turn(Dir.LEFT)
        # consume 后方向 = LEFT（最新）
        p.consume_turn(gm)
        self.assertEqual(p.dir, Dir.LEFT)
        # 缓冲已被清空
        self.assertEqual(len(p.turn_buffer), 0)

    def test_u31_reverse_immediate(self):
        """反向指令应立即执行（不缓冲）。"""
        gm = builtin_map()
        p = Player(pos=(1, 1))
        p.dir = Dir.RIGHT
        # 反向 = LEFT；request_turn 应立即 reverse
        p.request_turn(Dir.LEFT)
        self.assertEqual(p.dir, Dir.LEFT)
        # 缓冲应清空（防止残留指令与新方向冲突）
        self.assertEqual(len(p.turn_buffer), 0)


class TestPlayerWallBlock(unittest.TestCase):
    """U-32：撞墙不穿——非法方向不入队 / 不执行。"""

    def test_u32_blocked_turn_not_executed(self):
        """玩家前方为墙时转向指令不入队/不执行。"""
        gm = builtin_map()
        # builtin (0,2) 上方是 OOB，左 (0,1) 是 WALL，下 (1,2) 是 DOT, 右 (0,3) WALL
        p = Player(pos=(0, 2))
        p.dir = Dir.DOWN  # 当前方向：向下（DOT 可走）
        # 尝试请求 RIGHT：但 (0,3) 是 WALL
        p.request_turn(Dir.RIGHT)
        # RIGHT 不应执行——direction 仍为 DOWN
        p.consume_turn(gm)
        self.assertEqual(p.dir, Dir.DOWN)

    def test_u32_legal_turn_executes_next_tick(self):
        """合法方向下一 tick 立即执行。"""
        gm = builtin_map()
        p = Player(pos=(0, 2))
        p.dir = Dir.DOWN
        # 请求 LEFT：但 (0,1) 是 WALL，不应执行
        # 然后请求 UP：合法（如果上 (1,2) DOWN）——实际是 OOB
        # 改用 builtin (1,1) DOT；UP (0,1)=WALL, DOWN (2,1)=POWER, LEFT OOB, RIGHT (1,2)=DOT
        p.row, p.col = 1, 1
        p.dir = Dir.RIGHT
        p.request_turn(Dir.DOWN)  # (2,1) 是 POWER，可通
        p.consume_turn(gm)
        self.assertEqual(p.dir, Dir.DOWN)


class TestPlayerCannotWalkIntoWall(unittest.TestCase):
    """U-33：沿墙持续移动，玩家位置永不进 WALL 格（修复 r1 评审 #1）。"""

    def test_u33_walking_into_wall_stops(self):
        gm = builtin_map()
        p = Player(pos=(1, 1))
        p.dir = Dir.UP  # (0,1) 是 WALL
        # 推 20 tick 看是否穿墙
        for _ in range(20):
            p.add_motion(gm)
        # 玩家 (1, 1) 应停在原地（向上是墙，acc 清零）
        self.assertEqual((p.row, p.col), (1, 1))
        self.assertEqual(p.acc, 0.0)

    def test_u33_walking_along_wall_stays_on_passage(self):
        """沿通道行 20 tick 不进入任何 WALL。"""
        gm = builtin_map()
        p = Player(pos=(2, 1))  # POWER，可通
        p.dir = Dir.RIGHT
        # 推 20 tick
        visited = [(p.row, p.col)]
        for _ in range(20):
            p.add_motion(gm)
            visited.append((p.row, p.col))
        # 验证每个位置都不是 WALL
        for r, c in visited:
            t = gm.tile_at(r, c)
            self.assertNotEqual(t.name, "WALL", f"玩家穿墙: ({r},{c})")


class TestPlayerProtectionTimer(unittest.TestCase):
    """Player 保护期倒计时。"""

    def test_protection_timer_decrements(self):
        p = Player(pos=(1, 1))
        p.protection_timer = 2.0
        p.update_protection(0.5)
        self.assertAlmostEqual(p.protection_timer, 1.5, places=6)

    def test_protection_timer_floors_at_zero(self):
        p = Player(pos=(1, 1))
        p.protection_timer = 0.5
        p.update_protection(1.0)
        self.assertEqual(p.protection_timer, 0.0)


class TestPlayerProperty(unittest.TestCase):
    """Mover.pos 属性。"""

    def test_pos_returns_tuple(self):
        m = Mover(pos=(3, 5), dir_=Dir.UP, speed=1.0)
        self.assertEqual(m.pos, (3, 5))

    def test_set_pos_updates(self):
        m = Mover(pos=(3, 5), dir_=Dir.UP, speed=1.0)
        m.set_pos((10, 15))
        self.assertEqual(m.pos, (10, 15))
        self.assertEqual(m.row, 10)
        self.assertEqual(m.col, 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)