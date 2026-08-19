"""_render 分发单测（UT 28/29/30/40）。

需求：
- MENU 态：用 pygame.display.get_surface() 取 surface + 调 menu.draw_menu；不调 renderer.render
- PLAYING 态：调 renderer.render(snap, hud)；只取 1 次 snapshot
- GAME_OVER 态：用 get_surface + menu.draw_game_over；不调 renderer.render
- R3-2：menu 不读 _renderer 私有
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from game_app import App, InputAction
from game_app.screens import AppScreen
from game_core import Difficulty


class TestRenderMenu:
    def test_menu_uses_get_surface(self, app_with_mock_renderer: App) -> None:
        """UT 28：MENU 态 _render 调 pygame.display.get_surface() 取 surface。"""
        from game_app import app as app_mod
        fake = app_mod.pygame
        # 切到 MENU
        app_with_mock_renderer.screen = AppScreen.MENU
        fake.display.get_surface.reset_mock()
        app_with_mock_renderer._render()
        # get_surface 应被调
        assert fake.display.get_surface.called

    def test_menu_calls_draw_menu(self, app_with_mock_renderer: App) -> None:
        """MENU 态 _render 调 menu.draw_menu。"""
        from game_app import app as app_mod
        with patch.object(app_mod, "draw_menu") as mock_draw:
            app_with_mock_renderer.screen = AppScreen.MENU
            app_with_mock_renderer._render()
            mock_draw.assert_called_once()
            args = mock_draw.call_args[0]
            assert len(args) == 4  # surface, title_font, body_font, difficulty
            assert args[3] == Difficulty.HARD

    def test_menu_does_not_call_renderer_render(self, app_with_mock_renderer: App) -> None:
        """MENU 态 _render 不调 renderer.render。"""
        app_with_mock_renderer.screen = AppScreen.MENU
        app_with_mock_renderer._render()
        assert not app_with_mock_renderer._renderer.render.called


class TestRenderPlaying:
    def test_playing_calls_renderer_render(self, app_with_mock_renderer: App) -> None:
        """UT 29：PLAYING 态 _render 调 renderer.render(snap, hud)。"""
        assert app_with_mock_renderer.screen == AppScreen.PLAYING
        app_with_mock_renderer._render()
        app_with_mock_renderer._renderer.render.assert_called_once()
        args = app_with_mock_renderer._renderer.render.call_args[0]
        assert len(args) == 2

    def test_playing_does_not_call_get_surface(self, app_with_mock_renderer: App) -> None:
        """PLAYING 态 _render 不调 get_surface（renderer 内部处理）。"""
        from game_app import app as app_mod
        fake = app_mod.pygame
        fake.display.get_surface.reset_mock()
        app_with_mock_renderer._render()
        assert not fake.display.get_surface.called

    def test_playing_calls_snapshot_only_once(self, app_with_mock_renderer: App) -> None:
        """UT 29：_render 内 snapshot 调用次数 = 1（含传给 _build_hud）。"""
        from game_core import GameState
        original = GameState.snapshot
        call_count = [0]

        def counting_snap(self):
            call_count[0] += 1
            return original(self)

        with patch.object(GameState, "snapshot", counting_snap):
            app_with_mock_renderer._render()
        # 期望 1 次（_render 共享一次 snap）
        assert call_count[0] == 1


class TestRenderGameOver:
    def test_game_over_uses_get_surface(self, app_with_mock_renderer: App) -> None:
        """UT 30：GAME_OVER 态 _render 调 pygame.display.get_surface() 取 surface。"""
        from game_app import app as app_mod
        fake = app_mod.pygame
        # 进入 GAME_OVER
        app_with_mock_renderer._tick(1100)
        assert app_with_mock_renderer.screen == AppScreen.GAME_OVER
        fake.display.get_surface.reset_mock()
        app_with_mock_renderer._render()
        assert fake.display.get_surface.called

    def test_game_over_calls_draw_game_over(self, app_with_mock_renderer: App) -> None:
        """GAME_OVER 态 _render 调 menu.draw_game_over(surface, fonts, score)。"""
        from game_app import app as app_mod
        with patch.object(app_mod, "draw_game_over") as mock_draw:
            app_with_mock_renderer._tick(1100)
            assert app_with_mock_renderer.screen == AppScreen.GAME_OVER
            app_with_mock_renderer._render()
            mock_draw.assert_called_once()
            args = mock_draw.call_args[0]
            assert len(args) == 4  # surface, title_font, body_font, score
            assert isinstance(args[3], int)

    def test_game_over_does_not_call_renderer_render(self, app_with_mock_renderer: App) -> None:
        """GAME_OVER 态 _render 不调 renderer.render。"""
        app_with_mock_renderer._tick(1100)
        assert app_with_mock_renderer.screen == AppScreen.GAME_OVER
        app_with_mock_renderer._render()
        assert not app_with_mock_renderer._renderer.render.called


class TestRenderMenuNoRendererPrivate:
    """UT 40：menu 不读 renderer 私有（R3-2）。"""

    def test_menu_does_not_access_renderer_private(self) -> None:
        """自绘过程不碰 _renderer._screen。"""
        from game_app import menu as menu_mod
        import inspect
        sig = inspect.signature(menu_mod.draw_menu)
        assert "app" not in sig.parameters  # 不接收 App
        params = list(sig.parameters.keys())
        assert "surface" in params
        sig2 = inspect.signature(menu_mod.draw_game_over)
        params2 = list(sig2.parameters.keys())
        assert "surface" in params2


class TestRenderFlipsDisplay:
    def test_render_calls_display_flip(self, app_with_mock_renderer: App) -> None:
        """_render 末尾调 pygame.display.flip()。"""
        from game_app import app as app_mod
        fake = app_mod.pygame
        app_with_mock_renderer._render()
        assert fake.display.flip.called