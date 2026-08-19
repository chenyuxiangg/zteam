"""AppConfig 单测（UT 2/3/4/5）。

需求：FROZEN + 默认值 + 字段校验（fps_cap/窗口尺寸）。
"""
from __future__ import annotations

import dataclasses
import pytest

from game_app.config import AppConfig
from game_app.errors import ConfigError


class TestAppConfigDefaults:
    def test_default_values(self) -> None:
        cfg = AppConfig()
        assert cfg.window_w == 640
        assert cfg.window_h == 480
        assert cfg.fps_cap == 60
        assert cfg.min_window_w == 512
        assert cfg.min_window_h == 472

    def test_frozen(self) -> None:
        cfg = AppConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.fps_cap = 30  # type: ignore[misc]


class TestAppConfigValidation:
    @pytest.mark.parametrize("bad_fps", [0, -1, -100])
    def test_invalid_fps_cap(self, bad_fps: int) -> None:
        with pytest.raises(ConfigError):
            AppConfig(fps_cap=bad_fps)

    def test_window_w_below_min(self) -> None:
        with pytest.raises(ConfigError):
            AppConfig(window_w=400)

    def test_window_h_below_min(self) -> None:
        with pytest.raises(ConfigError):
            AppConfig(window_h=300)

    def test_valid_custom_values_pass(self) -> None:
        cfg = AppConfig(window_w=800, window_h=600, fps_cap=30)
        assert cfg.window_w == 800
        assert cfg.window_h == 600
        assert cfg.fps_cap == 30