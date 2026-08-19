"""App 构造 + AppScreen 状态机 init 单测（UT 1）。

需求：构造 App 不开窗、不调 pygame.init、不构造 Renderer；_renderer is None。
"""
from __future__ import annotations

from game_app import App, AppScreen, AppConfig
from game_core import Difficulty


class TestAppInit:
    def test_initial_screen_is_menu(self, app: App) -> None:
        assert app.screen == AppScreen.MENU

    def test_initial_difficulty_is_medium(self, app: App) -> None:
        assert app._difficulty == Difficulty.MEDIUM

    def test_initial_high_score_is_zero(self, app: App) -> None:
        assert app._high_score == 0

    def test_renderer_is_none_at_init(self, app_uninitialized: App) -> None:
        """R3-10：App.__init__ 不构造 Renderer。"""
        assert app_uninitialized._renderer is None

    def test_game_state_is_none_at_init(self, app_uninitialized: App) -> None:
        assert app_uninitialized.game_state is None

    def test_running_is_true_at_init(self, app_uninitialized: App) -> None:
        """R3-5：_running 主循环退出标志，初始 True。"""
        assert app_uninitialized._running is True

    def test_tick_accumulator_is_zero(self, app_uninitialized: App) -> None:
        assert app_uninitialized._tick_accumulator_ms == 0

    def test_pause_hint_shown_removed_in_iter2(
        self, app_uninitialized: App
    ) -> None:
        """G2-1 INV-8：_pause_hint_shown 字段在 iter-2 删除（PAUSED 是真实屏态）。"""
        assert not hasattr(app_uninitialized, "_pause_hint_shown")

    def test_storage_is_none_at_init(self, app_uninitialized: App) -> None:
        """G2-2：App.__init__ 默认 _storage = None（UT 不依赖磁盘）。"""
        assert app_uninitialized._storage is None

    def test_clock_is_none_until_init(self, app_uninitialized: App) -> None:
        assert app_uninitialized.clock is None

    def test_init_does_not_call_pygame_init(
        self, app_uninitialized: App, fake_pygame
    ) -> None:
        """构造期零副作用：pygame.init 不被调。"""
        fake_pygame.init.assert_not_called()
        fake_pygame.display.set_mode.assert_not_called()

    def test_init_with_custom_config(self) -> None:
        """自定义 AppConfig 可传入。"""
        cfg = AppConfig(fps_cap=30)
        a = App(cfg)
        assert a.config.fps_cap == 30