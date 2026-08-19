"""fonts 模块：CJK 字体加载（迭代 4 G4-5 修订）。

R3-12 沿用 + G4-5 增量：
- 优先级 1：打包内置字体文件（SourceHanSansCN-Regular.otf）—— 走 _constants.get_bundled_font_path()
- 优先级 2：pygame.font.match_font 回退链
- 优先级 3：pygame.font.Font(None, size) —— SDL 默认字体兜底

INV-19/20：
- 全失败后 _cjk_font_fallback == True（菜单/HUD 仍可读英文）
- CJKFontFallbackWarning 在全失败时触发（stderr warning 但不退出）
"""
from __future__ import annotations

import warnings

import pygame  # noqa: F401  # 由 UT 替换为 fake_pygame

from ._constants import get_bundled_font_path
from .errors import CJKFontFallbackWarning


_CJK_FONT_CANDIDATES = [
    "notosanscjksc",       # Debian/Ubuntu: fonts-noto-cjk
    "notosanscjk",
    "wenquanyizenhei",     # 旧版文泉驿
    "wenquanyimicrohei",
    "arialunicodems",      # Windows
]


def _load_cjk_font(size: int, bold: bool = False) -> pygame.font.Font:
    """加载支持 CJK 字符的字体（INV-19/20）。

    迭代 4 优先级（G4-5）：
      1. 打包内置字体文件（SourceHanSansCN-Regular.otf）—— sys._MEIPASS / __file__ 邻近
      2. pygame.font.match_font 回退链（notosanscjksc / wenquanyizenhei / ...）
      3. pygame.font.Font(None, size) —— SDL 默认字体（仅 ASCII，CJK 显示为方框）

    Args:
        size: 字体大小（pt）
        bold: 是否加粗（仅对 match_font / Font(path) 生效）

    Returns:
        pygame.font.Font 实例（永不抛异常——全失败走默认字体兜底）
    """
    # 1. 打包内置字体（优先）
    bundled_path = get_bundled_font_path()
    if bundled_path:
        try:
            font = pygame.font.Font(bundled_path, size)
            font.set_bold(bold)
            return font
        except pygame.error as e:
            warnings.warn(
                f"打包内置字体加载失败 ({bundled_path}): {e}",
                CJKFontFallbackWarning,
                stacklevel=2,
            )

    # 2. match_font 回退链
    for name in _CJK_FONT_CANDIDATES:
        try:
            path = pygame.font.match_font(name, bold=bold)
            if path:
                font = pygame.font.Font(path, size)
                font.set_bold(bold)
                return font
        except pygame.error:
            continue

    # 3. SDL 默认字体兜底（仅 ASCII，CJK 字符显示为方框/乱码）
    warnings.warn(
        "CJK 字体回退链全失败，使用 SDL 默认字体（中文显示为方框）",
        CJKFontFallbackWarning,
        stacklevel=2,
    )
    return pygame.font.Font(None, size)


__all__ = ["_load_cjk_font", "_CJK_FONT_CANDIDATES", "get_bundled_font_path"]