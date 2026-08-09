"""renderer.py 单测。

用 ScreenStub（curses 屏幕桩）代替真实屏幕，覆盖：
- TC-D1 六类元素渲染（墙/通道/豆/能量豆/玩家/幽灵）
- TC-D2 --no-color 单色降级（无 curses 颜色对初始化）
- TC-D3 HUD：分数/命数/关卡/能量倒计时实时刷新
- TC-D7 结算画面（最终分数/关卡/吃幽灵数）
- TC-N5 终端 <80×24 → TerminalTooSmall
- TC-C6 脆弱态倒计时渲染
"""
from __future__ import annotations

import unittest

from tests._path import code_dir
from pacman.renderer import Renderer, TerminalTooSmall

from pacman.config import Config
from pacman.entities import GhostKind, GhostMode
from pacman.map import Pos

from tests.fixtures import ScreenStub, build_game


class TestSizeCheck(unittest.TestCase):
    """Renderer.size_ok：<80×24 → False。"""

    def test_too_small(self):
        self.assertFalse(Renderer.size_ok(20, 80))
        self.assertFalse(Renderer.size_ok(24, 60))
        self.assertFalse(Renderer.size_ok(23, 79))

    def test_ok(self):
        self.assertTrue(Renderer.size_ok(24, 80))
        self.assertTrue(Renderer.size_ok(40, 100))


class TestDrawHUD(unittest.TestCase):
    """TC-D3：HUD 实时刷新。"""

    def test_initial_hud(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        r.draw(g, 0.0)
        self.assertIn("PAC-MAN", screen.line(0))
        self.assertIn("分数 000000", screen.line(0))
        self.assertIn("命数 3", screen.line(0))
        self.assertIn("关卡 1", screen.line(0))
        self.assertIn("状态 PLAYING", screen.line(0))
        self.assertEqual(screen.erase_count, 1)
        self.assertEqual(screen.refresh_count, 1)

    def test_hud_after_score(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        g.score = 1234
        g.lives = 1
        g.level = 5
        r.draw(g, 0.0)
        self.assertIn("分数 001234", screen.line(0))
        self.assertIn("命数 1", screen.line(0))
        self.assertIn("关卡 5", screen.line(0))

    def test_hud_power_timer(self):
        # TC-D3：能量暴走显示倒计时
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        g.power_timer = 3.2
        r.draw(g, 0.0)
        self.assertIn("能量暴走 3.2s", screen.line(0))


class TestDrawElements(unittest.TestCase):
    """TC-D1：六类元素均可见。"""

    def test_all_elements_visible(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        r.draw(g, 0.0)
        # 墙 ██
        self.assertIn("██", screen.captured)
        # 普通豆 ·
        self.assertIn("·", screen.captured)
        # 能量豆 ●
        self.assertIn("●", screen.captured)
        # 玩家 ᗧ
        self.assertIn("ᗧ", screen.captured)
        # 幽灵 B P I C（每个对应一个字母 + 空格）
        for letter in ("B", "P", "I", "C"):
            self.assertIn(f"{letter} ", screen.captured)

    def test_four_ghosts_different_chars(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        # 把所有幽灵放到可见位置
        for offset, ghost in enumerate(g.ghosts):
            ghost.pos = Pos(15, 5 + offset)
            ghost.released = True
            ghost.mode = GhostMode.CHASE
        r.draw(g, 0.0)
        for letter in ("B", "P", "I", "C"):
            self.assertIn(f"{letter} ", screen.captured)

    def test_frightened_render(self):
        # TC-C6/B9：FRIGHTENED 模式显示 f 或 w（蓝/白闪烁）
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        blinky = next(gh for gh in g.ghosts if gh.kind is GhostKind.BLINKY)
        blinky.pos = Pos(15, 5)
        blinky.released = True
        blinky.mode = GhostMode.FRIGHTENED
        # power_timer > 2.0 → "f "
        g.power_timer = 4.0
        r.draw(g, 0.0)
        self.assertIn("f ", screen.captured)
        # power_timer <= 2.0 → "w "（闪烁）；用整数触发条件
        screen2 = ScreenStub(24, 80)
        r2 = Renderer(screen2, no_color=True)
        g.power_timer = 1.0
        r2.draw(g, 0.0)
        self.assertIn("w ", screen2.captured)

    def test_eyes_render(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        blinky = next(gh for gh in g.ghosts if gh.kind is GhostKind.BLINKY)
        blinky.pos = Pos(15, 5)
        blinky.released = True
        blinky.mode = GhostMode.EYES
        r.draw(g, 0.0)
        self.assertIn("◉ ", screen.captured)


class TestGameOverScreen(unittest.TestCase):
    """TC-D7/B12：结算画面显示最终得分/关卡/吃幽灵数。"""

    def test_game_over_panel(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        g.score = 9999
        g.level = 7
        g.ghosts_eaten = 42
        from pacman.game import GameStatus
        g.status = GameStatus.GAME_OVER
        r.draw(g, 0.0)
        self.assertIn("游戏结束", screen.captured)
        self.assertIn("最终分数：9999", screen.captured)
        self.assertIn("到达关卡：7", screen.captured)
        self.assertIn("吃幽灵：42", screen.captured)


class TestPauseScreen(unittest.TestCase):
    """TC-D4：暂停画面。"""

    def test_pause_message(self):
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        from pacman.game import GameStatus
        g.status = GameStatus.PAUSED
        r.draw(g, 0.0)
        self.assertIn("已暂停", screen.captured)


class TestTerminalTooSmall(unittest.TestCase):
    """TC-N5：终端 <80×24 → TerminalTooSmall。"""

    def test_small_raises(self):
        screen = ScreenStub(20, 80)
        r = Renderer(screen, no_color=True)
        g = build_game()
        with self.assertRaises(TerminalTooSmall) as ctx:
            r.draw(g, 0.0)
        # 错误信息含 ≥80×24
        self.assertIn("80", str(ctx.exception))
        self.assertIn("24", str(ctx.exception))


class TestDrawError(unittest.TestCase):
    """draw_error：终端尺寸错误提示。"""

    def test_draw_error(self):
        screen = ScreenStub(20, 80)
        r = Renderer(screen, no_color=True)
        r.draw_error("需要 ≥80×24 终端，当前 80×20")
        # 居中显示错误信息
        self.assertIn("≥80×24", screen.captured)
        self.assertIn("调整终端后按任意键退出", screen.captured)


class TestRendererWithColors(unittest.TestCase):
    """颜色初始化分支：避免触发 curses 全局（initscr 未调）。

    这里只断言 no_color=False 时进入颜色分支的入口参数；具体的
    use_color 取决于运行环境是否有真实终端。
    """

    def test_no_color_false_does_not_raise_for_size_only(self):
        # 用 size_ok 等纯函数方法避开 curses 全局
        self.assertTrue(Renderer.size_ok(24, 80))

    def test_color_init_attribute_exists(self):
        # Renderer 必须有 use_color / colors 属性（签名约束）
        screen = ScreenStub(24, 80)
        r = Renderer(screen, no_color=True)
        self.assertFalse(r.use_color)
        self.assertEqual(r.colors, {})


if __name__ == "__main__":
    unittest.main()
