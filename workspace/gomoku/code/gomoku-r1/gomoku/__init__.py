"""gomoku — Linux 终端五子棋（人机对战）。

包内模块：
    config:           配置数据类 + 默认值
    board:            棋盘与规则层（落子/胜负/禁手/坐标/undo）
    ai:               AI 决策层（评估函数/候选/Alpha-Beta/三档难度/禁手规避）
    ui:               终端 UI（rich 渲染/输入循环/Ctrl+C 与退出恢复）
    main:             主控（CLI 装配/回合循环/重开/退出）
    forbidden_cases:  禁手判定对照表（≥10 例棋形 → 预期结论）
"""

from .board import Board, MoveError

__all__ = ["Board", "MoveError", "__version__"]

__version__ = "0.1.0"
