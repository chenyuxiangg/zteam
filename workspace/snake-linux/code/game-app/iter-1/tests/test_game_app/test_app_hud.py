"""HUD 构造单测（UT 24/25/26/27）。

需求：
- _build_hud(snap) 返 HudData dataclass 含 5 字段
- _high_score 占位 0
- 难度标签中文
- 状态标签 RUN/PAUSED/OVER
"""
from __future__ import annotations

import pytest

from game_app import App, InputAction, _DIFFICULTY_LABEL, _STATUS_LABEL
from gui_renderer import HudData
from game_core import Difficulty, GameStatus, Snapshot, Point, Snake, Food
import dataclasses


def _make_snapshot(status: GameStatus = GameStatus.RUN, score: int = 0) -> Snapshot:
    """构造指定 status/score 的 Snapshot。"""
    return Snapshot(
        snake_body=(Point(0, 0),),
        food=Point(1, 1),
        score=score,
        length=3,
        status=status,
        difficulty=Difficulty.MEDIUM,
        tick_ms=160,
    )


class TestHudStructure:
    def test_build_hud_returns_dataclass(self, app_in_playing: App) -> None:
        """UT 24：_build_hud(snap) 返 HudData。"""
        snap = app_in_playing.game_state.snapshot()
        hud = app_in_playing._build_hud(snap)
        assert isinstance(hud, HudData)

    def test_hud_has_five_fields(self, app_in_playing: App) -> None:
        snap = app_in_playing.game_state.snapshot()
        hud = app_in_playing._build_hud(snap)
        # 5 字段
        assert hasattr(hud, "score")
        assert hasattr(hud, "high_score")
        assert hasattr(hud, "length")
        assert hasattr(hud, "difficulty_label")
        assert hasattr(hud, "status_label")
        # 类型
        assert isinstance(hud.score, int)
        assert isinstance(hud.high_score, int)
        assert isinstance(hud.length, int)
        assert isinstance(hud.difficulty_label, str)
        assert isinstance(hud.status_label, str)


class TestHudHighScore:
    def test_high_score_is_zero(self, app_in_playing: App) -> None:
        """UT 25：_high_score 占位 0（INV-6）。"""
        snap = app_in_playing.game_state.snapshot()
        hud = app_in_playing._build_hud(snap)
        assert hud.high_score == 0


class TestHudDifficultyLabel:
    def test_difficulty_label_chinese(self) -> None:
        """UT 26：难度标签中文。"""
        assert _DIFFICULTY_LABEL[Difficulty.EASY] == "简单"
        assert _DIFFICULTY_LABEL[Difficulty.MEDIUM] == "普通"
        assert _DIFFICULTY_LABEL[Difficulty.HARD] == "困难"

    def test_difficulty_label_in_hud(self, app_in_playing: App) -> None:
        """app_in_playing 用 HARD。"""
        snap = app_in_playing.game_state.snapshot()
        hud = app_in_playing._build_hud(snap)
        assert hud.difficulty_label == "困难"


class TestHudStatusLabel:
    def test_status_label_run(self, app_in_playing: App) -> None:
        """UT 27：status=RUN 时 status_label == "RUN"。"""
        snap = app_in_playing.game_state.snapshot()
        assert snap.status == GameStatus.RUN
        hud = app_in_playing._build_hud(snap)
        assert hud.status_label == "RUN"

    def test_status_label_paused(self) -> None:
        """PAUSED 状态标签。"""
        assert _STATUS_LABEL[GameStatus.PAUSED] == "PAUSED"

    def test_status_label_over(self) -> None:
        """OVER 状态标签。"""
        assert _STATUS_LABEL[GameStatus.OVER] == "OVER"

    def test_hud_status_label_paused(self, app_in_playing: App) -> None:
        """构造一个 PAUSED snapshot 验证 _build_hud。"""
        # PAUSED 不会通过正常路径产生（迭代 1 TOGGLE_PAUSE 不调 toggle_pause）
        # 直接构造 snapshot 验证 _build_hud 接受 PAUSED 状态
        new_state = dataclasses.replace(app_in_playing.game_state, status=GameStatus.PAUSED)
        app_in_playing.game_state = new_state
        snap = app_in_playing.game_state.snapshot()
        assert snap.status == GameStatus.PAUSED
        hud = app_in_playing._build_hud(snap)
        assert hud.status_label == "PAUSED"


class TestHudSnapshotShared:
    """R3-11：_render 共享一次 snap 传给 _build_hud。"""

    def test_build_hud_accepts_snap_argument(self, app_in_playing: App) -> None:
        """_build_hud 必须接受 snap 参数（不能用 self.game_state.snapshot() 内部再次调）。"""
        import inspect
        sig = inspect.signature(app_in_playing._build_hud)
        assert "snap" in sig.parameters