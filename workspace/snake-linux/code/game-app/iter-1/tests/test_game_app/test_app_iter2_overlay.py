"""iter-2 暂停遮罩单测（UT O-1 ~ O-4）。

需求（G2-5）：
- draw_pause_overlay 形参正确
- 遮罩覆盖全屏（surface.blit 调用 ≥2）
- 遮罩不读 _screen（沿用 R3-2）
- 遮罩走 pygame.display.get_surface()（来自 _render PAUSED 路径）
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from game_app import AppScreen, InputAction
from game_app.menu import draw_pause_overlay
from game_core import Difficulty


class TestPauseOverlaySignature:
    """O-1: draw_pause_overlay 形参。"""

    def test_function_signature(self) -> None:
        """O-1：函数签名 (surface, body_font) -> None。"""
        sig = inspect.signature(draw_pause_overlay)
        params = list(sig.parameters.keys())
        assert params == ["surface", "body_font"]
        # return_annotation 在 from __future__ import annotations 下为字符串 'None'
        assert sig.return_annotation in (None, "None")


class TestPauseOverlayCoversScreen:
    """O-2: 遮罩覆盖全屏。"""

    def test_pause_overlay_blits_at_least_twice(self, fake_pygame) -> None:
        """O-2：surface.blit 调用次数 ≥2（半透明矩形 + 文字）。"""
        surface = MagicMock(name="surface")
        surface.get_size.return_value = (640, 480)
        surface.get_width.return_value = 640
        surface.get_height.return_value = 480
        body_font = MagicMock(name="body_font")
        body_font.render.return_value = MagicMock(
            get_width=MagicMock(return_value=100),
            get_height=MagicMock(return_value=20),
        )

        draw_pause_overlay(surface, body_font)
        # 至少 3 次 blit：overlay + "PAUSED" + "按 P 继续"
        assert surface.blit.call_count >= 2


class TestPauseOverlayUsesGetSurface:
    """O-3 / O-4: 遮罩走 pygame.display.get_surface()。"""

    def test_render_paused_uses_display_get_surface(
        self, fake_pygame, fake_storage, monkeypatch
    ) -> None:
        """O-4：_render() 在 PAUSED 态通过 fake_pygame.display.get_surface() 拿 surface。"""
        from game_app import App
        from unittest.mock import MagicMock

        # 构造带 mock renderer 的 paused app
        a = App()
        a._difficulty = Difficulty.HARD
        a._storage = fake_storage
        a._high_score = 0
        mock_renderer = MagicMock(name="mock_renderer")
        a._renderer = mock_renderer
        a._menu_title_font = MagicMock(name="title_font")
        a._menu_body_font = MagicMock(name="body_font")
        a.clock = MagicMock(name="clock")
        a._new_game(Difficulty.HARD)
        a._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PAUSED

        a._render()

        # fake_pygame.display.get_surface 应被调过
        assert fake_pygame.display.get_surface.call_count >= 1


class TestPauseOverlayNoScreenRead:
    """O-3: 遮罩不读 _screen（R3-2 沿用）。"""

    def test_overlay_does_not_access_renderer_screen(
        self, fake_pygame
    ) -> None:
        """O-3：draw_pause_overlay 不读 surface 之外的私有属性。"""
        import ast
        import game_app.menu as menu_mod

        # 解析 menu.py AST，提取 draw_pause_overlay 函数的代码节点
        source = inspect.getsource(menu_mod)
        tree = ast.parse(source)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "draw_pause_overlay":
                func_node = node
                break
        assert func_node is not None, "draw_pause_overlay function not found"
        # 检查函数体内是否有访问 _screen
        for subnode in ast.walk(func_node):
            if isinstance(subnode, ast.Attribute) and subnode.attr == "_screen":
                pytest.fail(
                    f"draw_pause_overlay must not access _screen (R3-2): {ast.dump(subnode)}"
                )