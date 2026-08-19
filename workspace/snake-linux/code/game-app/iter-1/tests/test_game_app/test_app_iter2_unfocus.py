"""iter-2 窗口失焦自动暂停单测（UT U-1 ~ U-6）。

需求（G2-4）：
- PLAYING 态失焦 → _drain_events 追加 UNFOCUS
- MENU / PAUSED / GAME_OVER 态失焦 → 不追加 UNFOCUS
- 失焦检测函数抛异常 → 兜底为 True（headless）
- 聚焦恢复不自动继续（需 P 键）
"""
from __future__ import annotations

import pytest

from game_app import (
    App,
    AppScreen,
    InputAction,
)
from game_core import GameStatus


class TestUnfocusInPlaying:
    """U-1: PLAYING 态失焦 → UNFOCUS。"""

    def test_playing_unfocus_appends_unfocus(
        self, app_in_playing: App, fake_pygame
    ) -> None:
        """U-1：fake_pygame.key.get_focused()=False → _drain_events 含 UNFOCUS。"""
        fake_pygame.key.get_focused.return_value = False
        actions = app_in_playing._drain_events()
        assert InputAction.UNFOCUS in actions

    def test_unfocus_in_playing_transitions_to_paused(
        self, app_in_playing: App, fake_pygame
    ) -> None:
        """U-1 扩展：UNFOCUS dispatch → screen==PAUSED。"""
        fake_pygame.key.get_focused.return_value = False
        actions = app_in_playing._drain_events()
        assert InputAction.UNFOCUS in actions
        # 模拟主循环 dispatch
        for a in actions:
            app_in_playing._dispatch(a)
        assert app_in_playing.screen == AppScreen.PAUSED


class TestUnfocusIgnoredInMenu:
    """U-2: MENU 态失焦不变。"""

    def test_menu_unfocus_does_not_append(
        self, app: App, fake_pygame
    ) -> None:
        """U-2：app.screen==MENU + get_focused=False → _drain_events 不含 UNFOCUS。"""
        assert app.screen == AppScreen.MENU
        fake_pygame.key.get_focused.return_value = False
        actions = app._drain_events()
        assert InputAction.UNFOCUS not in actions


class TestUnfocusIgnoredInPaused:
    """U-3: PAUSED 态失焦不变。"""

    def test_paused_unfocus_does_not_append(
        self, app_in_paused: App, fake_pygame
    ) -> None:
        """U-3：app_in_paused（screen=PAUSED）+ get_focused=False → 不含 UNFOCUS。"""
        assert app_in_paused.screen == AppScreen.PAUSED
        fake_pygame.key.get_focused.return_value = False
        actions = app_in_paused._drain_events()
        assert InputAction.UNFOCUS not in actions


class TestUnfocusIgnoredInGameOver:
    """U-4: GAME_OVER 态失焦不变。"""

    def test_game_over_unfocus_does_not_append(
        self, app_in_game_over: App, fake_pygame
    ) -> None:
        """U-4：app_in_game_over + get_focused=False → 不含 UNFOCUS。"""
        assert app_in_game_over.screen == AppScreen.GAME_OVER
        fake_pygame.key.get_focused.return_value = False
        actions = app_in_game_over._drain_events()
        assert InputAction.UNFOCUS not in actions


class TestUnfocusExceptionFallback:
    """U-5: 失焦检测函数抛异常 → 兜底为 True（headless 环境）。"""

    def test_unfocus_exception_falls_back_to_focused(
        self, app_in_playing: App, fake_pygame
    ) -> None:
        """U-5：fake_pygame.key.get_focused.side_effect=Exception → _drain_events 不含 UNFOCUS。"""
        fake_pygame.key.get_focused.side_effect = Exception("headless")
        actions = app_in_playing._drain_events()
        assert InputAction.UNFOCUS not in actions


class TestFocusRecoveryDoesNotAutoResume:
    """U-6: 聚焦恢复不自动继续（需 P 键）。"""

    def test_focused_in_paused_does_not_append_unfocus(
        self, app_in_paused: App, fake_pygame
    ) -> None:
        """U-6：app_in_paused + get_focused=True → 不含 UNFOCUS（不自动恢复）。"""
        assert app_in_paused.screen == AppScreen.PAUSED
        fake_pygame.key.get_focused.return_value = True
        actions = app_in_paused._drain_events()
        assert InputAction.UNFOCUS not in actions
        # 屏态应仍为 PAUSED（聚焦恢复未触发）
        assert app_in_paused.screen == AppScreen.PAUSED

    def test_focused_in_playing_does_not_append_unfocus(
        self, app_in_playing: App, fake_pygame
    ) -> None:
        """U-6 旁路：PLAYING + get_focused=True → 不含 UNFOCUS。"""
        fake_pygame.key.get_focused.return_value = True
        actions = app_in_playing._drain_events()
        assert InputAction.UNFOCUS not in actions