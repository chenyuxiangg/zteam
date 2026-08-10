"""ui.py — 终端 UI（rich 渲染 / 输入循环 / Ctrl+C 与退出恢复）。

约束（与方案 §3 / §5.4 / §5.5 一致）：
- 使用 rich（唯一第三方运行时依赖）；
- 不接管终端 raw 模式（避免破坏 stty）；
- Ctrl+C / quit / q / exit 由 main 顶层捕获，UI 本身不装 SIGINT handler；
- 黑白子视觉区分：彩色时按颜色；无彩色时用 ●/○ 字符；
- 上一步落子高亮（加粗 + 下划线）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .board import Board, MoveError, parse_move


@dataclass
class GameState:
    """UI 渲染所需的最小状态（与 main 中的回合循环共享）。"""

    turn: str = "B"             # 'B' / 'W'
    last_move: Optional[tuple[int, int]] = None
    message: str = ""           # 状态栏附加消息（如禁手警告）
    over: bool = False
    winner: Optional[str] = None  # 'B' / 'W' / None（平局）
    forbidden_reason: Optional[str] = None  # 禁手原因（人类落子非法时显示）


_B_CHAR = "●"   # 黑
_W_CHAR = "○"   # 白
_DOT_CHAR = "·"


class UI:
    """rich 渲染的终端 UI。无 I/O 接口表要求之外的副作用。"""

    def __init__(self, size: int = 15, *, force_no_color: bool = False) -> None:
        self.size = size
        # 无彩色降级：force_no_color=True 或 NO_COLOR 环境变量
        kwargs = {}
        if force_no_color:
            kwargs["no_color"] = True
        self.console = Console(**kwargs)

    # ---- 渲染 ----

    def render(self, board: Board, state: GameState) -> None:
        """渲染棋盘 + 状态栏。"""
        self.console.clear()
        self._render_state_bar(board, state)
        self._render_board(board, state)
        if state.over:
            self._render_game_over(board, state)
        else:
            self._render_input_hint()

    def _render_state_bar(self, board: Board, state: GameState) -> None:
        turn_text = "黑方 ●" if state.turn == "B" else "白方 ○"
        last = "—" if state.last_move is None else _coord_to_letter(state.last_move[0]) + str(state.last_move[1] + 1)
        last_color = "黑" if state.last_move and board.cell(state.last_move[0], state.last_move[1]) == "B" else "白"
        line = Text()
        line.append(f"当前：{turn_text}    ", style="bold")
        line.append(f"上一步：{last} {last_color}", style="dim")
        if state.message:
            line.append(f"  | {state.message}", style="yellow")
        self.console.print(line)

    def _render_board(self, board: Board, state: GameState) -> None:
        """渲染棋盘主体（Table）。"""
        n = board.size
        # 表头：列字母
        header = Text()
        header.append("    ")  # 行号占位
        for x in range(n):
            letter = chr(ord("A") + x)
            header.append(f" {letter} ", style="bold")
        self.console.print(header)

        for y in range(n):
            row_text = Text()
            row_text.append(f"{y+1:2d} ", style="bold")
            for x in range(n):
                c = board.cell(x, y)
                if c == ".":
                    row_text.append(f" {_DOT_CHAR} ")
                elif c == "B":
                    glyph = _B_CHAR
                    if state.last_move == (x, y):
                        row_text.append(f" {glyph} ", style=Style(bold=True, underline=True, color="cyan"))
                    else:
                        row_text.append(f" {glyph} ", style="bold")
                else:  # W
                    glyph = _W_CHAR
                    if state.last_move == (x, y):
                        row_text.append(f" {glyph} ", style=Style(bold=True, underline=True, color="magenta"))
                    else:
                        row_text.append(f" {glyph} ")
            self.console.print(row_text)

    def _render_input_hint(self) -> None:
        hint = Text()
        hint.append(
            "输入坐标（如 A8 或 8,8），quit / exit 退出：",
            style="dim",
        )
        self.console.print(hint)

    def _render_game_over(self, board: Board, state: GameState) -> None:
        if state.winner is None:
            self.console.print(Text("— 平局 —", style="bold yellow"))
        else:
            glyph = _B_CHAR if state.winner == "B" else _W_CHAR
            color_name = "黑" if state.winner == "B" else "白"
            if state.forbidden_reason:
                msg = f"禁手命中：{_reason_text(state.forbidden_reason)} → 白胜"
                self.console.print(Text(msg, style="bold red"))
            else:
                self.console.print(Text(f"— {glyph} {color_name}方胜 —", style="bold"))

    # ---- 输入 ----

    def get_move(self, board: Board, color: str) -> Optional[tuple[int, int]]:
        """读取人类落子。

        内部循环：捕获 MoveError 与空字符串，提示具体原因并重输。
        quit/q/exit/Ctrl+D 返回 None（交由 main 退出）。
        """
        while True:
            try:
                raw = self.console.input("[bold]落子[/bold] > ")
            except (EOFError, KeyboardInterrupt):
                return None
            text = raw.strip()
            if not text:
                continue
            if text.lower() in ("quit", "q", "exit"):
                return None
            try:
                return parse_move(text, board.size)
            except MoveError as e:
                reason_text = _reason_text(e.reason)
                self.console.print(f"[red]非法输入[/red]：{text!r}（{reason_text}）请重输")
                continue


def _coord_to_letter(x: int) -> str:
    return chr(ord("A") + x)


def _reason_text(reason: str) -> str:
    if reason == "format":
        return "格式错误"
    if reason == "out_of_range":
        return "越界"
    if reason == "occupied":
        return "已占用"
    if reason == "long":
        return "长连（≥6 连）"
    if reason == "double_four":
        return "双四"
    if reason == "double_three":
        return "双三"
    return reason
