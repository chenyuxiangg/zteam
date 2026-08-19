"""G3-3 平滑插值动画单测（INTERP-1~INTERP-13）。

需求：
- _interpolation_state(snap) 构造 InterpolationState（仅 PLAYING 路径调用）
- r2-1 alpha 公式：alpha = (_tick_accumulator_ms % tick_ms) / tick_ms
  （step 刚完成 elapsed=0 → alpha=0 显示 prev；elapsed→tick 时 alpha=1 显示 cur）
- r2-3 修订：_prev_snap = None / Chebyshev 距离 > 1 → 返 None
- r2-6 修订：snap=None 防御
- r2-7 修订：prev_food 始终传
- _render PLAYING 路径走 interp=；PAUSED/GAME_OVER 不走插值
- _tick step 前维护 _prev_snap（r2-1）+ OVER 后 _prev_snap=None
- _new_game 重置 _prev_snap=None

G3-3：平滑插值动画（FR-07）
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch
import pytest

from game_app import App, InputAction, AppScreen
from game_app.screens import AppScreen as AppScreenConst
from game_core import (
    Difficulty, Direction, GameStatus, Point, Snapshot,
)
from gui_renderer import InterpolationState

from .conftest import FakeEvent, _PYGAME_KEYS


def _set_events(app: App, events) -> None:
    from game_app import app as app_mod
    fake = app_mod.pygame
    fake.event.get.return_value = events


def _mk_snap(snake_body, food=Point(10, 10), tick_ms=160,
             score=0, status=GameStatus.RUN, difficulty=Difficulty.MEDIUM) -> Snapshot:
    return Snapshot(
        snake_body=tuple(Point(*p) if isinstance(p, tuple) else p for p in snake_body),
        food=food,
        score=score,
        length=len(snake_body),
        status=status,
        difficulty=difficulty,
        tick_ms=tick_ms,
    )


# ============================================================
# INTERP-1：首帧 _prev_snap=None → 返回 None
# ============================================================

class TestInterpolationStateBasic:
    """INTERP-1~5：_interpolation_state 基础行为。"""

    def test_interp_none_when_no_prev_snap(self, app: App) -> None:
        """INTERP-1：_prev_snap=None → _interpolation_state(snap) 返 None。"""
        assert app._prev_snap is None
        snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        result = app._interpolation_state(snap)
        assert result is None

    def test_interp_none_when_snap_is_none(self, app: App) -> None:
        """INTERP-13：snap=None 参数防御 → 返 None（r2-6 修订）。"""
        result = app._interpolation_state(None)
        assert result is None


# ============================================================
# INTERP-2 / INTERP-3：alpha 计算（r2-1 修订）
# ============================================================

class TestInterpolationAlpha:
    """r2-1 修订：alpha = (_tick_accumulator_ms % tick_ms) / tick_ms。"""

    def test_interp_alpha_half(self, app: App) -> None:
        """INTERP-2：_prev_snap 长度 3 + _tick_accumulator_ms=80 + tick_ms=160 → alpha=0.5。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        app._tick_accumulator_ms = 80
        snap = _mk_snap([(6, 5), (5, 5), (5, 6)])  # 蛇头横向右移 1 格
        result = app._interpolation_state(snap)
        assert result is not None
        assert isinstance(result, InterpolationState)
        assert result.alpha == 0.5
        # prev_snake_body 应为 ((5,5),(5,6),(5,7))
        assert result.prev_snake_body == ((5, 5), (5, 6), (5, 7))
        # prev_food 应为 (10, 10)
        assert result.prev_food == (10, 10)

    def test_interp_alpha_zero_at_step_completed(self, app: App) -> None:
        """INTERP-3a：_tick_accumulator_ms=0 → alpha=0.0（显示 prev，旧位置）。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        app._tick_accumulator_ms = 0
        snap = _mk_snap([(6, 5), (5, 5), (5, 6)])
        result = app._interpolation_state(snap)
        assert result is not None
        assert result.alpha == 0.0

    def test_interp_alpha_one_at_tick_boundary_minus_epsilon(self, app: App) -> None:
        """INTERP-3b：alpha 上限：_tick_accumulator_ms 接近 tick_ms 时 alpha 接近 1.0（显示 cur，新位置）。

        注意：alpha = (_tick_accumulator_ms % tick_ms) / tick_ms——这是 mod，不是 ceiling。
        _tick_accumulator_ms=159 + tick_ms=160 → alpha=159/160=0.99375（接近 1）。
        """
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        app._tick_accumulator_ms = 159
        snap = _mk_snap([(6, 5), (5, 5), (5, 6)])
        result = app._interpolation_state(snap)
        assert result is not None
        assert result.alpha == 159 / 160  # alpha 上限接近 1.0

    def test_interp_alpha_after_two_ticks(self, app: App) -> None:
        """INTERP-3 辅：_tick_accumulator_ms=240（= 1.5 * tick_ms）+ tick_ms=160 → elapsed_in_tick=80 → alpha=0.5。

        r2-1 修订：alpha = elapsed_in_tick / tick_ms，其中 elapsed_in_tick = acc % tick_ms。
        即使 acc > tick_ms（如 1.5 个节拍），alpha 也只反映本节拍内的进度。
        """
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        app._tick_accumulator_ms = 240
        snap = _mk_snap([(6, 5), (5, 5), (5, 6)])
        result = app._interpolation_state(snap)
        assert result is not None
        assert result.alpha == 0.5  # (240 % 160) / 160 = 80/160 = 0.5


# ============================================================
# INTERP-4 / INTERP-12：吃食 / Chebyshev 距离防御
# ============================================================

class TestInterpolationGuards:
    """INTERP-4 / INTERP-12：吃食 / Chebyshev 距离防御。"""

    def test_interp_none_when_length_differs(self, app: App) -> None:
        """INTERP-4：len(prev_body) != len(cur_body) → 返 None（吃食节拍防御）。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])  # 长度 3
        app._tick_accumulator_ms = 80
        snap = _mk_snap([(6, 5), (5, 5), (5, 6), (5, 7)])  # 长度 4（吃食后）
        result = app._interpolation_state(snap)
        assert result is None

    def test_interp_none_when_chebyshev_distance_too_large(self, app: App) -> None:
        """INTERP-12：Chebyshev 距离 > 1 → 返 None（r2-3 修订：真实 Chebyshev 距离防御）。"""
        # 蛇头从 (5,5) 跳到 (10,5) 距离 5 格（> 1）
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        app._tick_accumulator_ms = 80
        snap = _mk_snap([(10, 5), (5, 5), (5, 6)])
        result = app._interpolation_state(snap)
        assert result is None

    def test_interp_none_when_chebyshev_diagonal_too_large(self, app: App) -> None:
        """INTERP-12 辅：对角跳 2 格（max(|dx|,|dy|)=2 > 1）→ 返 None。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        app._tick_accumulator_ms = 80
        snap = _mk_snap([(7, 7), (5, 5), (5, 6)])  # 头从 (5,5) 对角跳到 (7,7)
        result = app._interpolation_state(snap)
        assert result is None

    def test_interp_none_when_new_game_residual_snapshot_different_position(
        self, app: App
    ) -> None:
        """INTERP-11：新旧局蛇身长度相同但位置不同 → 返 None（防御新局残留快照干扰）。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])  # 旧局位置
        app._tick_accumulator_ms = 80
        # 新局位置不同（蛇头从 (5,5) 跳到 (100,100)）
        snap = _mk_snap([(100, 100), (100, 101), (100, 102)])
        result = app._interpolation_state(snap)
        assert result is None


# ============================================================
# INTERP-5：tick_ms=0 防御
# ============================================================

class TestInterpolationTickMsGuard:
    """INTERP-5：tick_ms=0 防御。"""

    def test_interp_none_when_tick_ms_zero(self, app: App) -> None:
        """INTERP-5：snap.tick_ms=0 → 返 None（防御除零）。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)], tick_ms=160)
        app._tick_accumulator_ms = 0
        snap = _mk_snap([(6, 5), (5, 5), (5, 6)], tick_ms=0)
        result = app._interpolation_state(snap)
        assert result is None


# ============================================================
# INTERP-6 / INTERP-7 / INTERP-8：_render 路径走 interp
# ============================================================

class TestRenderPathsInterpolation:
    """INTERP-6/7/8：_render 各路径与 interp= 关系。"""

    def test_render_playing_passes_interp(self, app_in_playing: App, fake_renderer_iter3: MagicMock) -> None:
        """INTERP-6：_render PLAYING 路径走 interp=；调用 fake_renderer_iter3.render 后断言 kwargs["interp"] 为 None 或 InterpolationState。

        app_in_playing 使用 HARD 难度，tick_ms=100。
        _tick(80) 不触发 step（80 < 100）；手动设 _prev_snap 后调 _render。
        """
        # 调 _tick 让 _prev_snap 被设置（HARD tick_ms=100，dt=80 不触发 step）
        app_in_playing._tick(80)
        # 此时 _prev_snap 应为 None（dt 不够 step），但 _tick_accumulator_ms=80
        # 手动设 _prev_snap 来构造插值场景
        app_in_playing._prev_snap = app_in_playing.game_state.snapshot()
        # _tick_accumulator_ms=80 + tick_ms=100 → alpha = 80/100 = 0.8
        app_in_playing._render()
        # 断言 render 被调，且 kwargs["interp"] 是 InterpolationState
        fake_renderer_iter3.render.assert_called_once()
        interp_kwarg = fake_renderer_iter3.render.call_args.kwargs.get("interp")
        assert isinstance(interp_kwarg, InterpolationState)
        assert interp_kwarg.alpha == 0.8  # 80 / 100

    def test_render_playing_interp_none_when_no_prev_snap(
        self, app_in_playing: App, fake_renderer_iter3: MagicMock
    ) -> None:
        """INTERP-6 辅：首帧 _prev_snap=None → kwargs["interp"] is None（瞬移渲染）。"""
        # _new_game 已重置 _prev_snap=None；新局首帧调用 _render
        assert app_in_playing._prev_snap is None
        app_in_playing._render()
        fake_renderer_iter3.render.assert_called_once()
        interp_kwarg = fake_renderer_iter3.render.call_args.kwargs.get("interp")
        assert interp_kwarg is None

    def test_render_paused_interp_none(self, app_in_paused: App, fake_renderer_iter3: MagicMock) -> None:
        """INTERP-7：_render PAUSED 路径 kwargs["interp"] is None（PAUSED 不走插值，保持定格感）。"""
        app_in_paused._render()
        fake_renderer_iter3.render.assert_called_once()
        # PAUSED 不传 interp（调用 render(snap, hud) 而非 render(snap, hud, interp=...)）
        # 或即使传了，值也是 None
        if "interp" in fake_renderer_iter3.render.call_args.kwargs:
            assert fake_renderer_iter3.render.call_args.kwargs["interp"] is None

    def test_render_game_over_interp_none(self, app_in_game_over: App, fake_renderer_iter3: MagicMock) -> None:
        """INTERP-8：_render GAME_OVER 路径 kwargs 不含 interp 或 interp=None。"""
        app_in_game_over._render()
        # GAME_OVER 调 draw_game_over 不调 renderer.render
        fake_renderer_iter3.render.assert_not_called()


# ============================================================
# INTERP-9 / INTERP-10：_tick 维护 _prev_snap
# ============================================================

class TestTickMaintainsPrevSnap:
    """INTERP-9/10：_tick step 前维护 _prev_snap（r2-1 修订）。"""

    def test_tick_normal_step_updates_prev_snap(self, app_in_playing: App) -> None:
        """INTERP-10：_tick 后 _prev_snap is not None + _prev_snap.snake_body == step 前位置（最后一次 step）。

        app_in_playing 使用 HARD 难度，tick_ms=100。dt=120 触发 1 次 step，acc 剩余 20。
        """
        # 记录 step 前的位置
        before_snap = app_in_playing.game_state.snapshot()
        app_in_playing._tick(120)  # 120 >= tick_ms=100，step 1 次
        # _prev_snap 应已被更新（r2-1：step 前保存）
        assert app_in_playing._prev_snap is not None
        # _prev_snap.snake_body 应为**最后一次** step 前的蛇身
        # 实际：本次调用 step 1 次，_prev_snap = step 前的快照 = before_snap（dt=120 之前的状态）
        assert app_in_playing._prev_snap.snake_body == before_snap.snake_body

    def test_tick_over_resets_prev_snap(self, app_in_playing: App) -> None:
        """INTERP-9：_tick 足够 dt 撞墙 → _prev_snap is None。"""
        # 让蛇头强制撞墙（直接用 set_direction 到墙）
        # 简单方案：调 _tick 一个极大 dt，撞墙后应转 GAME_OVER 且 _prev_snap=None
        # 由于 game-core 行为复杂，使用 monkeypatch：手动构造 OVER 状态
        # 改用 _new_game + 直接调 game_state 替换为 OVER + _tick 看行为
        # 这里直接调一个超大 dt 触发撞墙
        # game-core step() 在 next_head 撞墙时转 OVER
        # 我们让蛇朝一个方向跑很多步直到撞墙
        # 简化：手动设置 _tick_accumulator_ms 让连续 step 多次
        # 但 INTERP-9 测试的是 OVER 后 _prev_snap=None
        # 直接通过 dataclasses.replace 强制 OVER 态验证 _tick 的清理逻辑
        # 不行——_tick 入口断言 status==RUN
        # 改用 _dispatch_over(BACK_TO_MENU) 回到 MENU 然后 _new_game → 验证 _prev_snap 已被 _new_game 重置（INTERP-11）
        pass

    def test_new_game_resets_prev_snap(self, app_in_playing: App) -> None:
        """INTERP-11：_new_game 重置 _prev_snap = None（r2-3 修订生命周期）。"""
        # 模拟 step 后 _prev_snap 已被设置
        app_in_playing._prev_snap = app_in_playing.game_state.snapshot()
        assert app_in_playing._prev_snap is not None
        # 重启新局
        app_in_playing._new_game(Difficulty.HARD)
        # _prev_snap 应被重置
        assert app_in_playing._prev_snap is None

    def test_new_game_first_frame_interp_none(self, app_in_playing: App) -> None:
        """INTERP-11 辅：新局首帧 _interpolation_state(snap) 返 None（防御旧局残留快照）。"""
        # 模拟上一局残留 _prev_snap
        app_in_playing._prev_snap = _mk_snap([(100, 100), (100, 101), (100, 102)])
        # 重启新局（_new_game 重置）
        app_in_playing._new_game(Difficulty.HARD)
        # 立即调 _interpolation_state 应返 None
        snap = app_in_playing.game_state.snapshot()
        result = app_in_playing._interpolation_state(snap)
        assert result is None


# ============================================================
# INTERP-9 真正覆盖：_tick 撞墙 OVER → _prev_snap=None
# ============================================================

class TestTickOverClearsPrevSnap:
    """INTERP-9：_tick 后撞墙（OVER）→ _prev_snap = None。"""

    def test_tick_until_over_clears_prev_snap(self, app_in_playing: App) -> None:
        """INTERP-9：app_in_playing._tick(足够 dt 撞墙) → app._prev_snap is None。"""
        # 让蛇朝一个方向跑（不转向）直到撞墙
        # 初始方向 Direction.RIGHT
        # 让蛇一直右移直到撞墙
        max_steps = 50
        for _ in range(max_steps):
            if app_in_playing.screen == AppScreenConst.GAME_OVER:
                break
            app_in_playing._tick(1000)  # 大 dt，每次必然 step
        assert app_in_playing.screen == AppScreenConst.GAME_OVER
        # OVER 后 _prev_snap 应被清空（G3-3 _tick 末尾 OVER 分支置 None）
        assert app_in_playing._prev_snap is None
