"""iter-2 返回菜单单测（UT B-1 ~ B-5）。

需求（G2-7 / P1-2 修订）：
- GAME_OVER 态 ESC → BACK_TO_MENU（屏态覆盖）
- GAME_OVER 态 Backspace → BACK_TO_MENU
- GAME_OVER 态 pygame.QUIT → QUIT（不被覆盖）
- GAME_OVER 态 Q 键 → QUIT 直通（不被覆盖）
- MENU 态 ESC 转 START（_MENU_RESERVED_ACTIONS 不含 ESCAPE）
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from game_app import (
    App,
    AppScreen,
    InputAction,
)
from game_core import Difficulty
from .conftest import _PYGAME_KEYS, FakeEvent


def _ev_key(key: str) -> FakeEvent:
    """构造指定键的 KEYDOWN 事件。"""
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], _PYGAME_KEYS[key])


def _ev_quit() -> FakeEvent:
    """构造 pygame.QUIT 事件。"""
    return FakeEvent(_PYGAME_KEYS["QUIT"])


class TestGameOverEscapeGoesToMenu:
    """B-1: GAME_OVER 态 ESC → BACK_TO_MENU。"""

    def test_esc_in_game_over_transitions_to_menu(
        self, app_in_game_over: App, fake_pygame
    ) -> None:
        """B-1：fake_pygame.event.get 注入 KEYDOWN K_ESCAPE → _drain_events → ESCAPE
        被屏态覆盖为 BACK_TO_MENU → _dispatch_over → screen=MENU + game_state is None。
        """
        assert app_in_game_over.screen == AppScreen.GAME_OVER
        # 注入 ESC 事件
        fake_pygame.event.get.return_value = [_ev_key("K_ESCAPE")]

        actions = app_in_game_over._drain_events()
        # _drain_events 在 GAME_OVER 态把 ESCAPE 覆盖为 BACK_TO_MENU
        assert InputAction.BACK_TO_MENU in actions
        assert InputAction.ESCAPE not in actions
        assert InputAction.QUIT not in actions

        # dispatch → 进 MENU
        for a in actions:
            app_in_game_over._dispatch(a)
        assert app_in_game_over.screen == AppScreen.MENU
        assert app_in_game_over.game_state is None  # INV-7


class TestGameOverBackspaceGoesToMenu:
    """B-2: GAME_OVER 态 Backspace → BACK_TO_MENU（_map_event 层直返）。"""

    def test_backspace_in_game_over_transitions_to_menu(
        self, app_in_game_over: App, fake_pygame
    ) -> None:
        """B-2：K_BACKSPACE 注入 → _map_event 直返 BACK_TO_MENU → dispatch → MENU。"""
        assert app_in_game_over.screen == AppScreen.GAME_OVER
        fake_pygame.event.get.return_value = [_ev_key("K_BACKSPACE")]

        actions = app_in_game_over._drain_events()
        assert InputAction.BACK_TO_MENU in actions

        for a in actions:
            app_in_game_over._dispatch(a)
        assert app_in_game_over.screen == AppScreen.MENU


class TestGameOverWindowQuitStaysQuit:
    """B-3: GAME_OVER 态 pygame.QUIT 仍为 QUIT（不被 ESC 屏态覆盖影响）。"""

    def test_window_quit_event_stays_quit(
        self, app_in_game_over: App, fake_pygame
    ) -> None:
        """B-3：pygame.QUIT 事件 → _map_event 返 QUIT（event.type==QUIT 守卫） →
        _drain_events GAME_OVER 态不覆盖（仅 ESCAPE 被覆盖）→ actions 含 [QUIT] 不含 BACK_TO_MENU。
        """
        assert app_in_game_over.screen == AppScreen.GAME_OVER
        fake_pygame.event.get.return_value = [_ev_quit()]

        actions = app_in_game_over._drain_events()
        assert InputAction.QUIT in actions
        assert InputAction.BACK_TO_MENU not in actions


class TestGameOverQKeyStaysQuit:
    """B-4: GAME_OVER 态 Q 键 → QUIT 直通（不被覆盖）。"""

    def test_q_key_in_game_over_stays_quit(
        self, app_in_game_over: App, fake_pygame
    ) -> None:
        """B-4：K_q → _map_event 返 QUIT（P1-2 修订：Q 始终 QUIT 直通）→
        _drain_events GAME_OVER 态不覆盖 → actions 含 [QUIT]。
        """
        assert app_in_game_over.screen == AppScreen.GAME_OVER
        fake_pygame.event.get.return_value = [_ev_key("K_q")]

        actions = app_in_game_over._drain_events()
        assert InputAction.QUIT in actions
        assert InputAction.BACK_TO_MENU not in actions


class TestMenuEscapeStartsGame:
    """B-5: MENU 态 ESC 转 START。"""

    def test_esc_in_menu_starts_game(
        self, app: App, fake_pygame
    ) -> None:
        """B-5：MENU 态 ESC → _map_event 返 ESCAPE（P1-2）→ _drain_events
        MENU 态 ESCAPE 不在 _MENU_RESERVED_ACTIONS → 兜底转 START → 开新局。
        """
        assert app.screen == AppScreen.MENU
        fake_pygame.event.get.return_value = [_ev_key("K_ESCAPE")]

        actions = app._drain_events()
        # MENU 态 ESCAPE 被兜底转 START
        assert InputAction.START in actions
        assert InputAction.ESCAPE not in actions

        for a in actions:
            app._dispatch(a)
        assert app.screen == AppScreen.PLAYING
        assert app.game_state is not None