"""AppConfigV3 子类单测（UT V3-1~V3-7）。

需求：
- AppConfigV3 是 AppConfig 的子类，继承全部字段 + 新增 enable_high_dpi: bool = True
- 继承父类 __post_init__ 校验（fps_cap/窗口尺寸）
- isinstance 判定与 App.__init__ 集成（G3-4）

G3-4：NFR-04 高分屏清晰
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock
import pytest

from game_app.config import AppConfig, AppConfigV3
from game_app.errors import ConfigError


class TestAppConfigV3Defaults:
    """V3-1 / V3-7：默认值 + 字段继承。"""

    def test_default_construction_no_args(self) -> None:
        """V3-1：AppConfigV3() 默认构造 + enable_high_dpi=True。"""
        cfg = AppConfigV3()
        assert cfg.enable_high_dpi is True

    def test_default_construction_explicit_true(self) -> None:
        """V3-1：AppConfigV3(enable_high_dpi=True) 显式构造。"""
        cfg = AppConfigV3(enable_high_dpi=True)
        assert cfg.enable_high_dpi is True

    def test_inherits_parent_fields(self) -> None:
        """V3-7：AppConfigV3 继承 AppConfig 全部字段。"""
        cfg = AppConfigV3()
        assert cfg.window_w == AppConfig().window_w == 640
        assert cfg.window_h == AppConfig().window_h == 480
        assert cfg.fps_cap == AppConfig().fps_cap == 60
        assert cfg.min_window_w == AppConfig().min_window_w == 512
        assert cfg.min_window_h == AppConfig().min_window_h == 472

    def test_isinstance_subclass_of_app_config(self) -> None:
        """AppConfigV3 是 AppConfig 子类（isinstance 判定为 True）。"""
        cfg = AppConfigV3()
        assert isinstance(cfg, AppConfig)

    def test_app_config_is_not_v3(self) -> None:
        """AppConfig 实例**不是** AppConfigV3 实例（isinstance 判定为 False）。"""
        cfg = AppConfig()
        assert not isinstance(cfg, AppConfigV3)

    def test_frozen(self) -> None:
        """frozen dataclass：构造后字段不可写。"""
        cfg = AppConfigV3()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.enable_high_dpi = False  # type: ignore[misc]


class TestAppConfigV3EnableHighDpi:
    """V3-2：enable_high_dpi 可设。"""

    def test_disable_high_dpi(self) -> None:
        """V3-2：enable_high_dpi=False 合法构造。"""
        cfg = AppConfigV3(enable_high_dpi=False)
        assert cfg.enable_high_dpi is False

    def test_enable_high_dpi_with_custom_fields(self) -> None:
        """enable_high_dpi + 自定义父类字段。"""
        cfg = AppConfigV3(window_w=800, window_h=600, fps_cap=30, enable_high_dpi=False)
        assert cfg.window_w == 800
        assert cfg.enable_high_dpi is False


class TestAppConfigV3Validation:
    """V3-3：继承父类 __post_init__ 校验。"""

    @pytest.mark.parametrize("bad_fps", [0, -1, -100])
    def test_invalid_fps_cap_raises_config_error(self, bad_fps: int) -> None:
        """V3-3：AppConfigV3(fps_cap=0) 继承父类校验抛 ConfigError。"""
        with pytest.raises(ConfigError):
            AppConfigV3(fps_cap=bad_fps)

    def test_window_w_below_min_raises(self) -> None:
        with pytest.raises(ConfigError):
            AppConfigV3(window_w=400)

    def test_window_h_below_min_raises(self) -> None:
        with pytest.raises(ConfigError):
            AppConfigV3(window_h=300)


class TestAppConfigV3WithApp:
    """V3-4~V3-6：App.__init__ 集成 + isinstance 判定 + 传给 Renderer。"""

    def test_app_with_app_config_v3_passes_enable_high_dpi_true(
        self, fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch
    ) -> None:
        """V3-4：App(AppConfigV3(enable_high_dpi=True))._init_pygame() 调 Renderer(enable_high_dpi=True)。

        通过 monkeypatch Renderer 桩记录构造调用，断言 kwargs。
        """
        from game_app import App, AppConfigV3
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        captured_calls = []

        def capture_renderer(size, **kwargs):
            captured_calls.append({"size": size, "kwargs": kwargs})
            return fake_renderer_iter3

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfigV3(enable_high_dpi=True))
        a._init_pygame()
        # 断言 Renderer 构造时 enable_high_dpi=True 传入
        assert len(captured_calls) == 1
        assert captured_calls[0]["kwargs"].get("enable_high_dpi") is True

    def test_app_with_app_config_v3_passes_enable_high_dpi_false(
        self, fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch
    ) -> None:
        """V3-6：App(AppConfigV3(enable_high_dpi=False))._init_pygame() 调 Renderer(enable_high_dpi=False)。"""
        from game_app import App, AppConfigV3
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        captured_calls = []

        def capture_renderer(size, **kwargs):
            captured_calls.append({"size": size, "kwargs": kwargs})
            return fake_renderer_iter3

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfigV3(enable_high_dpi=False))
        a._init_pygame()
        assert len(captured_calls) == 1
        assert captured_calls[0]["kwargs"].get("enable_high_dpi") is False

    def test_app_with_app_config_backward_compatible_true(
        self, fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch
    ) -> None:
        """V3-5：App(AppConfig()) 不传 enable_high_dpi → 兜底 True（向后兼容，无破坏）。

        行为：isinstance(config, AppConfigV3) 为 False → 兜底 enable_high_dpi=True 传给 Renderer。
        """
        from game_app import App, AppConfig
        from game_app import storage as storage_mod
        from game_app import app as app_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)

        captured_calls = []

        def capture_renderer(size, **kwargs):
            captured_calls.append({"size": size, "kwargs": kwargs})
            return fake_renderer_iter3

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfig())
        a._init_pygame()
        # 断言 Renderer 构造 kwargs.enable_high_dpi == True（兜底）
        assert len(captured_calls) == 1
        assert captured_calls[0]["kwargs"].get("enable_high_dpi") is True
