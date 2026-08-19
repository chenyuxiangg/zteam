"""errors 模块：app 顶层异常层级。

- AppError：app 顶层错误基类
- GraphicsUnavailableError：图形环境不可用（pygame.init / display.set_mode 失败）→ 退出码 2
- ConfigError：AppConfig 字段非法 → 启动时抛
- StorageUnavailableError：HighScoreStore 失败 → 退出码 1（G2-2 iter-2 新增）

迭代 4 增量（G4-2 NFR-03 错误提示完善）：
- GraphicsUnavailableError 新增 `suggestion: str = ""` 字段（INV-17 退出码 2 路径写入 stderr）
- StorageUnavailableError 新增 `suggestion: str = ""` 字段 + 退出码由 1 改为 3（G4-2 新增）
  - 通过 error_to_exit_code() 函数统一映射（精确类型 > 基类 > 默认 1）
- 新增 3 类 UserWarning 子类（非致命，stderr warning）：
  - HighDPIWarning：HiDPI 缩放失败 → 自动降级
  - CJKFontFallbackWarning：CJK 字体回退链全失败 → SDL 默认字体
  - PlatformUnsupportedWarning：macOS <12 / Windows <10 → 尽力兼容
"""
from __future__ import annotations

from typing import Final


class AppError(RuntimeError):
    """app 顶层错误基类。"""


class GraphicsUnavailableError(AppError):
    """Renderer.init() / pygame.display.set_mode 失败 → 退出码 2（NFR-03 最小集）。

    iter-4 增量（G4-2）：
    - 新增 `suggestion: str = ""` 字段——人类可读的建议，由 main() 写入 stderr。
    """

    def __init__(self, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion


class ConfigError(AppError):
    """AppConfig 字段非法（fps_cap <= 0 / window_w < min_window_w）→ 启动时抛。"""


class StorageUnavailableError(AppError):
    """HighScoreStore 读写失败 → 退出码 3（G4-2 新增退出码，区分于一般 AppError 的 1）。

    包装 platform_storage.StorageError / OSError（mkdir 失败），app 层统一异常类型。
    由 _init_pygame / _dispatch_menu RESET_HIGHSCORE / _new_game 注册的 score_callback 抛出。

    iter-4 增量（G4-2）：
    - 新增 `suggestion: str = ""` 字段——人类可读的建议（"检查 ~/.local/share 权限"），
      由 main() 写入 stderr 后返退出码 3。
    """

    def __init__(self, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion


# ---- 迭代 4 G4-2 新增：非致命警告类（UserWarning 子类，stderr warning 但不退出） ----

class HighDPIWarning(UserWarning):
    """HiDPI 缩放失败警告：自动降级到非 SCALED 模式，stderr warning，不退出。"""


class CJKFontFallbackWarning(UserWarning):
    """CJK 字体回退链全失败警告：使用 SDL 默认字体，stderr warning，不退出。"""


class PlatformUnsupportedWarning(UserWarning):
    """平台版本低于最低要求警告（macOS <12 / Windows <10）：尽力兼容，stderr warning，不退出。"""


# ---- 迭代 4 G4-2 新增：退出码映射函数 ----

_EXIT_CODE_MAP: Final[dict] = {
    ConfigError: 1,
    GraphicsUnavailableError: 2,
    StorageUnavailableError: 3,  # G4-2 新增退出码 3
    # AppError 默认 1（未列出的子类走 isinstance 命中基类后兜底）
}


def error_to_exit_code(error: BaseException) -> int:
    """G4-2 新增：根据异常类型映射退出码。

    优先级：精确类型 > AppError 基类 > 默认 1。

    退出码语义：
      0 = 正常退出
      1 = app 异常（ConfigError / AppError 默认）
      2 = 图形环境不可用（GraphicsUnavailableError）
      3 = 用户数据目录不可写（StorageUnavailableError，G4-2 新增）

    Args:
        error: 待映射的异常对象（任意 BaseException）

    Returns:
        对应的进程退出码（int ∈ {1, 2, 3}）
    """
    for exc_type, code in _EXIT_CODE_MAP.items():
        if isinstance(error, exc_type):
            return code
    # 未命中精确类型 → 检查 AppError 基类
    if isinstance(error, AppError):
        return 1
    return 1


__all__ = [
    "AppError",
    "GraphicsUnavailableError",
    "ConfigError",
    "StorageUnavailableError",
    "HighDPIWarning",
    "CJKFontFallbackWarning",
    "PlatformUnsupportedWarning",
    "error_to_exit_code",
]