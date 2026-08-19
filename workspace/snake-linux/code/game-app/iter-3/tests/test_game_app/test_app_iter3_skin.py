"""G3-1 皮肤切换 UI 单测（SK-1~SK-11）。

需求：
- MENU 态 ←/→ 切皮肤（_skin_index 循环；调 Renderer.set_skin）
- PLAYING/PAUSED/GAME_OVER 态 ←/→ 透传为 MOVE_LEFT/MOVE_RIGHT（不影响对局，FR-10）
- SkinNotFoundError 兜底（stderr 提示 + _skin_index 不变）
- skin_names() 空时防御
- _render MENU 路径用 current_skin_name（通过 spy draw_menu 断言）

G3-1：MENU 态皮肤切换 UI
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from game_app import App, InputAction, AppScreen
from game_app.screens import AppScreen as AppScreenConst
from game_core import Difficulty

# 复用作 test_drain_events 的事件注入辅助
from .conftest import (
    FakeEvent, _PYGAME_KEYS,
    make_resize_event,  # 仅占位，下面单独构造
)


def _kd(key: str) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], _PYGAME_KEYS[key])


def _set_events(app: App, events) -> None:
    """直接给 fake_pygame.event.get 返回值打补丁。"""
    from game_app import app as app_mod
    fake = app_mod.pygame
    fake.event.get.return_value = events


# ============================================================
# SK-1~SK-3：MENU 态 _switch_skin 行为
# ============================================================

class TestSwitchSkinMenuScreen:
    """G3-1：MENU 态 SET_SKIN_NEXT/SET_SKIN_PREV 在 _drain_events 内同步处理（不进 dispatch）。"""

    def test_skin_next_increments_index(self, app: App, fake_renderer_iter3: MagicMock) -> None:
        """SK-1：MENU 态 → 键切下一皮肤 → set_skin("dark") 调用 1 次 + _skin_index == 1。"""
        _set_events(app, [_kd("K_RIGHT")])
        actions = app._drain_events()
        # SK-1：MENU 态同步处理 → 不入 actions 列表
        assert InputAction.SET_SKIN_NEXT not in actions
        # 调 set_skin
        fake_renderer_iter3.set_skin.assert_called_once_with("dark")
        # _skin_index 更新
        assert app._skin_index == 1

    def test_skin_prev_decrements_index_wraps(self, app: App, fake_renderer_iter3: MagicMock) -> None:
        """SK-2：MENU 态 ← 键切上一皮肤（初始 0 → (0-1)%3=2 → colorblind_friendly）。"""
        _set_events(app, [_kd("K_LEFT")])
        actions = app._drain_events()
        assert InputAction.SET_SKIN_PREV not in actions
        fake_renderer_iter3.set_skin.assert_called_once_with("colorblind_friendly")
        assert app._skin_index == 2

    def test_skin_cycles_through_indices(self, app: App, fake_renderer_iter3: MagicMock) -> None:
        """SK-3：MENU 态循环边界：连续 3 次 ← → _skin_index 在 [0, 2, 1, 0]。"""
        for _ in range(3):
            _set_events(app, [_kd("K_LEFT")])
            app._drain_events()
        # 0 -> 2 -> 1 -> 0
        assert app._skin_index == 0
        # 验证调用顺序（colorblind_friendly → dark → classic）
        assert fake_renderer_iter3.set_skin.call_count == 3
        calls = [c.args[0] for c in fake_renderer_iter3.set_skin.call_args_list]
        assert calls == ["colorblind_friendly", "dark", "classic"]

    def test_skin_next_multiple_times(self, app: App, fake_renderer_iter3: MagicMock) -> None:
        """MENU 态连续 → 键 → _skin_index 循环 0→1→2→0。"""
        for _ in range(3):
            _set_events(app, [_kd("K_RIGHT")])
            app._drain_events()
        assert app._skin_index == 0
        calls = [c.args[0] for c in fake_renderer_iter3.set_skin.call_args_list]
        assert calls == ["dark", "colorblind_friendly", "classic"]

    def test_skin_event_not_in_actions_when_menu(self, app: App) -> None:
        """G3-1：MENU 态 SET_SKIN_* 不进 actions 列表（同步处理）。"""
        _set_events(app, [_kd("K_RIGHT"), _kd("K_LEFT")])
        actions = app._drain_events()
        assert InputAction.SET_SKIN_PREV not in actions
        assert InputAction.SET_SKIN_NEXT not in actions


# ============================================================
# SK-4~SK-7：PLAYING/PAUSED/GAME_OVER 态 ←/→ 透传为 MOVE_*
# ============================================================

class TestSkinKeysOtherScreens:
    """G3-1：PLAYING/PAUSED/GAME_OVER 态 ←/→ 透传为 MOVE_LEFT/MOVE_RIGHT（不影响对局，FR-10）。"""

    def test_playing_skin_prev_becomes_move_left(
        self, app_in_playing: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-4：PLAYING 态 ← 键 → 透传为 MOVE_LEFT（不调 set_skin；_skin_index 不变）。"""
        _set_events(app_in_playing, [_kd("K_LEFT")])
        actions = app_in_playing._drain_events()
        assert InputAction.MOVE_LEFT in actions
        assert InputAction.SET_SKIN_PREV not in actions
        fake_renderer_iter3.set_skin.assert_not_called()
        assert app_in_playing._skin_index == 0  # 不变

    def test_playing_skin_next_becomes_move_right(
        self, app_in_playing: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-5：PLAYING 态 → 键 → 透传为 MOVE_RIGHT。"""
        _set_events(app_in_playing, [_kd("K_RIGHT")])
        actions = app_in_playing._drain_events()
        assert InputAction.MOVE_RIGHT in actions
        assert InputAction.SET_SKIN_NEXT not in actions
        fake_renderer_iter3.set_skin.assert_not_called()

    def test_paused_skin_prev_becomes_move_left(
        self, app_in_paused: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-6：PAUSED 态 ← 键 → 透传为 MOVE_LEFT。"""
        _set_events(app_in_paused, [_kd("K_LEFT")])
        actions = app_in_paused._drain_events()
        assert InputAction.MOVE_LEFT in actions
        fake_renderer_iter3.set_skin.assert_not_called()

    def test_game_over_skin_prev_becomes_move_left(
        self, app_in_game_over: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-7：GAME_OVER 态 ← 键 → 透传为 MOVE_LEFT（不影响对局，FR-10）。"""
        _set_events(app_in_game_over, [_kd("K_LEFT")])
        actions = app_in_game_over._drain_events()
        assert InputAction.MOVE_LEFT in actions
        fake_renderer_iter3.set_skin.assert_not_called()


# ============================================================
# SK-8：SkinNotFoundError 兜底
# ============================================================

class TestSwitchSkinErrorHandling:
    """G3-1：_switch_skin 防御性兜底。"""

    def test_skin_not_found_error_keeps_index(
        self, app: App, fake_renderer_iter3: MagicMock, capsys
    ) -> None:
        """SK-8：set_skin 抛 SkinNotFoundError → stderr 写入 + _skin_index 不变。"""
        from gui_renderer import SkinNotFoundError
        fake_renderer_iter3.set_skin.side_effect = SkinNotFoundError(name="bad", available=("classic",))
        # 直接调 _switch_skin（不走 _drain_events 的输入路径）
        app._switch_skin(InputAction.SET_SKIN_NEXT)
        # 索引未变（仍为 0）
        assert app._skin_index == 0
        # stderr 写入
        captured = capsys.readouterr()
        assert "[警告]" in captured.err
        assert "切换皮肤失败" in captured.err

    def test_skin_names_empty_does_nothing(
        self, app: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-9：skin_names() 空时防御：不调 set_skin + _skin_index 不变。"""
        fake_renderer_iter3.skin_names.return_value = ()
        app._switch_skin(InputAction.SET_SKIN_NEXT)
        fake_renderer_iter3.set_skin.assert_not_called()
        assert app._skin_index == 0


# ============================================================
# SK-10/SK-11：_render MENU 路径用 current_skin_name
# ============================================================

class TestRenderMenuSkinName:
    """G3-1 + G3-5：_render MENU 路径用 current_skin_name（spy draw_menu 断言）。"""

    def test_render_menu_passes_current_skin_name(
        self, app: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-10：_render MENU 路径 spy draw_menu 调用参数 current_skin_name == current_skin_name。"""
        from game_app import app as app_mod
        with patch.object(app_mod, "draw_menu") as mock_draw:
            app.screen = AppScreenConst.MENU
            app._render()
            mock_draw.assert_called_once()
            kwargs = mock_draw.call_args.kwargs
            assert kwargs.get("current_skin_name") == fake_renderer_iter3.current_skin_name
            assert kwargs.get("current_skin_name") == "classic"

    def test_render_menu_after_skin_switch(
        self, app: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """SK-11：切换皮肤后 _render 下一帧使用新皮肤。"""
        # 模拟切换到 dark
        fake_renderer_iter3.current_skin_name = "dark"
        fake_renderer_iter3.set_skin.return_value = None  # set_skin 已"切到"dark
        from game_app import app as app_mod
        with patch.object(app_mod, "draw_menu") as mock_draw:
            app.screen = AppScreenConst.MENU
            app._render()
            kwargs = mock_draw.call_args.kwargs
            assert kwargs.get("current_skin_name") == "dark"
