"""_tick 节拍推进单测（UT 19/19a/20/37）。

需求：
- R3-8：循环内重读 tick_ms（吃食加速即时生效）
- 节拍不漂移（HARD 100ms / MEDIUM 160ms）
- 一帧多次 step（节拍追跑）
- _tick(0) 边界
"""
from __future__ import annotations

from unittest.mock import patch
import pytest

from game_app import App, InputAction
from game_app.screens import AppScreen
from game_core import Difficulty, GameStatus, GameState
import dataclasses


def _head_x(app: App) -> int:
    return app.game_state.snake.head.x


class TestTickBasicBoundary:
    def test_tick_zero_no_step(self, app: App) -> None:
        """UT 37：_tick(0) → step 调 0 次（蛇头位置不变）。"""
        app._difficulty = Difficulty.MEDIUM
        app._new_game(Difficulty.MEDIUM)
        before = _head_x(app)
        app._tick(0)
        assert _head_x(app) == before  # 未推进

    def test_tick_exactly_one_step_medium(self, app: App) -> None:
        """UT 37：_tick(160) 恰好调 1 次 step（MEDIUM，蛇头 +1）。"""
        app._difficulty = Difficulty.MEDIUM
        app._new_game(Difficulty.MEDIUM)
        before = _head_x(app)
        app._tick(160)
        # 1 步：蛇头 (10,7) → (11,7)
        assert _head_x(app) == before + 1
        assert app._tick_accumulator_ms == 0


class TestTickDoesNotDrift:
    """UT 19：节拍不漂移（每次 step 后重读 tick_ms）。"""

    def test_three_50ms_ticks_medium_no_step(self, app: App) -> None:
        """UT 19：MEDIUM 160ms × 3 次 _tick(50) → step 调 0 次（累加器 < 160）。"""
        app._difficulty = Difficulty.MEDIUM
        app._new_game(Difficulty.MEDIUM)
        before = _head_x(app)
        # 累加器变化：50+50+50 = 150 < 160 → 0 次 step
        app._tick(50)
        assert app._tick_accumulator_ms == 50
        app._tick(50)
        assert app._tick_accumulator_ms == 100
        app._tick(50)
        assert app._tick_accumulator_ms == 150
        # game_state 仍未推进（head.x 未变）
        assert _head_x(app) == before
        assert app.game_state.status == GameStatus.RUN

    def test_accumulator_breaks_at_tick(self, app: App) -> None:
        """UT 19：_tick(170) 一次 → step 调 1 次；累加器为 10。"""
        app._difficulty = Difficulty.MEDIUM
        app._new_game(Difficulty.MEDIUM)
        before = _head_x(app)
        # 170ms → step 1 次（160ms），剩余 10ms
        app._tick(170)
        assert _head_x(app) == before + 1
        assert app._tick_accumulator_ms == 10
        assert app.game_state.status == GameStatus.RUN


class TestTickMultipleStepsPerFrame:
    """UT 20：节拍追跑（一帧多次 step）。"""

    def test_500ms_hard_5_steps(self, app: App) -> None:
        """UT 20：HARD 100ms × _tick(500) → step 调 5 次；累加器为 0。"""
        app._difficulty = Difficulty.HARD
        app._new_game(Difficulty.HARD)
        before = _head_x(app)
        # 蛇头初始 (10, 7) direction=RIGHT，撞墙需 head.x >= 20，10 步撞墙
        # 500ms / 100ms = 5 步，head → (15, 7) 仍 RUN（5 < 10）
        app._tick(500)
        assert _head_x(app) == before + 5
        assert app._tick_accumulator_ms == 0
        assert app.game_state.status == GameStatus.RUN


class TestTickTransitionsOnOver:
    """_tick 在 step 后遇到 OVER 自动转 GAME_OVER。"""

    def test_wall_collision_during_tick(self, app: App) -> None:
        """撞墙 + tick → status=OVER + screen=GAME_OVER。"""
        app._difficulty = Difficulty.HARD
        app._new_game(Difficulty.HARD)
        # 蛇头 (10,7) 向 RIGHT，HARD tick_ms=100。1100ms / 100ms = 11 步（10 步撞墙 OVER break）
        app._tick(1100)
        assert app.game_state.status == GameStatus.OVER
        assert app.screen == AppScreen.GAME_OVER


class TestTickRereadTickMs:
    """UT 19a：R3-8 循环内重读 tick_ms。

    验证 tick_ms 在 step 之间会被重读（吃食加速即时生效）。
    """

    def test_speed_curve_adapts_to_score(self, app: App) -> None:
        """MEDIUM speed_curve：score=0 → 160ms；score=10 → 120ms。

        验证 _tick 使用最新 tick_ms 而非帧首快照：把 score 改到 10 后 _tick(120) 应 1 步而非 0 步。
        """
        app._difficulty = Difficulty.MEDIUM
        app._new_game(Difficulty.MEDIUM)
        # score=10 → tick_ms = max(80, 160 - 4*10) = 120
        new_state = dataclasses.replace(app.game_state, score=10)
        app.game_state = new_state
        before = _head_x(app)
        # _tick(120) → step 1 次（120ms），累加器 0
        app._tick(120)
        assert _head_x(app) == before + 1
        assert app._tick_accumulator_ms == 0

    def test_speed_curve_adapts_at_floor(self, app: App) -> None:
        """MEDIUM floor=80ms：score=20 → tick_ms=80；_tick(80) 调 1 步。"""
        app._difficulty = Difficulty.MEDIUM
        app._new_game(Difficulty.MEDIUM)
        new_state = dataclasses.replace(app.game_state, score=20)
        app.game_state = new_state
        before = _head_x(app)
        # tick_ms = max(80, 160-80) = 80
        app._tick(80)
        assert _head_x(app) == before + 1
        assert app._tick_accumulator_ms == 0


class TestTickNoOpWhenNotPlaying:
    """_tick 仅在 PLAYING 态执行；其他屏态不调 step。"""

    def test_tick_in_menu_raises_assertion(self, app: App) -> None:
        """MENU 态 _tick 不应被调（设计要求 assert screen==PLAYING）。"""
        assert app.screen == AppScreen.MENU
        assert app.game_state is None
        # 主循环不调；直接调会 assert
        with pytest.raises(AssertionError):
            app._tick(100)