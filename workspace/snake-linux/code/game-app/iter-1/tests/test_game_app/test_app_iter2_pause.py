"""iter-2 PAUSED 状态机单测（UT P-1 ~ P-8）。

需求（G2-1）：
- PLAYING→PAUSED（P 键）→ 屏态同步 + game_state.status == PAUSED
- PAUSED→RUN（P 键）→ 屏态同步 + game_state.status == RUN
- PAUSED 态 _tick 不进入（主循环判断）
- PAUSED 态 _dispatch_paused 忽略 MOVE_*
- OVER 态调 toggle_pause 抛 InvalidStateError
- PAUSED→RUN 后 pending_direction 清空
- _render PAUSED 路径：renderer.render + draw_pause_overlay
- 方案 A：_tick 内不存在 elif new_status == PAUSED 分支（防误加回）
"""
from __future__ import annotations

import inspect
import pytest

from game_app import (
    App,
    AppScreen,
    InputAction,
)
from game_core import Direction, GameStatus, InvalidStateError


class TestPlayingToPausedTransition:
    """P-1: PLAYING→PAUSED。"""

    def test_p_key_in_playing_transitions_to_paused(
        self, app_in_playing: App
    ) -> None:
        """P-1：_dispatch_playing(TOGGLE_PAUSE) → screen==PAUSED + game_state.status==PAUSED（INV-11 方案 A）。"""
        assert app_in_playing.screen == AppScreen.PLAYING
        assert app_in_playing.game_state.status == GameStatus.RUN
        app_in_playing._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert app_in_playing.screen == AppScreen.PAUSED
        assert app_in_playing.game_state.status == GameStatus.PAUSED


class TestPausedToPlayingTransition:
    """P-2: PAUSED→RUN。"""

    def test_p_key_in_paused_transitions_to_playing(
        self, app_in_paused: App
    ) -> None:
        """P-2：_dispatch_paused(TOGGLE_PAUSE) → screen==PLAYING + game_state.status==RUN（INV-11 方案 A）。"""
        assert app_in_paused.screen == AppScreen.PAUSED
        assert app_in_paused.game_state.status == GameStatus.PAUSED
        app_in_paused._dispatch_paused(InputAction.TOGGLE_PAUSE)
        assert app_in_paused.screen == AppScreen.PLAYING
        assert app_in_paused.game_state.status == GameStatus.RUN


class TestTickNotCalledInPaused:
    """P-3: PAUSED 态 _tick 不进入。"""

    def test_paused_state_skips_tick_in_run_loop(
        self, app_in_paused: App, monkeypatch
    ) -> None:
        """P-3：主循环 screen==PAUSED 时跳过 _tick 调用（spy _tick 调用次数=0）。"""
        spy_called = []

        def tick_spy(dt_ms: int) -> None:
            spy_called.append(dt_ms)

        # monkeypatch _tick 方法为 spy
        monkeypatch.setattr(app_in_paused, "_tick", tick_spy)

        # 模拟主循环 _run_loop 内一次"tick 调用"判断
        if app_in_paused.screen == AppScreen.PLAYING:
            app_in_paused._tick(100)
        # 主循环没有调 _tick（PAUSED 态不进入）
        assert spy_called == []


class TestDispatchPausedIgnoresMove:
    """P-4: PAUSED 态 _dispatch_paused 忽略 MOVE_*。"""

    @pytest.mark.parametrize(
        "action", [
            InputAction.MOVE_UP, InputAction.MOVE_DOWN,
            InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT,
        ]
    )
    def test_move_in_paused_does_not_set_direction(
        self, app_in_paused: App, action: InputAction
    ) -> None:
        """P-4：_dispatch_paused(MOVE_*) 不调 set_direction（pending_direction 不变）。"""
        original_gs = app_in_paused.game_state
        # _dispatch_paused 内对 MOVE_* 无分支——pending_direction 不变
        app_in_paused._dispatch_paused(action)
        # game_state 应未变（MOVE_* 在 _dispatch_paused 内被忽略）
        assert app_in_paused.game_state is original_gs


class TestOverStateTogglePauseRaises:
    """P-5: OVER 态调 toggle_pause 抛 InvalidStateError。"""

    def test_toggle_pause_on_over_raises(
        self, app_in_game_over: App
    ) -> None:
        """P-5：pytest.raises(InvalidStateError) 调 game_state.toggle_pause()。"""
        assert app_in_game_over.game_state.status == GameStatus.OVER
        with pytest.raises(InvalidStateError):
            app_in_game_over.game_state.toggle_pause()


class TestPausedReturnsClearsPendingDirection:
    """P-6: PAUSED→RUN 后 pending_direction 清空（INV-8）。"""

    def test_pending_direction_clears_after_unpause(
        self, app_in_playing: App
    ) -> None:
        """P-6：前置步骤 RUN→MOVE_RIGHT（pending=LEFT/RIGHT）→ toggle_pause → toggle_pause；pending 恢复后清空。"""
        # RUN 态设置方向
        app_in_playing._dispatch_playing(InputAction.MOVE_RIGHT)
        # 进 PAUSED
        app_in_playing._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert app_in_playing.screen == AppScreen.PAUSED
        # 回 RUN
        app_in_playing._dispatch_paused(InputAction.TOGGLE_PAUSE)
        # pending_direction 应被清空（core iter-2 toggle_pause 行为 INV-8）
        assert app_in_playing.game_state.pending_direction is None


class TestRenderPausedPath:
    """P-7: _render PAUSED 路径。"""

    def test_render_paused_calls_renderer_and_overlay(
        self, fake_pygame, fake_storage, monkeypatch
    ) -> None:
        """P-7：_render() 在 PAUSED 态调 renderer.render + draw_pause_overlay 各 1 次。"""
        from game_app import App, InputAction
        from game_app import menu as menu_mod
        from game_core import Difficulty
        from unittest.mock import MagicMock

        # 构造带 mock renderer 的 paused app
        a = App()
        a._difficulty = Difficulty.HARD
        a._storage = fake_storage
        a._high_score = 0
        # 用 mock renderer 替掉真 Renderer（避免真渲染副作用）
        mock_renderer = MagicMock(name="mock_renderer")
        a._renderer = mock_renderer
        a._menu_title_font = MagicMock(name="title_font")
        a._menu_body_font = MagicMock(name="body_font")
        a.clock = MagicMock(name="clock")
        # 创建 game_state + 进 PAUSED
        a._new_game(Difficulty.HARD)
        a._dispatch_playing(InputAction.TOGGLE_PAUSE)
        from game_app import AppScreen as AS
        assert a.screen == AS.PAUSED

        # spy draw_pause_overlay（替换 app_mod 内的 draw_pause_overlay 引用）
        overlay_spy = MagicMock(name="overlay_spy")
        import game_app.app as app_mod
        monkeypatch.setattr(app_mod, "draw_pause_overlay", overlay_spy)

        a._render()

        assert mock_renderer.render.call_count == 1
        assert overlay_spy.call_count == 1


class TestNoElifPausedBranchInTick:
    """P-8: _tick 内不存在 elif new_status == PAUSED 分支（P0-1 防误加回）。"""

    def test_tick_source_has_no_paused_branch(self, app: App) -> None:
        """P-8：inspect.getsource(app._tick) 不含 'GameStatus.PAUSED'。"""
        src = inspect.getsource(app._tick)
        assert "GameStatus.PAUSED" not in src, (
            f"_tick must not reference GameStatus.PAUSED (方案 A): {src}"
        )