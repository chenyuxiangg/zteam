"""config 模块：AppConfig / AppConfigV3 运行期不可变常量 + 构造期校验。

公开 API：
- AppConfig：dataclass(frozen=True) + __post_init__ 校验（iter-2 沿用）
- AppConfigV3：dataclass(frozen=True)，继承 AppConfig + 新增 enable_high_dpi 字段（G3-4 iter-3）

迭代 3 增量（G3-4 NFR-04 高分屏清晰）：
- AppConfigV3 继承 AppConfig 全部字段 + 新增 enable_high_dpi: bool = True
- 继承父类 __post_init__ 校验（不重写，bool 无非法值）
- App.__init__ 用 isinstance(config, AppConfigV3) 判定，把 enable_high_dpi 传给 Renderer 构造
- 旧 AppConfig 实例向后兼容（isinstance False → 兜底 enable_high_dpi=True）
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True)
class AppConfig:
    """运行期不可变常量。FR-09/NFR-01/NFR-02。

    G2-R-N1：__post_init__ 在构造期校验字段合法性，非法抛 ConfigError。
    iter-3：字段不变；扩展 enable_high_dpi 通过子类 AppConfigV3（G3-4）。
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


@dataclass(frozen=True)
class AppConfigV3(AppConfig):
    """iter-3 扩展：增加 enable_high_dpi 字段（NFR-04 高分屏清晰）。

    字段：父类全部 + enable_high_dpi: bool = True。
    __post_init__ 继承父类（fps_cap/窗口尺寸校验），不重写。
    App.__init__ 用 isinstance(config, AppConfigV3) 判定并把 enable_high_dpi 传给 Renderer 构造；
    iter-2 AppConfig 实例仍可用（isinstance False → 兜底 enable_high_dpi=True）。
    """
    enable_high_dpi: bool = True  # G3-4 iter-3 新增（NFR-04）
    # __post_init__ 继承父类校验（bool 字段无非法值，不需要新增校验）


__all__ = ["AppConfig", "AppConfigV3"]