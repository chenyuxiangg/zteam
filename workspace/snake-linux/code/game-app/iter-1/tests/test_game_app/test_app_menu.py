"""MENU 态 dispatch + _new_game 单测（UT 10/11/12/13/36/42）。

需求：
- 1/2/3 改 _difficulty（R3-4 字段名）
- START 开局：screen=PLAYING + game_state 非 None（全关键字构造无 TypeError）
- QUIT 走主循环外层 break（dispatch 内不写 _running=False，UT 42）
- 难度游戏中不可切换（INV-3）
"""
from __future__ import annotations

import pytest

from game_app import App, InputAction
from game_app.screens import AppScreen
from game_core import Difficulty, GameState, GameStatus


class TestMenuDifficultySelection:
    @pytest.mark.parametrize("action,expected", [
        (InputAction.SELECT_EASY, Difficulty.EASY),
        (InputAction.SELECT_MEDIUM, Difficulty.MEDIUM),
        (InputAction.SELECT_HARD, Difficulty.HARD),
    ])
    def test_select_changes_difficulty(self, app: App, action: InputAction, expected: Difficulty) -> None:
        """UT 10/11：SELECT_* 改 _difficulty。"""
        assert app._difficulty == Difficulty.MEDIUM  # 默认
        app._dispatch(action)
        assert app._difficulty == expected

    def test_select_medium_after_easy(self, app: App) -> None:
        app._dispatch(InputAction.SELECT_EASY)
        assert app._difficulty == Difficulty.EASY
        app._dispatch(InputAction.SELECT_MEDIUM)
        assert app._difficulty == Difficulty.MEDIUM


class TestMenuStartNewGame:
    def test_start_opens_game(self, app: App) -> None:
        """UT 12：START → screen=PLAYING + game_state 非 None。"""
        assert app.screen == AppScreen.MENU
        app._dispatch(InputAction.START)
        assert app.screen == AppScreen.PLAYING
        assert app.game_state is not None

    def test_new_game_uses_default_difficulty(self, app: App) -> None:
        app._dispatch(InputAction.START)
        assert app.game_state.difficulty == Difficulty.MEDIUM

    def test_new_game_uses_selected_difficulty(self, app: App) -> None:
        """UT 36：选定难度后 START 用选定难度。"""
        app._dispatch(InputAction.SELECT_HARD)
        app._dispatch(InputAction.START)
        assert app.game_state.difficulty == Difficulty.HARD

    def test_new_game_status_is_run(self, app: App) -> None:
        app._dispatch(InputAction.START)
        assert app.game_state.status == GameStatus.RUN

    def test_new_game_resets_accumulator(self, app: App) -> None:
        app._tick_accumulator_ms = 999
        app._dispatch(InputAction.START)
        assert app._tick_accumulator_ms == 0

    def test_new_game_no_pause_hint_field_in_iter2(self, app: App) -> None:
        """G2-1 INV-8：_pause_hint_shown 字段已删除（PAUSED 是真实屏态）。"""
        assert not hasattr(app, "_pause_hint_shown")

    def test_new_game_accepts_keyword_only(self, app: App) -> None:
        """全关键字构造：位置参数应被 GameState 拒绝。"""
        # _new_game 已正确传关键字；这里确认不抛 TypeError
        app._dispatch(InputAction.START)
        # 已 PLAYING 态说明 OK
        assert app.screen == AppScreen.PLAYING


class TestMenuQuitPropagation:
    def test_dispatch_menu_quit_does_not_set_running_false(self, app: App) -> None:
        """UT 42：_dispatch_menu(QUIT) 后 app._running 不变（主循环外层先 break）。"""
        assert app._running is True
        app._dispatch_menu(InputAction.QUIT)
        # R3-7：dispatch 内不写 self._running = False
        assert app._running is True


class TestDifficultyImmutableInGame:
    """UT 36：难度游戏中不可切换（INV-3）。"""

    def test_select_easy_during_playing_does_not_change_game_difficulty(self, app_in_playing) -> None:
        """_new_game(HARD) 后调 _dispatch(SELECT_EASY) → game_state.difficulty 仍 HARD。

        但 app._difficulty 可能被改写（这是 app 内部状态，非 game_state 不可变字段）。
        核心不变量是 game-core 的 difficulty 字段保持。
        """
        from game_core import Difficulty
        # app_in_playing 是 HARD
        assert app_in_playing.game_state.difficulty == Difficulty.HARD
        app_in_playing._dispatch(InputAction.SELECT_EASY)
        # game-core 的 difficulty 字段不应被改变
        assert app_in_playing.game_state.difficulty == Difficulty.HARD


class TestMenuUnreachableActions:
    """MENU 态 dispatch 收到非保留 action 走防御性忽略（理论上 _drain_events 已处理）。"""

    def test_move_up_ignored_in_menu(self, app: App) -> None:
        """MENU 态 MOVE_UP 走防御性忽略（理论上不会进来）。"""
        app._dispatch(InputAction.MOVE_UP)
        assert app.screen == AppScreen.MENU
        assert app.game_state is None