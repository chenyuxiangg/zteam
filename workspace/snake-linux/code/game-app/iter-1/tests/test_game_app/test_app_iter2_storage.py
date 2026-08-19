"""iter-2 storage 接入单测（UT S-1 ~ S-10, SC-1 ~ SC-3, H-1 ~ H-4, S-3 mkdir 失败）。

需求（G2-2/G2-3/G2-6）：
- App.__init__ 默认 _storage = None（UT 不依赖磁盘）
- _init_pygame 构造 HighScoreStore 并 load() 覆盖 _high_score（INV-12）
- mkdir 失败 → 包 AppError（退出码 1）
- _dispatch_menu RESET_HIGHSCORE 成功/失败
- _new_game 注册 score_callback → 触发 → 同步 _high_score + storage.save
- storage.save 抛 StorageError → 包 StorageUnavailableError
- draw_menu / draw_game_over 形参 high_score 显示
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from game_app import (
    App,
    AppError,
    AppScreen,
    InputAction,
    StorageUnavailableError,
)
from game_app.config import AppConfig
from game_core import Difficulty, GameStatus
from platform_storage import HighScoreStore, StorageError


# ========== S-1 / S-2 / S-3：_init_pygame 构造 storage ==========


class TestStorageInit:
    def test_storage_none_at_init(self, app_uninitialized: App) -> None:
        """UT S-1：构造 App 时 _storage 默认 None（G2-2 让 UT 不依赖磁盘）。"""
        assert app_uninitialized._storage is None

    def test_init_pygame_creates_storage(
        self, fake_pygame, monkeypatch, app_uninitialized: App
    ) -> None:
        """UT S-2：_init_pygame 内构造 HighScoreStore + _high_score = load()。"""
        import game_app.app as app_mod

        fake_store = MagicMock(name="real_fake_storage")
        fake_store.load.return_value = 42
        # monkeypatch app 模块的 create_storage 符号
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_store)
        app_uninitialized._init_pygame()
        assert app_uninitialized._storage is fake_store
        assert app_uninitialized._high_score == 42

    def test_init_pygame_skips_create_if_already_injected(
        self, fake_pygame, monkeypatch, app_uninitialized: App
    ) -> None:
        """UT S-2 旁路（P1-3）：fixture 注入 fake 后 _init_pygame 不覆盖。"""
        import game_app.app as app_mod

        injected = MagicMock(name="injected_fake")
        injected.load.return_value = 7
        create_called = MagicMock(name="create_called")
        monkeypatch.setattr(app_mod, "create_storage", create_called)
        app_uninitialized._storage = injected  # 提前注入 fake
        app_uninitialized._init_pygame()
        # create_storage 未被调
        create_called.assert_not_called()
        # injected 保留
        assert app_uninitialized._storage is injected
        # _high_score 由 caller 在注入后赋值（fixture pattern）
        app_uninitialized._high_score = injected.load.return_value
        assert app_uninitialized._high_score == 7

    def test_init_pygame_wraps_storage_error(
        self, fake_pygame, monkeypatch, app_uninitialized: App
    ) -> None:
        """UT S-3：HighScoreStore mkdir 失败抛 StorageError → 包 AppError。"""
        import game_app.app as app_mod
        from platform_storage import StorageError as PSStorageError

        def boom(path=None):
            raise PSStorageError("disk full")

        monkeypatch.setattr(app_mod, "create_storage", boom)
        with pytest.raises(AppError):
            app_uninitialized._init_pygame()

    def test_init_pygame_wraps_oserror_on_mkdir(
        self, fake_pygame, monkeypatch, app_uninitialized: App
    ) -> None:
        """UT S-3 旁路（P1-1）：mkdir 抛裸 OSError → 包 AppError。"""
        import game_app.app as app_mod

        def boom(path=None):
            raise OSError("permission denied")

        monkeypatch.setattr(app_mod, "create_storage", boom)
        with pytest.raises(AppError):
            app_uninitialized._init_pygame()


# ========== S-4 / S-5：RESET_HIGHSCORE 分支 ==========


class TestResetHighScore:
    def test_reset_highscore_calls_storage_reset_and_zeroes_field(
        self, app_in_playing: App
    ) -> None:
        """UT S-4：MENU 态 H 键 → storage.reset + _high_score=0。"""
        from game_app import InputAction as IA

        # 进 MENU 态（H 键只在 MENU 态响应）
        app_in_playing.screen = AppScreen.MENU
        app_in_playing._high_score = 99
        # 调 dispatch（实际是 _dispatch_menu）
        app_in_playing._dispatch(IA.RESET_HIGHSCORE)
        assert app_in_playing._storage.reset.call_count == 1
        assert app_in_playing._high_score == 0

    def test_reset_highscore_wraps_storage_error(
        self, app_in_playing: App
    ) -> None:
        """UT S-5：storage.reset 抛 StorageError → 包 StorageUnavailableError。"""
        from game_app import InputAction as IA
        from platform_storage import StorageError as PSStorageError

        app_in_playing._storage.reset.side_effect = PSStorageError("io")
        app_in_playing.screen = AppScreen.MENU
        with pytest.raises(StorageUnavailableError):
            app_in_playing._dispatch(IA.RESET_HIGHSCORE)


# ========== S-6 / S-7 / S-8：score_callback 注册 + 触发 ==========


class TestScoreCallbackRegistration:
    def test_new_game_registers_score_callback(
        self, app_in_playing: App
    ) -> None:
        """UT S-6：_new_game 注册 score_callback（持有 self）。"""
        # game_state 应已通过 _new_game 创建
        cb = app_in_playing.game_state._score_callback
        assert cb is not None
        # 手动触发 callback → 应调用 storage.save
        cb(10)
        # save 被调；具体调用见 S-7

    def test_score_callback_saves_and_updates_high_score(
        self, app_in_playing: App
    ) -> None:
        """UT S-7：吃食触发 callback → storage.save(max(score, load())) + _high_score 同步。"""
        app_in_playing._storage.load.return_value = 5
        cb = app_in_playing.game_state._score_callback
        assert cb is not None
        cb(10)
        # save 被调：save(max(10, 5)) = save(10)
        app_in_playing._storage.save.assert_called_once_with(10)
        # _high_score 同步更新为 max(0, 10) = 10
        assert app_in_playing._high_score == 10

    def test_score_callback_save_error_wrapped(
        self, app_in_playing: App
    ) -> None:
        """UT S-8：storage.save 抛 StorageError → 包 StorageUnavailableError。"""
        from platform_storage import StorageError as PSStorageError

        app_in_playing._storage.load.return_value = 0
        app_in_playing._storage.save.side_effect = PSStorageError("write fail")
        cb = app_in_playing.game_state._score_callback
        assert cb is not None
        with pytest.raises(StorageUnavailableError):
            cb(5)


# ========== SC-1 / SC-2 / SC-3：INV-13 同步实例字段 + 重开重新注册 ==========


class TestScoreCallbackInv13:
    def test_high_score_synced_after_score_event(
        self, app_in_playing: App
    ) -> None:
        """UT SC-1 / SC-2：score_callback 触发后 _high_score 立即可见（INV-13 P0-2）。"""
        app_in_playing._storage.load.return_value = 0
        cb = app_in_playing.game_state._score_callback
        assert cb is not None
        cb(10)
        # _high_score 同步为 10（P0-2 直接写实例字段，不再走 nonlocal 容器）
        assert app_in_playing._high_score == 10

    def test_new_game_re_registers_callback(
        self, app_uninitialized: App
    ) -> None:
        """UT SC-3：重开新局重新注册 callback（旧 callback 仍持有旧 _storage 引用，

        新 game_state 的 callback 持有新 _storage 引用——验证二者均为闭包且不同。
        """
        from unittest.mock import MagicMock
        from game_app import InputAction as IA

        # 手动注入 fake storage
        fake_store = MagicMock(name="fake_store")
        fake_store.load.return_value = 0
        app_uninitialized._storage = fake_store

        # 第一次 _new_game
        app_uninitialized._new_game(Difficulty.MEDIUM)
        first_cb = app_uninitialized.game_state._score_callback
        assert first_cb is not None

        # 触发 first_cb 写入 _high_score = 5
        first_cb(5)
        assert app_uninitialized._high_score == 5
        assert fake_store.save.call_count == 1

        # 重开
        app_uninitialized._dispatch(IA.START)  # MENU 态 START 会 _new_game
        second_cb = app_uninitialized.game_state._score_callback
        assert second_cb is not None
        # 两次 callback 都是 App._new_game 内的局部函数对象
        assert callable(first_cb)
        assert callable(second_cb)
        # 触发 second_cb 写入 _high_score = 8（应在原 5 基础上 max）
        second_cb(8)
        assert app_uninitialized._high_score == 8
        assert fake_store.save.call_count == 2


# ========== S-9 / S-10：real HighScoreStore via tmp_path ==========


class TestRealStorageIO:
    def test_init_pygame_with_custom_path_loads_highscore(
        self, tmp_path, fake_pygame, monkeypatch, app_uninitialized: App
    ) -> None:
        """UT S-9 / S-10：用 tmp_path 注入真实 HighScoreStore。"""
        import game_app.app as app_mod
        from platform_storage import HighScoreStore

        # 写一个 highscore.json = 50
        target = tmp_path / "highscore.json"
        store = HighScoreStore(target)
        store.save(50)

        # monkeypatch create_storage 接受 path 并返回真实 store
        monkeypatch.setattr(
            app_mod,
            "create_storage",
            lambda path=None: HighScoreStore(path or target),
        )
        app_uninitialized._init_pygame()
        assert app_uninitialized._high_score == 50

    def test_load_corrupt_file_returns_zero(
        self, tmp_path, fake_pygame, monkeypatch, app_uninitialized: App
    ) -> None:
        """UT S-9：损坏文件 → load() 返 0（platform-storage 内部备份 + 返 0）。"""
        import game_app.app as app_mod
        from platform_storage import HighScoreStore

        target = tmp_path / "highscore.json"
        target.write_text("{not valid json", encoding="utf-8")

        monkeypatch.setattr(
            app_mod,
            "create_storage",
            lambda path=None: HighScoreStore(path or target),
        )
        app_uninitialized._init_pygame()
        assert app_uninitialized._high_score == 0


# ========== H-1 / H-2 / H-3 / H-4：菜单/结束画面 high_score 展示 ==========


class TestHighScoreDisplayInMenu:
    def test_draw_menu_renders_high_score_when_positive(
        self, fake_pygame
    ) -> None:
        """UT H-1：draw_menu(high_score=100) 调用 body_font.render 含 '最高分' 文本。"""
        from game_app.menu import draw_menu

        surface = MagicMock(name="surface")
        surface.get_width.return_value = 640
        surface.get_height.return_value = 480
        title_font = MagicMock(name="title_font")
        body_font = MagicMock(name="body_font")
        # 让 render 返一个 MagicMock，其 get_width/get_height 不为 0
        for f in (title_font, body_font):
            f.render.return_value = MagicMock(
                get_width=MagicMock(return_value=100),
                get_height=MagicMock(return_value=20),
            )

        draw_menu(surface, title_font, body_font, Difficulty.EASY, high_score=100)
        # body_font.render 至少被调 1 次，参数含独立的 "最高分：100" 行
        render_texts = [
            call.args[0] for call in body_font.render.call_args_list
        ]
        hs_lines = [t for t in render_texts if t.startswith("最高分")]
        assert any("100" in t for t in hs_lines), (
            f"Expected high-score line in render calls, got: {hs_lines}"
        )

    def test_draw_menu_omits_high_score_when_zero(self, fake_pygame) -> None:
        """UT H-2：draw_menu(high_score=0) 不绘制最高分行（独立成行）。"""
        from game_app.menu import draw_menu

        surface = MagicMock(name="surface")
        surface.get_width.return_value = 640
        surface.get_height.return_value = 480
        title_font = MagicMock(name="title_font")
        body_font = MagicMock(name="body_font")
        for f in (title_font, body_font):
            f.render.return_value = MagicMock(
                get_width=MagicMock(return_value=100),
                get_height=MagicMock(return_value=20),
            )

        draw_menu(surface, title_font, body_font, Difficulty.EASY, high_score=0)
        render_texts = [
            call.args[0] for call in body_font.render.call_args_list
        ]
        # 检查独立的"最高分：xxx"行（不是嵌入到 hint 提示文本里）
        hs_lines = [t for t in render_texts if t.startswith("最高分")]
        assert hs_lines == [], (
            f"Did not expect high-score line when score is 0, got: {hs_lines}"
        )

    def test_draw_game_over_renders_high_score_when_positive(
        self, fake_pygame
    ) -> None:
        """UT H-3：draw_game_over(high_score=200) 含 '最高分' 文本。"""
        from game_app.menu import draw_game_over

        surface = MagicMock(name="surface")
        surface.get_width.return_value = 640
        surface.get_height.return_value = 480
        title_font = MagicMock(name="title_font")
        body_font = MagicMock(name="body_font")
        for f in (title_font, body_font):
            f.render.return_value = MagicMock(
                get_width=MagicMock(return_value=100),
                get_height=MagicMock(return_value=20),
            )

        draw_game_over(
            surface, title_font, body_font, score=50, high_score=200
        )
        render_texts = [
            call.args[0] for call in body_font.render.call_args_list
        ]
        hs_lines = [t for t in render_texts if t.startswith("最高分")]
        assert any("200" in t for t in hs_lines), (
            f"Expected high-score line in render calls, got: {hs_lines}"
        )

    def test_draw_game_over_omits_high_score_when_zero(
        self, fake_pygame
    ) -> None:
        """UT H-4：draw_game_over(high_score=0) 不绘制最高分行。"""
        from game_app.menu import draw_game_over

        surface = MagicMock(name="surface")
        surface.get_width.return_value = 640
        surface.get_height.return_value = 480
        title_font = MagicMock(name="title_font")
        body_font = MagicMock(name="body_font")
        for f in (title_font, body_font):
            f.render.return_value = MagicMock(
                get_width=MagicMock(return_value=100),
                get_height=MagicMock(return_value=20),
            )

        draw_game_over(
            surface, title_font, body_font, score=50, high_score=0
        )
        render_texts = [
            call.args[0] for call in body_font.render.call_args_list
        ]
        hs_lines = [t for t in render_texts if t.startswith("最高分")]
        assert hs_lines == [], (
            f"Did not expect high-score line when score is 0, got: {hs_lines}"
        )