"""errors 模块：app 顶层异常层级。

- AppError：app 顶层错误基类
- GraphicsUnavailableError：图形环境不可用（pygame.init / display.set_mode 失败）→ 退出码 2
- ConfigError：AppConfig 字段非法 → 启动时抛
- StorageUnavailableError：HighScoreStore 失败 → 退出码 1（G2-2 iter-2 新增）
"""
from __future__ import annotations


class AppError(RuntimeError):
    """app 顶层错误基类。"""


class GraphicsUnavailableError(AppError):
    """Renderer.init() / pygame.display.set_mode 失败 → 退出码 2（NFR-03 最小集）。"""


class ConfigError(AppError):
    """AppConfig 字段非法（fps_cap <= 0 / window_w < min_window_w）→ 启动时抛。"""


class StorageUnavailableError(AppError):
    """HighScoreStore 读写失败 → 退出码 1。

    包装 platform_storage.StorageError / OSError（mkdir 失败），app 层统一异常类型。
    由 _init_pygame / _dispatch_menu RESET_HIGHSCORE / _new_game 注册的 score_callback 抛出。
    """


__all__ = [
    "AppError",
    "GraphicsUnavailableError",
    "ConfigError",
    "StorageUnavailableError",
]