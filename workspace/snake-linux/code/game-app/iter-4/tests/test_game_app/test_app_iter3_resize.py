"""G3-2 窗口缩放单测（RS-1~RS-7）。

需求：
- _drain_events 注入 VIDEORESIZE → Renderer.handle_resize 调用 + actions 列表不含 RESIZE
- RenderError 兜底（stderr 提示 + 不抛异常）
- PLAYING/PAUSED/GAME_OVER 态缩放不中断（INV-15）
- 同一帧多事件：RESIZE + KEYDOWN → handle_resize 调 + actions 含 QUIT
- 缩放由 renderer 内部完成重绘，app 无需重 render

G3-2：窗口等比缩放（FR-09）
r2-2 契约前置：Renderer 窗口必须带 RESIZABLE 标志（VIDEORESIZE 事件源）；
app 侧无降级路径（由 gui-renderer 模块所有者保证，独立可测）。
"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from game_app import App, InputAction
from game_app.screens import AppScreen
from game_core import Difficulty

from .conftest import FakeEvent, _PYGAME_KEYS, make_resize_event


def _kd(key: str) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], _PYGAME_KEYS[key])


def _set_events(app: App, events) -> None:
    from game_app import app as app_mod
    fake = app_mod.pygame
    fake.event.get.return_value = events


# ============================================================
# RS-1：VIDEORESIZE → handle_resize 调用 + 不入 actions
# ============================================================

class TestResizeEventHandling:
    """G3-2：VIDEORESIZE 事件在 _drain_events 内同步处理。"""

    def test_resize_event_calls_handle_resize(
        self, app: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """RS-1：_drain_events() 注入 [VIDEORESIZE(w=1024, h=768)] → fake_renderer_iter3.handle_resize(1024, 768) 调用 1 次 + actions 列表不含 RESIZE。"""
        ev = make_resize_event(1024, 768)
        _set_events(app, [ev])
        actions = app._drain_events()
        fake_renderer_iter3.handle_resize.assert_called_once_with(1024, 768)
        assert InputAction.RESIZE not in actions

    def test_resize_event_returns_empty_actions(
        self, app: App
    ) -> None:
        """RS-1 辅：单独 RESIZE 事件 → actions 为空（不入 dispatch）。"""
        ev = make_resize_event(800, 600)
        _set_events(app, [ev])
        actions = app._drain_events()
        assert actions == []

    def test_render_error_caught_in_stderr(
        self, app: App, fake_renderer_iter3: MagicMock, capsys
    ) -> None:
        """RS-2：fake_renderer_iter3.handle_resize.side_effect = RenderError("尺寸过小") → _handle_resize 调用 → stderr 写入 + 不抛异常。"""
        from gui_renderer import RenderError
        fake_renderer_iter3.handle_resize.side_effect = RenderError("尺寸过小")
        ev = make_resize_event(100, 100)
        _set_events(app, [ev])
        # 不应抛异常
        actions = app._drain_events()
        # stderr 写入
        captured = capsys.readouterr()
        assert "[警告]" in captured.err
        assert "窗口缩放失败" in captured.err
        # actions 列表为空
        assert actions == []


# ============================================================
# RS-3 / RS-4 / RS-5：PLAYING/PAUSED/GAME_OVER 态缩放不中断（INV-15）
# ============================================================

class TestResizeDoesNotInterrupt:
    """INV-15：缩放不中断游戏（G3-2 兜底语义）。"""

    def test_resize_during_playing_keeps_screen(
        self, app_in_playing: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """RS-3：PLAYING 态 _drain_events 注入 [VIDEORESIZE] → actions 列表不含 RESIZE + handle_resize 调用 + screen==PLAYING 不变（INV-15）。"""
        assert app_in_playing.screen == AppScreen.PLAYING
        ev = make_resize_event(900, 700)
        _set_events(app_in_playing, [ev])
        actions = app_in_playing._drain_events()
        assert InputAction.RESIZE not in actions
        fake_renderer_iter3.handle_resize.assert_called_once_with(900, 700)
        assert app_in_playing.screen == AppScreen.PLAYING  # INV-15

    def test_resize_during_paused_keeps_screen(
        self, app_in_paused: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """RS-4：PAUSED 态缩放不中断。"""
        assert app_in_paused.screen == AppScreen.PAUSED
        ev = make_resize_event(900, 700)
        _set_events(app_in_paused, [ev])
        actions = app_in_paused._drain_events()
        assert InputAction.RESIZE not in actions
        fake_renderer_iter3.handle_resize.assert_called_once_with(900, 700)
        assert app_in_paused.screen == AppScreen.PAUSED

    def test_resize_during_game_over_keeps_screen(
        self, app_in_game_over: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """RS-5：GAME_OVER 态缩放不中断。"""
        assert app_in_game_over.screen == AppScreen.GAME_OVER
        ev = make_resize_event(900, 700)
        _set_events(app_in_game_over, [ev])
        actions = app_in_game_over._drain_events()
        assert InputAction.RESIZE not in actions
        fake_renderer_iter3.handle_resize.assert_called_once_with(900, 700)
        assert app_in_game_over.screen == AppScreen.GAME_OVER


# ============================================================
# RS-6：同一帧多事件：RESIZE + KEYDOWN
# ============================================================

class TestResizeWithOtherEvents:
    """RS-6：同帧多事件混排。"""

    def test_resize_plus_quit(
        self, app: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """RS-6：注入 [VIDEORESIZE, KEYDOWN K_q] → handle_resize 调 1 次 + actions 含 [QUIT]（QUIT 优先 break）。"""
        ev_resize = make_resize_event(1024, 768)
        ev_quit = FakeEvent(_PYGAME_KEYS["QUIT"])
        _set_events(app, [ev_resize, ev_quit])
        actions = app._drain_events()
        fake_renderer_iter3.handle_resize.assert_called_once_with(1024, 768)
        assert InputAction.QUIT in actions
        assert InputAction.RESIZE not in actions


# ============================================================
# RS-7：缩放由 renderer 内部完成重绘，app 无需重 render
# ============================================================

class TestResizeDoesNotTriggerAppRender:
    """RS-7：缩放后 _render 不变（缩放由 renderer 内部完成，app 无需重 render）。"""

    def test_resize_does_not_call_app_render(
        self, app_in_playing: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """RS-7：_drain_events 注入 [VIDEORESIZE] → 下一帧 _render 调用 fake_renderer_iter3.render 与之前一致（缩放由 renderer 内部完成）。"""
        # 先做一次 _render（基线调用次数）
        app_in_playing._render()
        baseline_render_count = fake_renderer_iter3.render.call_count
        # 注入 RESIZE 事件
        ev = make_resize_event(900, 700)
        _set_events(app_in_playing, [ev])
        app_in_playing._drain_events()
        # 下一帧 _render（缩放后）
        app_in_playing._render()
        # 验证缩放**不**触发额外 _render（只应有基线 + 1 次）
        assert fake_renderer_iter3.render.call_count == baseline_render_count + 1
        # 但 handle_resize 应被调 1 次
        fake_renderer_iter3.handle_resize.assert_called_once_with(900, 700)
