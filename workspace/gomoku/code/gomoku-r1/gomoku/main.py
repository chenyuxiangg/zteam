"""main.py — 主控（CLI 装配 / 回合循环 / 重开 / 退出）。

约束（与方案 §3 / §5.4 一致）：
- CLI 参数解析（argparse）→ Config；
- 装配 Board / AI / UI；
- 主循环：渲染 → 落子（人类或 AI）→ 胜负 / 禁手 / 满盘判定 → 终局提示 → 重开/退出；
- Ctrl+C 顶层捕获并礼貌退出（exit 0）。

辅助：
    main(): CLI 入口；
    game_loop(...): 启动一回合循环（便于测试）。
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from .ai import choose_move
from .board import Board, MoveError, parse_move
from .config import Config, parse_args
from .ui import GameState, UI


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 入口。返回 exit code（0=正常退出）。"""
    try:
        cfg = parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2

    return game_loop(cfg)


def game_loop(cfg: Config, *, board: Board | None = None, ui: UI | None = None) -> int:
    """跑一回合循环；终局后询问重开/退出。

    注入 board/UI 用于测试；不传则新建。
    """
    if board is None:
        board = Board(cfg.size)
    if ui is None:
        ui = UI(cfg.size)

    human_color = "B" if cfg.human_color == "black" else "W"
    ai_color = "W" if human_color == "B" else "B"

    while True:
        # 渲染初始棋盘
        state = _initial_state(human_color)
        board.reset()
        ui.render(board, state)
        # 主循环
        try:
            while not state.over:
                if state.turn == human_color:
                    _human_turn(board, state, ui)
                else:
                    _ai_turn(board, state, cfg, ai_color, ui)
                # 胜负 / 满盘判定
                _post_turn_check(board, state)
                ui.render(board, state)
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C / Ctrl+D 退出
            ui.console.print("\n[bold]退出[/bold]")
            return 0

        # 终局 → 询问重开
        try:
            ans = ui.console.input("\n重开？(y/n) [默认 y] > ")
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans.strip().lower() in ("n", "no"):
            ui.console.print("[bold]退出[/bold]")
            return 0
        # 否则进入下一轮，保持 cfg


def _initial_state(human_color: str) -> GameState:
    """开局状态：人类执色方先手；消息为空。"""
    return GameState(turn=human_color, last_move=None, message="", over=False)


def _human_turn(board: Board, state: GameState, ui: UI) -> None:
    """人类落子：循环读取坐标 → 校验 → 落子。"""
    while True:
        move = ui.get_move(board, state.turn)
        if move is None:
            # 退出
            raise KeyboardInterrupt()
        x, y = move
        # 占用校验（额外检查，因为 parse_move 不查占用）
        if board.cell(x, y) != ".":
            ui.console.print(f"[red]已占用[/red]：({x}, {y})")
            continue
        # 禁手检查（黑方）
        if state.turn == "B" and board.check_forbidden(x, y, "B")[0]:
            fb, reason = board.check_forbidden(x, y, "B")
            # 禁手当判黑负白胜——但禁手判定前先看是否成五；成五则胜
            # board.check_forbidden 已内部按"成五优先"返回 (False, None)
            # 这里若返回 True，表示确实禁手 → 黑负
            state.forbidden_reason = reason
            state.over = True
            state.winner = "W"
            return
        # 落子
        ok = board.place(x, y, state.turn)
        if not ok:
            ui.console.print("[red]落子失败[/red]")
            continue
        state.last_move = (x, y)
        # 检查成五：人类刚落，立即判
        winner = board.check_win(x, y)
        if winner:
            state.over = True
            state.winner = winner
            return
        # 切换回合
        state.turn = "W" if state.turn == "B" else "B"
        state.message = ""
        state.forbidden_reason = None
        return


def _ai_turn(board: Board, state: GameState, cfg: Config, ai_color: str, ui: UI) -> None:
    """AI 落子：按 cfg.difficulty 调 AI。"""
    state.message = f"AI 思考中（{cfg.difficulty}）..."
    ui.render(board, state)
    t0 = time.monotonic()
    # 时间预算：弱/中 0.5s，强 2s（与方案 §5.3 / README §6 一致）
    time_budget = {"weak": 0.05, "medium": 0.2, "strong": 2.0}.get(cfg.difficulty, 0.2)
    move = choose_move(
        board,
        ai_color,
        difficulty=cfg.difficulty,
        time_budget=time_budget,
    )
    elapsed = time.monotonic() - t0
    if move is None:
        # 无合法点（满盘）—— 由 _post_turn_check 处理平局
        return
    x, y = move
    board.place(x, y, ai_color)
    state.last_move = (x, y)
    state.message = f"AI：{chr(ord('A') + x)}{y + 1}（{elapsed:.2f}s）"
    winner = board.check_win(x, y)
    if winner:
        state.over = True
        state.winner = winner
        return
    state.turn = "B" if state.turn == "W" else "W"


def _post_turn_check(board: Board, state: GameState) -> None:
    """每次落子后：检查满盘 / 平局；如成五已由调用者 set state.over。"""
    if state.over:
        return
    if board.is_full():
        state.over = True
        state.winner = None  # 平局


# Board.reset 已在 board.py 中实现，无需此处 monkey-patch。


if __name__ == "__main__":
    raise SystemExit(main())
