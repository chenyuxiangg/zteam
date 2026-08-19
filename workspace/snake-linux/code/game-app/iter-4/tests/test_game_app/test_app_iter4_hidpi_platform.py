"""G4-2 HiDPI 降级 + 平台检查 UT（UT HIDPI-1~4 + PLAT-1~3）。

不变量（INV-17/18/19）：
- HiDPI 失败 → 降级到非 HiDPI 模式 + stderr warning + _hidpi_degraded=True
- 降级也失败 → GraphicsUnavailableError → 退出码 2
- 平台版本检查：macOS <12 / Windows <10 → PlatformUnsupportedWarning（不退出）
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestHiDpiFallback:
    """HIDPI-1/2/3/4：HiDPI 降级包装。"""

    def test_hidpi_first_try_succeeds_no_fallback(
        self, monkeypatch, fake_pygame, fake_storage
    ) -> None:
        """HIDPI-1a：第一次 init 成功 → 不降级（_hidpi_degraded=False）。

        MDE §5.3 修订后：降级标志由 _create_renderer_with_hidpi_fallback
        二元组直接返回，不再读写 Renderer 实例属性——mock 无需 spec=[] 规避
        marker 陷阱（保留 spec=[] 亦无害）。
        """
        from game_app import App
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
        fake_renderer = MagicMock(spec=[])  # 无属性 → getattr 走 default
        fake_renderer.init = MagicMock()
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer)

        a = App()
        a._init_pygame()
        assert a._hidpi_degraded is False

    def test_hidpi_first_try_fails_fallback_to_non_hidpi(
        self, monkeypatch, fake_pygame, fake_storage
    ) -> None:
        """HIDPI-1：enable_high_dpi=True init 失败 → 降级到 enable_high_dpi=False init 成功。"""
        from game_app import App, AppConfigV3
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        fake_renderer = MagicMock(spec=[])  # spec=[]：仅避免 MagicMock 自动属性（marker 已移除）

        # 记录 init 调用次数
        init_call_count = [0]

        def init_with_failure_first():
            init_call_count[0] += 1
            if init_call_count[0] == 1:
                raise fake_pygame.error("SCALED unsupported")
            return None

        fake_renderer.init = MagicMock(side_effect=init_with_failure_first)

        # 记录 Renderer 构造调用
        captured_kwargs = []

        def capture_renderer(size, **kw):
            captured_kwargs.append(kw.copy())
            return fake_renderer

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)

        a = App(AppConfigV3(enable_high_dpi=True))
        a._init_pygame()
        # 第一次构造 enable_high_dpi=True → 失败
        # 第二次构造 enable_high_dpi=False → 成功
        assert len(captured_kwargs) == 2
        assert captured_kwargs[0].get("enable_high_dpi") is True
        assert captured_kwargs[1].get("enable_high_dpi") is False
        # 降级标志
        assert a._hidpi_degraded is True

    def test_hidpi_both_fail_raise_graphics_unavailable(
        self, monkeypatch, fake_pygame, fake_storage
    ) -> None:
        """HIDPI-2：HiDPI + 非 HiDPI 都失败 → GraphicsUnavailableError。"""
        from game_app import App, AppConfigV3
        from game_app.errors import GraphicsUnavailableError
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        fake_renderer = MagicMock()
        fake_renderer.init = MagicMock(side_effect=fake_pygame.error("display set_mode fail"))

        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer)

        a = App(AppConfigV3(enable_high_dpi=True))
        with pytest.raises(GraphicsUnavailableError) as exc_info:
            a._init_pygame()
        assert "图形环境初始化失败" in str(exc_info.value)

    def test_hidpi_warning_emitted_on_fallback(
        self, monkeypatch, fake_pygame, fake_storage, capsys
    ) -> None:
        """HIDPI-3：HiDPI 降级触发 stderr HighDPIWarning（INV-18）。"""
        from game_app import App, AppConfigV3
        from game_app.errors import HighDPIWarning
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        fake_renderer = MagicMock()
        call_count = [0]

        def init_with_failure():
            call_count[0] += 1
            if call_count[0] == 1:
                raise fake_pygame.error("SCALED unsupported")
            return None

        fake_renderer.init = MagicMock(side_effect=init_with_failure)
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer)

        a = App(AppConfigV3(enable_high_dpi=True))
        with pytest.warns(HighDPIWarning):
            a._init_pygame()

    def test_hidpi_degraded_flag_initialized_false(self, app_uninitialized) -> None:
        """HIDPI-4a：初始 _hidpi_degraded == False。"""
        assert app_uninitialized._hidpi_degraded is False


class TestPlatformCheck:
    """PLAT-1/2/3：平台版本检查（非致命，stderr warning 但继续运行）。"""

    def test_macos_old_version_warning(self, monkeypatch) -> None:
        """PLAT-1：macOS <12 → PlatformUnsupportedWarning。"""
        from game_app.errors import PlatformUnsupportedWarning
        from game_app import app as app_mod
        import platform as platform_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Darwin")
        monkeypatch.setattr(platform_mod, "mac_ver", lambda: ("11.5.2", ("", "", ""), ""))

        with pytest.warns(PlatformUnsupportedWarning):
            app_mod._check_platform_version()

    def test_windows_old_version_warning(self, monkeypatch) -> None:
        """PLAT-2：Windows <10 → PlatformUnavailableWarning。

        检视 F-3 修订：platform.win32_ver() 返回 (version, csd, ptype)——
        版本号在 [0] 位，[1] 是 csd（Service Pack 描述）。mock 必须按真实
        API 结构 (\"8.1\", \"\", \"\", \"\") 放置版本号，否则绿测掩盖缺陷。
        """
        from game_app.errors import PlatformUnsupportedWarning
        from game_app import app as app_mod
        import platform as platform_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Windows")
        monkeypatch.setattr(platform_mod, "win32_ver", lambda: ("8.1", "", "", ""))
        monkeypatch.setattr(platform_mod, "release", lambda: "8.1")

        with pytest.warns(PlatformUnsupportedWarning):
            app_mod._check_platform_version()

    def test_windows_version_from_release_fallback(self, monkeypatch) -> None:
        """F-3 补充：win32_ver()[0] 为空串 → 兜底取 release() 触发警告。

        覆盖 _check_platform_version Windows 分支的 release() 兜底路径
        （202 行）：win32_ver() 返回空版本号时（部分 Windows 精简版），
        int('') 会抛 ValueError——必须走 release() 兜底而非静默吞掉。
        """
        from game_app.errors import PlatformUnsupportedWarning
        from game_app import app as app_mod
        import platform as platform_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Windows")
        monkeypatch.setattr(platform_mod, "win32_ver", lambda: ("", "", "", ""))
        monkeypatch.setattr(platform_mod, "release", lambda: "8.1")

        with pytest.warns(PlatformUnsupportedWarning):
            app_mod._check_platform_version()

    def test_macos_unparseable_version_no_crash(self, monkeypatch) -> None:
        """F-3 补充：mac_ver 版本号不可解析（如 \"unknown\"）→ 不崩溃不警告。

        覆盖 macOS 分支 except (ValueError, IndexError, AttributeError) 兜底
        （193-194 行）：版本字符串非数字时静默跳过，不抛异常。
        """
        from game_app import app as app_mod
        from game_app.errors import PlatformUnsupportedWarning
        import platform as platform_mod
        import warnings as warnings_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Darwin")
        monkeypatch.setattr(platform_mod, "mac_ver", lambda: ("unknown", ("", "", ""), ""))

        with warnings_mod.catch_warnings(record=True) as wlist:
            warnings_mod.simplefilter("always")
            app_mod._check_platform_version()
        plat_warnings = [w for w in wlist if issubclass(w.category, PlatformUnsupportedWarning)]
        assert len(plat_warnings) == 0

    def test_linux_no_warning(self, monkeypatch) -> None:
        """PLAT-3a：Linux 平台不触发警告。"""
        from game_app import app as app_mod
        import platform as platform_mod
        import warnings as warnings_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Linux")

        with warnings_mod.catch_warnings(record=True) as wlist:
            warnings_mod.simplefilter("always")
            app_mod._check_platform_version()
        # 不应有 PlatformUnsupportedWarning
        from game_app.errors import PlatformUnsupportedWarning
        plat_warnings = [w for w in wlist if issubclass(w.category, PlatformUnsupportedWarning)]
        assert len(plat_warnings) == 0

    def test_macos_new_version_no_warning(self, monkeypatch) -> None:
        """PLAT-3b：macOS 12+ 不触发警告。"""
        from game_app import app as app_mod
        from game_app.errors import PlatformUnsupportedWarning
        import platform as platform_mod
        import warnings as warnings_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Darwin")
        monkeypatch.setattr(platform_mod, "mac_ver", lambda: ("13.0.0", ("", "", ""), ""))

        with warnings_mod.catch_warnings(record=True) as wlist:
            warnings_mod.simplefilter("always")
            app_mod._check_platform_version()
        plat_warnings = [w for w in wlist if issubclass(w.category, PlatformUnsupportedWarning)]
        assert len(plat_warnings) == 0

    def test_windows_new_version_no_warning(self, monkeypatch) -> None:
        """PLAT-3c：Windows 10+ 不触发警告（版本号在 [0] 位）。"""
        from game_app import app as app_mod
        from game_app.errors import PlatformUnsupportedWarning
        import platform as platform_mod
        import warnings as warnings_mod

        monkeypatch.setattr(platform_mod, "system", lambda: "Windows")
        monkeypatch.setattr(platform_mod, "win32_ver", lambda: ("10.0", "", "", ""))
        monkeypatch.setattr(platform_mod, "release", lambda: "10")

        with warnings_mod.catch_warnings(record=True) as wlist:
            warnings_mod.simplefilter("always")
            app_mod._check_platform_version()
        plat_warnings = [w for w in wlist if issubclass(w.category, PlatformUnsupportedWarning)]
        assert len(plat_warnings) == 0


class TestHiDpiFallbackPackage:
    """HIDPI 私有函数 _create_renderer_with_hidpi_fallback 单元测试。"""

    def test_function_exists_and_callable(self) -> None:
        from game_app import app as app_mod
        assert hasattr(app_mod, "_create_renderer_with_hidpi_fallback")
        assert callable(app_mod._create_renderer_with_hidpi_fallback)

    def test_returns_renderer_when_first_try_succeeds(self, monkeypatch, fake_pygame) -> None:
        """第一次 init 成功 → 返 (renderer, False)（不降级）。"""
        from game_app import app as app_mod

        fake_renderer = MagicMock(spec=[])  # spec=[] 避免 MagicMock 自动属性
        fake_renderer.init = MagicMock()

        # monkeypatch Renderer → 直接返 fake_renderer，绕开 _validate_skin
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer)

        result, degraded = app_mod._create_renderer_with_hidpi_fallback(
            (640, 480), skin=MagicMock(spec=[]), enable_high_dpi=True
        )
        assert result is fake_renderer
        assert degraded is False
        # init 应被调 1 次
        assert fake_renderer.init.call_count == 1

    def test_returns_renderer_after_fallback(self, monkeypatch, fake_pygame) -> None:
        """第一次失败 → 第二次（降级）成功 → 返 (renderer, True)。"""
        from game_app import app as app_mod
        from game_app.errors import HighDPIWarning

        fake_renderer = MagicMock(spec=[])
        call_count = [0]

        def init_with_failure():
            call_count[0] += 1
            if call_count[0] == 1:
                raise fake_pygame.error("SCALED unsupported")
            return None

        fake_renderer.init = MagicMock(side_effect=init_with_failure)

        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer)

        with pytest.warns(HighDPIWarning):
            result, degraded = app_mod._create_renderer_with_hidpi_fallback(
                (640, 480), skin=MagicMock(spec=[]), enable_high_dpi=True
            )
        assert result is fake_renderer
        assert degraded is True
        assert call_count[0] == 2