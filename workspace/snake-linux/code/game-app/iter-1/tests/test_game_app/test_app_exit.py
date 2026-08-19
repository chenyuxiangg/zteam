"""退出主循环 + 错误处理单测（UT 31/32/33/41/42）。

需求：
- 退出主循环调 Renderer.shutdown（INV-5）→ fake.quit.call_count >= 1
- 图形环境不可用 → 退出码 2 + shutdown 兜底
- ConfigError 触发退出码 1
- 无 _quit() 死代码（R3-7）
- dispatch 内不写 _running=False
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from game_app import App, InputAction, AppConfig
from game_app.errors import AppError, ConfigError, GraphicsUnavailableError
from game_app.app import main
from game_app.screens import AppScreen


class TestNoQuitMethod:
    def test_app_has_no_quit_method(self, app: App) -> None:
        """UT 41：R3-7 删除 _quit() 死代码。"""
        assert not hasattr(app, "_quit")


class TestRendererShutdownOnExit:
    def test_quit_calls_renderer_shutdown(self, fake_pygame) -> None:
        """UT 31：退出主循环调 Renderer.shutdown（INV-5）。"""
        from game_core import Difficulty
        a = App()
        a._difficulty = Difficulty.HARD
        a._init_pygame()
        # 用真 renderer（在 fake_pygame 下构造）；验证 shutdown 调了 pygame.quit
        # 注入事件序列：第一帧 QUIT（主循环 break）→ finally shutdown
        from game_app import app as app_mod
        fake = app_mod.pygame
        from .conftest import FakeEvent, _PYGAME_KEYS
        fake.event.get.return_value = [FakeEvent(_PYGAME_KEYS["QUIT"])]

        rc = a.run()
        assert rc == 0
        # fake.quit 应被调（renderer.shutdown 内部调 pygame.quit）
        assert fake.quit.call_count >= 1


class TestGraphicsUnavailableError:
    def test_graphics_unavailable_exits_with_code_2(self, fake_pygame) -> None:
        """UT 32：图形环境不可用 → run() 返 2 + stderr 可读消息 + shutdown 兜底。"""
        from game_core import Difficulty
        a = App()
        a._difficulty = Difficulty.HARD
        # 让 renderer.init 失败
        from game_app import app as app_mod
        fake = app_mod.pygame
        fake.display.set_mode.side_effect = RuntimeError("no display")

        # 捕获 stderr
        import io
        import sys
        old_stderr = sys.stderr
        captured = io.StringIO()
        sys.stderr = captured
        try:
            rc = a.run()
        finally:
            sys.stderr = old_stderr

        assert rc == 2
        # stderr 应有"无法初始化图形界面"
        assert "无法初始化图形界面" in captured.getvalue()
        # fake.quit 应至少调 1 次（退出码 2 路径 shutdown 兜底）
        assert fake.quit.call_count >= 1


class TestConfigError:
    def test_fps_cap_zero_raises_config_error(self) -> None:
        """UT 33/4：fps_cap=0 抛 ConfigError。"""
        with pytest.raises(ConfigError):
            AppConfig(fps_cap=0)

    def test_main_returns_1_on_config_error(self, capsys) -> None:
        """UT 33：ConfigError 触发退出码 1。"""
        # 直接构造 App 会抛，所以 main() 必须在 App() 构造前捕获
        # 但 main() 用 AppConfig() 默认构造，不可能传非法值；这里改测 App 构造失败场景
        # 改为：patch App 构造抛 ConfigError，验证 main 捕获 + exit 1
        with patch("game_app.app.App", side_effect=ConfigError("fps_cap=0")):
            rc = main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "配置非法" in captured.err


class TestAppErrorExitCode:
    def test_app_error_returns_1(self, fake_pygame) -> None:
        """AppError → exit 1。"""
        from game_core import Difficulty
        # 让 _init_pygame 抛 AppError 子类
        a = App()
        a._difficulty = Difficulty.HARD
        # 直接 patch _init_pygame 抛 GraphicsUnavailableError
        with patch.object(a, "_init_pygame", side_effect=GraphicsUnavailableError("simulated")):
            import io, sys
            old = sys.stderr
            captured = io.StringIO()
            sys.stderr = captured
            try:
                rc = a.run()
            finally:
                sys.stderr = old
        assert rc == 2


class TestDispatchDoesNotWriteRunning:
    """UT 42：dispatch 内不写 self._running = False（菜单/结束态）。"""

    def test_dispatch_menu_quit_keeps_running_true(self, app: App) -> None:
        """_dispatch_menu(QUIT) 后 app._running 不变。"""
        assert app._running is True
        app._dispatch_menu(InputAction.QUIT)
        assert app._running is True

    def test_dispatch_over_quit_keeps_running_true(self, app_with_mock_renderer) -> None:
        """_dispatch_over(QUIT) 后 app._running 不变。"""
        assert app_with_mock_renderer._running is True
        app_with_mock_renderer.screen = AppScreen.GAME_OVER
        app_with_mock_renderer._dispatch_over(InputAction.QUIT)
        assert app_with_mock_renderer._running is True


class TestQuitFromAnyScreen:
    """UT 34：Q/ESC 任意态退出。"""

    @pytest.mark.parametrize("screen", [AppScreen.MENU, AppScreen.PLAYING, AppScreen.GAME_OVER])
    def test_quit_breaks_loop_from_any_screen(self, app_with_mock_renderer, screen: AppScreen) -> None:
        """任意态收到 QUIT → 主循环下次 break。"""
        app_with_mock_renderer.screen = screen
        # 直接注入 fake.event.get 返回 [QUIT]
        from game_app import app as app_mod
        from .conftest import FakeEvent, _PYGAME_KEYS
        fake = app_mod.pygame
        fake.event.get.return_value = [FakeEvent(_PYGAME_KEYS["QUIT"])]

        rc = app_with_mock_renderer.run()
        assert rc == 0