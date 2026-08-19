"""config 模块：AppConfig 运行期不可变常量 + 构造期校验（G2-R-N1）。

公开 API：
- AppConfig：dataclass(frozen=True) + __post_init__ 校验
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True)
class AppConfig:
    """运行期不可变常量。FR-09/NFR-01/NFR-02。

    G2-R-N1：__post_init__ 在构造期校验字段合法性，非法抛 ConfigError。
    """
    window_w: int = 640
    window_h: int = 480
    fps_cap: int = 60
    min_window_w: int = 512
    min_window_h: int = 472

    def __post_init__(self) -> None:
        """构造期校验（避免运行时崩溃）。"""
        if self.fps_cap <= 0:
            raise ConfigError(f"fps_cap 必须 > 0，收到 {self.fps_cap}")
        if self.window_w < self.min_window_w or self.window_h < self.min_window_h:
            raise ConfigError(
                f"窗口尺寸 ({self.window_w}, {self.window_h}) 小于最小可玩 "
                f"({self.min_window_w}, {self.min_window_h})"
            )


__all__ = ["AppConfig"]