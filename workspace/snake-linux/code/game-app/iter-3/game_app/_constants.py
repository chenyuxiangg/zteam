"""_constants 模块：app 内常量（标题、颜色等）+ 打包内置字体路径定位。

迭代 4 增量（G4-5 打包内置字体）：
- BUNDLED_FONT_FILENAME：内置中文字体文件名（Source Han Sans CN / OFL）
- get_bundled_font_path()：查找打包内置字体路径——
    1. PyInstaller --onefile 临时目录 sys._MEIPASS
    2. 源码目录 / --onedir 模式（__file__ 邻近）
    3. 失败返回空串（由 _load_cjk_font 走 match_font 回退链兜底）

INV-20：打包内置字体优先级 = sys._MEIPASS > __file__ 邻近 > match_font > Font(None)
"""
from __future__ import annotations

import os
import sys


WINDOW_TITLE = "Snake GUI v2.0.0"

# 菜单自绘配色
MENU_BG = (18, 18, 24)
MENU_TITLE_COLOR = (255, 255, 255)
MENU_DIFFICULTY_DEFAULT = (200, 200, 210)
MENU_DIFFICULTY_HIGHLIGHT = (255, 210, 90)
MENU_HINT_COLOR = (200, 200, 210)
MENU_QUIT_HINT_COLOR = (160, 160, 170)

# 结束画面配色
OVER_BG = (18, 18, 24)
OVER_TITLE_COLOR = (255, 90, 90)
OVER_SCORE_COLOR = (230, 230, 240)
OVER_HINT_COLOR = (200, 200, 210)

# G2-5 iter-2 新增：暂停遮罩配色
PAUSE_OVERLAY_ALPHA = 128
PAUSE_OVERLAY_COLOR = (0, 0, 0, PAUSE_OVERLAY_ALPHA)
PAUSE_OVERLAY_TITLE_COLOR = (255, 210, 90)
PAUSE_OVERLAY_HINT_COLOR = (220, 220, 230)


# ---- iter-4 G4-5 打包内置字体 ----

# 内置中文字体文件名（Source Han Sans CN / Noto Sans CJK SC，OFL 协议）
BUNDLED_FONT_FILENAME = "SourceHanSansCN-Regular.otf"


def get_bundled_font_path() -> str:
    """查找打包内置字体路径（PyInstaller --onefile 临时目录 / 源码目录）。

    查找优先级（INV-20）：
      1. sys._MEIPASS（PyInstaller --onefile 临时解压目录）
      2. __file__ 邻近（源码目录 / --onedir 模式）
      3. 全部失败返回空串（由 fonts._load_cjk_font 走 match_font 回退链兜底）

    Returns:
        字体文件绝对路径；找不到时返回空串 ""（绝不是 None，便于调用方 `if path:` 判断）。
    """
    # 1. PyInstaller --onefile 临时目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, BUNDLED_FONT_FILENAME)
        if os.path.isfile(candidate):
            return candidate

    # 2. 源码目录 / --onedir 模式
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, BUNDLED_FONT_FILENAME)
    if os.path.isfile(candidate):
        return candidate

    return ""


__all__ = [
    "WINDOW_TITLE",
    "MENU_BG", "MENU_TITLE_COLOR", "MENU_DIFFICULTY_DEFAULT",
    "MENU_DIFFICULTY_HIGHLIGHT", "MENU_HINT_COLOR", "MENU_QUIT_HINT_COLOR",
    "OVER_BG", "OVER_TITLE_COLOR", "OVER_SCORE_COLOR", "OVER_HINT_COLOR",
    "PAUSE_OVERLAY_ALPHA", "PAUSE_OVERLAY_COLOR",
    "PAUSE_OVERLAY_TITLE_COLOR", "PAUSE_OVERLAY_HINT_COLOR",
    # G4-5 新增
    "BUNDLED_FONT_FILENAME",
    "get_bundled_font_path",
]