"""_map_event 单测（UT 6/7/8/9）。

需求：单键归一化；不感知屏态；未映射键返 None。
"""
from __future__ import annotations

from typing import Optional
import pytest

from game_app.input import _map_event, InputAction, _MENU_RESERVED_ACTIONS
from .conftest import _PYGAME_KEYS, FakeEvent


def _ev(key: str) -> FakeEvent:
    """构造指定键的 KEYDOWN 事件（key 名称 → pygame key 常量）。"""
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], _PYGAME_KEYS[key])


def _evt(type_: str, key: Optional[int] = None) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS[type_], key)


class TestMapEvent:
    # ---- WASD ----
    @pytest.mark.parametrize("key,expected", [
        ("K_w", InputAction.MOVE_UP),
        ("K_s", InputAction.MOVE_DOWN),
        ("K_a", InputAction.MOVE_LEFT),
        ("K_d", InputAction.MOVE_RIGHT),
    ])
    def test_wasd(self, key: str, expected: InputAction, fake_pygame) -> None:
        assert _map_event(_ev(key)) is expected

    # ---- 方向键 ----
    @pytest.mark.parametrize("key,expected", [
        ("K_UP", InputAction.MOVE_UP),
        ("K_DOWN", InputAction.MOVE_DOWN),
        ("K_LEFT", InputAction.MOVE_LEFT),
        ("K_RIGHT", InputAction.MOVE_RIGHT),
    ])
    def test_arrows(self, key: str, expected: InputAction, fake_pygame) -> None:
        assert _map_event(_ev(key)) is expected

    # ---- Q → QUIT；ESC → ESCAPE（P1-2 修订：ESC 独立 action 与 Q 区分）----
    def test_q_key_returns_quit(self, fake_pygame) -> None:
        assert _map_event(_ev("K_q")) is InputAction.QUIT

    def test_esc_key_returns_escape(self, fake_pygame) -> None:
        """P1-2：ESC 在 _map_event 层返 ESCAPE（独立 action，与 Q 区分）。"""
        assert _map_event(_ev("K_ESCAPE")) is InputAction.ESCAPE

    # ---- 难度键 ----
    @pytest.mark.parametrize("key,expected", [
        ("K_1", InputAction.SELECT_EASY),
        ("K_2", InputAction.SELECT_MEDIUM),
        ("K_3", InputAction.SELECT_HARD),
    ])
    def test_difficulty_keys(self, key: str, expected: InputAction, fake_pygame) -> None:
        assert _map_event(_ev(key)) is expected

    # ---- P → TOGGLE_PAUSE / R → RESTART ----
    def test_p_key(self, fake_pygame) -> None:
        assert _map_event(_ev("K_p")) is InputAction.TOGGLE_PAUSE

    def test_r_key(self, fake_pygame) -> None:
        assert _map_event(_ev("K_r")) is InputAction.RESTART

    # ---- G2-3 H → RESET_HIGHSCORE ----
    def test_h_key_returns_reset_highscore(self, fake_pygame) -> None:
        assert _map_event(_ev("K_h")) is InputAction.RESET_HIGHSCORE

    # ---- G2-7 Backspace → BACK_TO_MENU ----
    def test_backspace_key_returns_back_to_menu(self, fake_pygame) -> None:
        assert _map_event(_ev("K_BACKSPACE")) is InputAction.BACK_TO_MENU

    # ---- 未映射键 ----
    def test_unmapped_returns_none(self, fake_pygame) -> None:
        # 任意未映射键（这里用 K_x = 120）→ None
        assert _map_event(FakeEvent(_PYGAME_KEYS["KEYDOWN"], 120)) is None

    def test_quit_event_type_returns_quit(self, fake_pygame) -> None:
        # pygame.QUIT 事件类型（不带 key）
        assert _map_event(_evt("QUIT")) is InputAction.QUIT

    def test_other_event_types_return_none(self, fake_pygame) -> None:
        # 非 KEYDOWN 也非 QUIT → None
        assert _map_event(FakeEvent(999, _PYGAME_KEYS["K_w"])) is None


class TestMenuReservedActions:
    def test_reserved_set_contents(self) -> None:
        assert InputAction.QUIT in _MENU_RESERVED_ACTIONS
        assert InputAction.SELECT_EASY in _MENU_RESERVED_ACTIONS
        assert InputAction.SELECT_MEDIUM in _MENU_RESERVED_ACTIONS
        assert InputAction.SELECT_HARD in _MENU_RESERVED_ACTIONS
        assert InputAction.TOGGLE_PAUSE in _MENU_RESERVED_ACTIONS
        assert InputAction.RESTART in _MENU_RESERVED_ACTIONS
        assert InputAction.MOVE_UP not in _MENU_RESERVED_ACTIONS
        assert InputAction.START not in _MENU_RESERVED_ACTIONS