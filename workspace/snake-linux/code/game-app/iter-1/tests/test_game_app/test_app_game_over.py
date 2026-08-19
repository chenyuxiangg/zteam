"""GAME_OVER 态 dispatch + 重开单测（UT 21/22）。

需求：
- R 键 RESTART → 新 game_state 且 status=RUN
- GAME_OVER 态 _drain_events 收到 QUIT 走主循环 break
"""
from __future__ import annotations

import pytest

from game_app import App, InputAction
from game_app.screens import AppScreen
from game_core import Difficulty, GameStatus


class TestGameOverRestart:
    def test_restart_opens_new_game(self, app_in_playing: App) -> None:
        """UT 21：_dispatch(RESTART) → screen==PLAYING + 新 game_state.status==RUN。"""
        # 进入 OVER
        app_in_playing._tick(1100)
        assert app_in_playing.screen == AppScreen.GAME_OVER
        old_state = app_in_playing.game_state
        assert old_state.status == GameStatus.OVER
        # RESTART
        app_in_playing._dispatch(InputAction.RESTART)
        assert app_in_playing.screen == AppScreen.PLAYING
        assert app_in_playing.game_state.status == GameStatus.RUN
        # 新对象（纯函数语义）
        assert app_in_playing.game_state is not old_state

    def test_restart_uses_current_difficulty(self, app_in_playing: App) -> None:
        """RESTART 保持选定难度。"""
        app_in_playing._tick(1100)
        assert app_in_playing.screen == AppScreen.GAME_OVER
        # 当前 _difficulty=HARD
        app_in_playing._dispatch(InputAction.RESTART)
        assert app_in_playing.game_state.difficulty == Difficulty.HARD


class TestGameOverQuit:
    def test_game_over_quit_breaks_main_loop(self, app_in_playing: App) -> None:
        """UT 22：GAME_OVER 态 _drain_events 返 [QUIT] → 主循环 break（_running 不被 dispatch 改）。"""
        from .test_drain_events import _set_events
        from .conftest import FakeEvent, _PYGAME_KEYS

        app_in_playing._tick(1100)
        assert app_in_playing.screen == AppScreen.GAME_OVER

        # 设置 fake event
        _set_events(app_in_playing, [FakeEvent(_PYGAME_KEYS["QUIT"])])
        actions = app_in_playing._drain_events()
        assert InputAction.QUIT in actions
        # 主循环检测后 break → _running 仍 True（break 不会改 _running）
        assert app_in_playing._running is True


class TestGameOverIgnoresOtherActions:
    """GAME_OVER 态收到非 RESTART 的 action 不应崩。"""

    def test_game_over_move_up_ignored(self, app_in_playing: App) -> None:
        app_in_playing._tick(1100)
        assert app_in_playing.screen == AppScreen.GAME_OVER
        # 调 MOVE_UP 应被静默忽略（_dispatch_over 没此分支）
        app_in_playing._dispatch(InputAction.MOVE_UP)
        assert app_in_playing.screen == AppScreen.GAME_OVER
        assert app_in_playing.game_state.status == GameStatus.OVER

    def test_game_over_start_ignored(self, app_in_playing: App) -> None:
        """START 是 MENU 态专属；GAME_OVER 态收到应被忽略（_dispatch_over 无 START 分支）。"""
        app_in_playing._tick(1100)
        assert app_in_playing.screen == AppScreen.GAME_OVER
        app_in_playing._dispatch(InputAction.START)
        assert app_in_playing.screen == AppScreen.GAME_OVER