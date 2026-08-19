"""_map_event 单测（迭代 3 增量：G3-1/G3-2）。

需求：
- 单键归一化；不感知屏态；未映射键返 None
- G3-1：K_LEFT → SET_SKIN_PREV；K_RIGHT → SET_SKIN_NEXT（在 _drain_events 内按屏态分发）
- G3-2：VIDEORESIZE 事件 → RESIZE（_drain_events 内同步处理）
- K_a/K_d 始终为 MOVE_LEFT/MOVE_RIGHT（避免 WASD 用户意外触发皮肤切换）

输入总成员数 = 18（iter-2 15 + iter-3 3）：
  QUIT/START/MOVE_UP/MOVE_DOWN/MOVE_LEFT/MOVE_RIGHT/TOGGLE_PAUSE/RESTART
  /SELECT_EASY/SELECT_MEDIUM/SELECT_HARD/RESET_HIGHSCORE/BACK_TO_MENU/ESCAPE/UNFOCUS
  +SET_SKIN_PREV/SET_SKIN_NEXT/RESIZE
"""
from __future__ import annotations

from typing import Optional
import pytest

from game_app.input import _map_event, InputAction, _MENU_RESERVED_ACTIONS
from .conftest import _PYGAME_KEYS, FakeEvent


def _ev(key: str) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], _PYGAME_KEYS[key])


def _evt(type_: str, key: Optional[int] = None) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS[type_], key)


class TestMapEventIter3SkinKeys:
    """G3-1：方向键 → SET_SKIN_PREV/SET_SKIN_NEXT（在 _drain_events 内按屏态分发）。"""

    def test_left_arrow_returns_set_skin_prev(self, fake_pygame) -> None:
        """G3-1：← 键 → SET_SKIN_PREV。"""
        assert _map_event(_ev("K_LEFT")) is InputAction.SET_SKIN_PREV

    def test_right_arrow_returns_set_skin_next(self, fake_pygame) -> None:
        """G3-1：→ 键 → SET_SKIN_NEXT。"""
        assert _map_event(_ev("K_RIGHT")) is InputAction.SET_SKIN_NEXT

    def test_k_a_returns_move_left_not_skin(self, fake_pygame) -> None:
        """G3-1：K_a 保持 MOVE_LEFT（不映射 SET_SKIN_PREV），避免 WASD 用户意外触发。"""
        assert _map_event(_ev("K_a")) is InputAction.MOVE_LEFT

    def test_k_d_returns_move_right_not_skin(self, fake_pygame) -> None:
        """G3-1：K_d 保持 MOVE_RIGHT（不映射 SET_SKIN_NEXT）。"""
        assert _map_event(_ev("K_d")) is InputAction.MOVE_RIGHT

    def test_k_up_returns_move_up_not_skin(self, fake_pygame) -> None:
        """G3-1：K_UP 保持 MOVE_UP。"""
        assert _map_event(_ev("K_UP")) is InputAction.MOVE_UP

    def test_k_down_returns_move_down_not_skin(self, fake_pygame) -> None:
        """G3-1：K_DOWN 保持 MOVE_DOWN。"""
        assert _map_event(_ev("K_DOWN")) is InputAction.MOVE_DOWN


class TestMapEventIter3ResizeEvent:
    """G3-2：VIDEORESIZE 事件 → RESIZE（在 _drain_events 内同步处理）。"""

    def test_videoresize_event_returns_resize(self, fake_pygame) -> None:
        """G3-2：pygame.VIDEORESIZE 事件类型 → RESIZE。"""
        ev = FakeEvent(_PYGAME_KEYS["VIDEORESIZE"], w=1024, h=768)
        assert _map_event(ev) is InputAction.RESIZE


class TestInputActionCount:
    """r2-5 修订：InputAction 成员总数 = 18（iter-2 15 + iter-3 3）。"""

    def test_total_member_count_is_18(self) -> None:
        assert len(InputAction) == 18

    def test_skin_actions_exist(self) -> None:
        """G3-1：SET_SKIN_PREV/SET_SKIN_NEXT 在 InputAction 中。"""
        assert hasattr(InputAction, "SET_SKIN_PREV")
        assert hasattr(InputAction, "SET_SKIN_NEXT")
        assert InputAction.SET_SKIN_PREV.value == "skin_prev"
        assert InputAction.SET_SKIN_NEXT.value == "skin_next"

    def test_resize_action_exists(self) -> None:
        """G3-2：RESIZE 在 InputAction 中。"""
        assert hasattr(InputAction, "RESIZE")
        assert InputAction.RESIZE.value == "resize"
