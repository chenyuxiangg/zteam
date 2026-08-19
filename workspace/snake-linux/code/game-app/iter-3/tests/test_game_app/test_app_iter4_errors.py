"""G4-2 错误类型 + 退出码映射 UT（UT ERR-1~5）。

迭代 4 增量（G4-2）：
- GraphicsUnavailableError.suggestion 字段 + 退出码 2 路径写入 stderr
- StorageUnavailableError.suggestion 字段 + 退出码 3 路径写入 stderr
- error_to_exit_code() 函数：精确类型 > 基类 > 默认 1
- INV-17：GraphicsUnavailableError → 2；StorageUnavailableError → 3

不变量：
- ConfigError → 1（沿用）
- AppError 默认 → 1（基类兜底）
"""
from __future__ import annotations

import io
import sys

import pytest


class TestSuggestionFields:
    """ERR-2/ERR-4：suggestion 字段可读 + 默认值。"""

    def test_graphics_unavailable_error_default_suggestion_empty(self) -> None:
        from game_app.errors import GraphicsUnavailableError
        e = GraphicsUnavailableError("msg")
        assert e.suggestion == ""

    def test_graphics_unavailable_error_custom_suggestion(self) -> None:
        from game_app.errors import GraphicsUnavailableError
        e = GraphicsUnavailableError("SDL2 缺失", suggestion="请安装 libsdl2-dev")
        assert e.suggestion == "请安装 libsdl2-dev"
        assert "SDL2 缺失" in str(e)

    def test_storage_unavailable_error_default_suggestion_empty(self) -> None:
        from game_app.errors import StorageUnavailableError
        e = StorageUnavailableError("disk full")
        assert e.suggestion == ""

    def test_storage_unavailable_error_custom_suggestion(self) -> None:
        from game_app.errors import StorageUnavailableError
        e = StorageUnavailableError("不可写", suggestion="检查 ~/.local/share 权限")
        assert e.suggestion == "检查 ~/.local/share 权限"

    def test_storage_unavailable_error_is_subclass_of_app_error(self) -> None:
        """iter-3 沿用：StorageUnavailableError 仍继承 AppError（退出码兼容基础）。"""
        from game_app.errors import AppError, StorageUnavailableError
        assert issubclass(StorageUnavailableError, AppError)

    def test_graphics_unavailable_error_is_subclass_of_app_error(self) -> None:
        from game_app.errors import AppError, GraphicsUnavailableError
        assert issubclass(GraphicsUnavailableError, AppError)


class TestErrorToExitCode:
    """ERR-5：错误 → 退出码映射（精确类型 > 基类 > 默认）。"""

    def test_config_error_to_1(self) -> None:
        from game_app.errors import ConfigError, error_to_exit_code
        assert error_to_exit_code(ConfigError("bad fps")) == 1

    def test_graphics_unavailable_to_2(self) -> None:
        """ERR-5a：GraphicsUnavailableError → 2（精确类型优先于 AppError 基类的 1）。"""
        from game_app.errors import GraphicsUnavailableError, error_to_exit_code
        assert error_to_exit_code(GraphicsUnavailableError("SDL 缺失")) == 2

    def test_storage_unavailable_to_3(self) -> None:
        """ERR-5b：StorageUnavailableError → 3（iter-4 新增退出码）。"""
        from game_app.errors import StorageUnavailableError, error_to_exit_code
        assert error_to_exit_code(StorageUnavailableError("不可写")) == 3

    def test_app_error_default_to_1(self) -> None:
        """基类 AppError（未映射子类）默认 1。"""
        from game_app.errors import AppError, error_to_exit_code
        assert error_to_exit_code(AppError("generic")) == 1

    def test_unknown_exception_to_1(self) -> None:
        """非 AppError 异常默认 1。"""
        from game_app.errors import error_to_exit_code
        assert error_to_exit_code(ValueError("xxx")) == 1

    def test_runtime_error_to_1(self) -> None:
        from game_app.errors import error_to_exit_code
        assert error_to_exit_code(RuntimeError("oops")) == 1


class TestWarningClasses:
    """G4-2 新增 3 类非致命警告类（HiDPI / CJK / PlatformUnsupported）。"""

    def test_high_dpi_warning_is_user_warning(self) -> None:
        from game_app.errors import HighDPIWarning
        import warnings as warnings_mod
        assert issubclass(HighDPIWarning, UserWarning)

    def test_cjk_font_fallback_warning_is_user_warning(self) -> None:
        from game_app.errors import CJKFontFallbackWarning
        assert issubclass(CJKFontFallbackWarning, UserWarning)

    def test_platform_unsupported_warning_is_user_warning(self) -> None:
        from game_app.errors import PlatformUnsupportedWarning
        assert issubclass(PlatformUnsupportedWarning, UserWarning)


class TestRunExitCodesViaRun:
    """ERR-1 / ERR-3：App.run() 在异常时的退出码。"""

    def test_run_returns_2_on_graphics_unavailable(
        self, fake_pygame, monkeypatch, fake_storage
    ) -> None:
        """ERR-1：_init_pygame 抛 GraphicsUnavailableError → run() 返 2。"""
        from game_app import App
        from game_app.errors import GraphicsUnavailableError
        from game_app import app as app_mod
        from game_app import storage as storage_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        def boom_init(*a, **kw):
            raise GraphicsUnavailableError("SDL2 missing", suggestion="请安装 libsdl2-dev")
        monkeypatch.setattr(app_mod.App, "_init_pygame", boom_init)

        a = App()
        rc = a.run()
        assert rc == 2

    def test_run_returns_3_on_storage_unavailable(
        self, fake_pygame, monkeypatch, fake_storage
    ) -> None:
        """ERR-3：_init_pygame 抛 StorageUnavailableError → run() 返 3（G4-2 新增退出码）。"""
        from game_app import App
        from game_app.errors import StorageUnavailableError
        from game_app import app as app_mod
        from game_app import storage as storage_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        def boom_init(*a, **kw):
            raise StorageUnavailableError("disk full", suggestion="清理磁盘空间")
        monkeypatch.setattr(app_mod.App, "_init_pygame", boom_init)

        a = App()
        rc = a.run()
        assert rc == 3

    def test_run_returns_1_on_config_error(
        self, fake_pygame, monkeypatch, fake_storage
    ) -> None:
        """ConfigError → 1（沿用）。"""
        from game_app import App
        from game_app.errors import ConfigError
        from game_app import app as app_mod
        from game_app import storage as storage_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        def boom_init(*a, **kw):
            raise ConfigError("fps_cap=0")
        monkeypatch.setattr(app_mod.App, "_init_pygame", boom_init)

        a = App()
        rc = a.run()
        assert rc == 1

    def test_run_stderr_graphics_suggestion(
        self, fake_pygame, monkeypatch, fake_storage, capsys
    ) -> None:
        """ERR-2：GraphicsUnavailableError.suggestion 写入 stderr。"""
        from game_app import App
        from game_app.errors import GraphicsUnavailableError
        from game_app import app as app_mod
        from game_app import storage as storage_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        def boom_init(*a, **kw):
            raise GraphicsUnavailableError("显示器不可用", suggestion="检查 SDL2 库")
        monkeypatch.setattr(app_mod.App, "_init_pygame", boom_init)

        a = App()
        a.run()
        captured = capsys.readouterr()
        assert "检查 SDL2 库" in captured.err

    def test_run_stderr_storage_suggestion(
        self, fake_pygame, monkeypatch, fake_storage, capsys
    ) -> None:
        """ERR-4：StorageUnavailableError.suggestion 写入 stderr。"""
        from game_app import App
        from game_app.errors import StorageUnavailableError
        from game_app import app as app_mod
        from game_app import storage as storage_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        def boom_init(*a, **kw):
            raise StorageUnavailableError("权限拒绝", suggestion="检查 ~/.local/share 目录权限")
        monkeypatch.setattr(app_mod.App, "_init_pygame", boom_init)

        a = App()
        a.run()
        captured = capsys.readouterr()
        assert "检查 ~/.local/share 目录权限" in captured.err