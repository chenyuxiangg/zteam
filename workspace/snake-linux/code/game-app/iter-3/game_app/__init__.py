"""game_app 包对外 re-export。

迭代 2：App + AppConfig + main + AppScreen + InputAction + AppError + HudData
+ StorageUnavailableError (G2-2 iter-2 新增)

迭代 3 增量（G3-4）：AppConfigV3 子类（NFR-04 高分屏清晰）
"""
from __future__ import annotations

from .app import App, main, _DIFFICULTY_LABEL, _STATUS_LABEL
from .config import AppConfig, AppConfigV3  # G3-4 iter-3 新增 AppConfigV3
from .errors import (
    AppError,
    ConfigError,
    GraphicsUnavailableError,
    StorageUnavailableError,
)
from .input import InputAction
from .screens import AppScreen

# HudData 来自 gui-renderer；通过 gui_renderer re-export
try:
    from gui_renderer import HudData  # type: ignore
except Exception:  # noqa: BLE001
    HudData = None  # type: ignore

__all__ = [
    "App",
    "main",
    "AppConfig",
    "AppConfigV3",  # G3-4 iter-3 新增
    "AppScreen",
    "InputAction",
    "AppError",
    "ConfigError",
    "GraphicsUnavailableError",
    "StorageUnavailableError",
    "HudData",
    "_DIFFICULTY_LABEL",
    "_STATUS_LABEL",
]