"""fonts 模块：CJK 字体回退链（R3-12）。

顺序：notosanscjksc → notosanscjk → wenquanyizenhei → wenquanyimicrohei → arialunicodems → SDL 默认字体。
"""
from __future__ import annotations

import pygame  # noqa: F401  # 由 UT 替换为 fake_pygame


_CJK_FONT_CANDIDATES = [
    "notosanscjksc",       # Debian/Ubuntu: fonts-noto-cjk
    "notosanscjk",
    "wenquanyizenhei",     # 旧版文泉驿
    "wenquanyimicrohei",
    "arialunicodems",      # Windows
]


def _load_cjk_font(size: int, bold: bool = False) -> pygame.font.Font:
    """R3-12 CJK 字体回退链：依次 match_font 候选；全失败 → SDL 默认字体。"""
    for name in _CJK_FONT_CANDIDATES:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)  # SDL 默认字体兜底（不崩，文字可能为 □）


__all__ = ["_load_cjk_font", "_CJK_FONT_CANDIDATES"]