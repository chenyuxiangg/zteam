"""screens 模块：app 顶层界面状态机枚举。

G2-1 iter-2 新增 PAUSED 态（FR-12 暂停/继续）。
"""
from __future__ import annotations

from enum import Enum


class AppScreen(Enum):
    """app 顶层界面状态机。FR-11 + FR-12 入口。"""

    MENU = "menu"          # 开始 + 难度选择
    PLAYING = "playing"    # 玩法循环（RUN）
    PAUSED = "paused"      # 暂停态（G2-1 iter-2 新增，FR-12）
    GAME_OVER = "over"     # 结束 + 重开/退出


__all__ = ["AppScreen"]