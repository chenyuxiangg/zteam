"""renderer 测试：通过 stub screen 验证绘制行为。

覆盖：FR-14（渲染）/ FR-15（HUD）/ S-02（六元素）/ S-03（HUD 实时）/ S-08（结算画面）/ E-01（尺寸不足）。
真实终端视觉项保留手工走查清单（manual_checklist.md）。

策略：直接 import renderer 模块但用 sys.modules 注入 curses 桩，使 _init_colors 走 has_colors=False 路径。
"""
from __future__ import annotations

import sys
import unittest
from types import ModuleType

from tests._path import code_dir  # noqa: F401
from tests.fixtures import (
    ScreenStub, builtin_map, build_game, frozen_clock,
    CursesStub,
)


def _install_curses_stub():
    """注入极简 curses 桩，使 renderer 模块能成功 import 而无真终端。"""
    fake = ModuleType("curses")
    fake.has_colors = lambda: False
    fake.start_color = lambda: None
    fake.use_default_colors = lambda: None
    fake.init_pair = lambda *a, **k: None
    fake.color_pair = lambda n: n
    fake.curs_set = lambda v: 0
    # 颜色常量
    fake.COLOR_BLACK = 0
    fake.COLOR_RED = 1
    fake.COLOR_GREEN = 2
    fake.COLOR_YELLOW = 3
    fake.COLOR_BLUE = 4
    fake.COLOR_MAGENTA = 5
    fake.COLOR_CYAN = 6
    fake.COLOR_WHITE = 7
    fake.error = type("error", (Exception,), {})

    # 注入到 sys.modules（在 import renderer 之前）
    sys.modules["curses"] = fake
    return fake


# 在 import 任何 pacman.* 之前先注入 curses 桩
_curses_stub = _install_curses_stub()


from pacman.game import Game, Status
from pacman.renderer import Renderer


class TestRendererInit(unittest.TestCase):
    """Renderer 构造与基础状态。"""

    def test_renderer_init_with_screen_stub(self):
        screen = ScreenStub(lines=24, cols=80)
        r = Renderer(screen, no_color=True)
        self.assertIs(r.stdscr, screen)
        self.assertTrue(r.no_color)
        # has_colors=False → colors_ok=False
        self.assertFalse(r.colors_ok)


class TestRendererDrawTooSmall(unittest.TestCase):
    """E-01：终端 <80×24 应显示尺寸不足提示并。等待任意键。"""

    def test_draw_too_small_shows_message(self):
        screen = ScreenStub(lines=20, cols=60)
        r = Renderer(screen, no_color=True)
        game = build_game()
        r.draw(game)
        # 屏幕应包含尺寸提示
        self.assertTrue(screen.contains("需要 ≥80×24 终端"))
        # 屏幕应包含实际尺寸 60×20
        self.assertTrue(screen.contains("60"))
        self.assertTrue(screen.contains("20"))

    def test_wait_any_key_blocks_until_input(self):
        """wait_any_key 调用 getch（应不抛错）。"""
        screen = ScreenStub(lines=20, cols=60)
        r = Renderer(screen, no_color=True)
        # 桩 getch 返回 -1（无输入）
        screen.getch = lambda: -1
        # 不应抛
        r.wait_any_key()


class TestRendererDrawNormal(unittest.TestCase):
    """S-02 / S-03：正常渲染画面 + HUD + 六元素。"""

    def setUp(self):
        self.screen = ScreenStub(lines=24, cols=80)
        self.r = Renderer(self.screen, no_color=True)
        self.game = build_game()

    def test_draw_calls_erase_and_refresh(self):
        self.r.draw(self.game)
        self.assertGreater(self.screen.erase_count, 0)
        self.assertGreater(self.screen.refresh_count, 0)

    def test_draw_hud_contains_score_lives_level(self):
        """HUD 显示 分数/命/关。"""
        self.r.draw(self.game)
        self.assertTrue(self.screen.contains("分数:"))
        self.assertTrue(self.screen.contains("命:"))
        self.assertTrue(self.screen.contains("关:"))

    def test_draw_hud_includes_power_countdown_when_active(self):
        """能量豆期内 HUD 显示倒计时。"""
        self.game.power_timer = 3.5
        self.r.draw(self.game)
        self.assertTrue(self.screen.contains("能量:"))

    def test_draw_hud_normal_state_when_no_power(self):
        """无能量豆时 HUD 显示"状态: 普通"。"""
        self.game.power_timer = 0.0
        self.r.draw(self.game)
        self.assertTrue(self.screen.contains("状态:"))

    def test_draw_includes_six_element_types(self):
        """S-02：六元素（墙/通道/豆/能量豆/玩家/幽灵）可辨识。"""
        # 默认布局下 no_color=True：渲染用纯字符（#, ., o, -, C, G, H）
        self.r.draw(self.game)
        # 墙字符
        self.assertTrue(self.screen.contains("#"))
        # 玩家字符
        self.assertTrue(self.screen.contains("C"))
        # 幽灵字符
        self.assertTrue(self.screen.contains("G"))

    def test_draw_paused_shows_pause_message(self):
        """S-06：暂停时显示"** 已暂停 **"。"""
        self.game.pause()
        self.r.draw(self.game)
        self.assertTrue(self.screen.contains("已暂停"))

    def test_draw_game_over_shows_score(self):
        """S-08：GAME_OVER 显示最终得分/关卡/吃幽灵数。"""
        from pacman.game import FinalScore
        self.game.lives = 1
        self.game.score = 1500
        self.game.level = 3
        self.game.ghosts_eaten_total = 7
        # 强制 GAME_OVER
        self.game.status = Status.GAME_OVER
        self.r.draw(self.game)
        # 结算画面含字段
        self.assertTrue(self.screen.contains("游戏结束"))
        self.assertTrue(self.screen.contains("最终得分:"))
        self.assertTrue(self.screen.contains("到达关卡:"))
        self.assertTrue(self.screen.contains("吃幽灵数:"))
        # 数值
        self.assertTrue(self.screen.contains("1500"))


class TestRendererNoCrash(unittest.TestCase):
    """无颜色终端 / 边缘坐标不崩溃。"""

    def test_draw_at_24_80_works(self):
        """标准 80×24 终端正常渲染。"""
        screen = ScreenStub(lines=24, cols=80)
        r = Renderer(screen, no_color=True)
        game = build_game()
        # 不应抛错
        r.draw(game)


if __name__ == "__main__":
    unittest.main(verbosity=2)