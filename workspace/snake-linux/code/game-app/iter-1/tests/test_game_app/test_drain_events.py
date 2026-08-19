"""_drain_events 屏态兜底单测（R3-1 唯一转换点：UT 9a/9b/9c/9d/9e + 38）。
"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from game_app import App, InputAction
from game_app.input import _MENU_RESERVED_ACTIONS
from .conftest import _PYGAME_KEYS, FakeEvent


def _kd(key: str) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], _PYGAME_KEYS[key])


def _ev_quit() -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["QUIT"])


def _set_events(app: App, events) -> None:
    """直接给 app.game 内部 pygame.event.get 返回值打补丁。"""
    # app 模块使用 `import pygame`，访问通过 `sys.modules['pygame']`（_init_pygame 之前）
    # 由 conftest 提供的 fake_pygame 已在 sys.modules 中。
    from game_app import app as app_mod
    fake = app_mod.pygame
    fake.event.get.return_value = events


class TestDrainEventsMenuScreen:
    """MENU 屏态：None/方向键等非保留 action → START；保留键透传。"""

    def test_unmapped_key_becomes_start(self, app: App) -> None:
        """UT 9a：MENU 态 fake.event.get 返 [K_x 未映射 KEYDOWN] → _drain_events 返 [START]。"""
        _set_events(app, [_kd("K_x") if "K_x" in _PYGAME_KEYS else FakeEvent(_PYGAME_KEYS["KEYDOWN"], 120)])
        actions = app._drain_events()
        assert actions == [InputAction.START]

    @pytest.mark.parametrize("direction_key", ["K_UP", "K_DOWN", "K_LEFT", "K_RIGHT", "K_w", "K_a", "K_s", "K_d"])
    def test_direction_key_becomes_start(self, app: App, direction_key: str) -> None:
        """UT 9b：MENU 态方向键 → START（不是 MOVE_UP）。"""
        _set_events(app, [_kd(direction_key)])
        actions = app._drain_events()
        assert InputAction.START in actions
        # 确认不是 MOVE_*
        for a in actions:
            assert a not in (InputAction.MOVE_UP, InputAction.MOVE_DOWN, InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT)

    @pytest.mark.parametrize("key,expected", [
        ("K_1", InputAction.SELECT_EASY),
        ("K_2", InputAction.SELECT_MEDIUM),
        ("K_3", InputAction.SELECT_HARD),
        ("K_p", InputAction.TOGGLE_PAUSE),
        ("K_r", InputAction.RESTART),
    ])
    def test_reserved_keys_passthrough(self, app: App, key: str, expected: InputAction) -> None:
        """UT 9c：MENU 态保留键透传（不被 START 替换）。"""
        _set_events(app, [_kd(key)])
        actions = app._drain_events()
        assert expected in actions
        assert InputAction.START not in actions

    def test_quit_passthrough(self, app: App) -> None:
        """QUIT 在 MENU 态也是保留键（主循环外层 'if QUIT in actions: break'）。"""
        _set_events(app, [_ev_quit()])
        actions = app._drain_events()
        assert InputAction.QUIT in actions

    def test_quit_priority_with_unmapped(self, app: App) -> None:
        """UT 9e：同一帧返 [K_x, QUIT] → actions=[QUIT, START]（QUIT 必在）。"""
        _set_events(app, [FakeEvent(_PYGAME_KEYS["KEYDOWN"], 120), _ev_quit()])
        actions = app._drain_events()
        assert InputAction.QUIT in actions
        assert InputAction.START in actions


class TestDrainEventsOtherScreens:
    """PLAYING/GAME_OVER 屏态：原样透传（不补 START）。"""

    def test_playing_unmapped_passthrough_as_none_skipped(self, app_in_playing) -> None:
        """UT 9d：PLAYING 态返 [K_x 未映射 KEYDOWN] → 不补 START。"""
        _set_events(app_in_playing, [FakeEvent(_PYGAME_KEYS["KEYDOWN"], 120)])
        actions = app_in_playing._drain_events()
        assert InputAction.START not in actions
        assert actions == []  # None 被丢弃

    def test_playing_direction_passthrough(self, app_in_playing) -> None:
        """PLAYING 态方向键透传为 MOVE_UP 等。"""
        _set_events(app_in_playing, [_kd("K_UP")])
        actions = app_in_playing._drain_events()
        assert InputAction.MOVE_UP in actions
        assert InputAction.START not in actions

    def test_game_over_restart_passthrough(self, app_in_playing) -> None:
        """GAME_OVER 态 R 键透传。"""
        from game_app.screens import AppScreen
        app_in_playing.screen = AppScreen.GAME_OVER
        _set_events(app_in_playing, [_kd("K_r")])
        actions = app_in_playing._drain_events()
        assert InputAction.RESTART in actions
        assert InputAction.START not in actions


class TestDrainEventsAnyKeyStart:
    """UT 38：MENU 态任意键（未映射）→ START → 主循环下个 tick 后 screen==PLAYING。"""

    def test_any_key_start_triggers_new_game(self, app: App) -> None:
        """MENU 态 fake.event.get 返 [K_x 未映射 KEYDOWN] → _drain_events 返 [START] → _dispatch(START) → screen==PLAYING。"""
        from game_app.screens import AppScreen
        assert app.screen == AppScreen.MENU
        _set_events(app, [FakeEvent(_PYGAME_KEYS["KEYDOWN"], 120)])
        actions = app._drain_events()
        assert actions == [InputAction.START]
        for a in actions:
            app._dispatch(a)
        assert app.screen == AppScreen.PLAYING
        assert app.game_state is not None