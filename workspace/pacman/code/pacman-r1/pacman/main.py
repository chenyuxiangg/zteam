"""主入口：argparse + curses.wrapper + 主循环。

职责：组装 Config → 加载地图 → 构建 Game/Renderer → 主循环（输入/推进/渲染）；
      干净退出（wrapper + KeyboardInterrupt 兜底）。
依赖：pacman.config / pacman.map / pacman.game / pacman.input / pacman.renderer。
对应方案：plans/pacman-r1.md §3.1 架构、§3.3 主循环时序、§4.1 CLI 接口、§5.3 边界。
"""

import argparse
import os
import sys
import time

try:
    import curses
except ImportError as e:
    curses = None  # type: ignore
    _CURSES_IMPORT_ERROR = e
else:
    _CURSES_IMPORT_ERROR = None

from .config import (
    Config, DEFAULT_LIVES, DEFAULT_GHOSTS, DEFAULT_LEVEL,
    DEFAULT_SPEED, DEFAULT_MAP, GHOST_BASE_SPEED, HOME_CORNERS,
    MIN_COLS, MIN_LINES, Dir,
)
from .map import load_map, MapError
from .game import Game, Status
from .renderer import Renderer
from .input import parse_key, keycode_to_str, Action


# ============================================================================
# argparse
# ============================================================================
def _build_argparser() -> argparse.ArgumentParser:
    """CLI 参数定义（方案 §4.1）。"""
    p = argparse.ArgumentParser(
        prog="pacman",
        description="Linux 终端版吃豆人游戏（人机对战，差异化 AI）",
    )
    p.add_argument("--map", default=DEFAULT_MAP,
                   help=f"地图文件路径（默认 {DEFAULT_MAP}）")
    p.add_argument("--ghosts", type=int, default=DEFAULT_GHOSTS,
                   help="幽灵数量（2/3/4，默认 4）")
    p.add_argument("--lives", type=int, default=DEFAULT_LIVES,
                   help="初始命数（1..9，默认 3）")
    p.add_argument("--level", type=int, default=DEFAULT_LEVEL,
                   help="起始关卡（≥1，默认 1）")
    p.add_argument("--speed", type=float, default=DEFAULT_SPEED,
                   help="全局速度倍率（0.5..2.0，默认 1.0）")
    p.add_argument("--no-color", action="store_true",
                   help="关闭颜色（单色模式）")
    p.add_argument("--log-ai", action="store_true",
                   help="输出 AI 行为日志（stderr）")
    return p


def _parse_args(argv=None) -> Config:
    """解析 CLI 为 Config，含参数校验。"""
    args = _build_argparser().parse_args(argv)

    # 参数校验（方案 §4.1 错误语义）
    if args.ghosts not in (2, 3, 4):
        print(f"非法 --ghosts={args.ghosts}（合法：2/3/4）", file=sys.stderr)
        sys.exit(2)
    if not (1 <= args.lives <= 9):
        print(f"非法 --lives={args.lives}（合法：1..9）", file=sys.stderr)
        sys.exit(2)
    if args.level < 1:
        print(f"非法 --level={args.level}（合法：≥1）", file=sys.stderr)
        sys.exit(2)
    if not (0.5 <= args.speed <= 2.0):
        print(f"非法 --speed={args.speed}（合法：0.5..2.0）", file=sys.stderr)
        sys.exit(2)

    return Config(
        map_path=args.map,
        ghosts=args.ghosts,
        lives=args.lives,
        level=args.level,
        speed=args.speed,
        no_color=args.no_color,
        log_ai=args.log_ai,
    )


# ============================================================================
# TTY / curses 检查
# ============================================================================
def _check_tty() -> None:
    """非 TTY 报错退出（方案 §5.3）。"""
    if not sys.stdin.isatty():
        print("需要真实终端（stdin 不是 TTY）。请在终端中直接运行。",
              file=sys.stderr)
        sys.exit(1)
    if curses is None:
        print(f"无法导入 curses：{_CURSES_IMPORT_ERROR}。"
              "在 Debian/Ubuntu 极简发行版请执行：apt install python3-curses",
              file=sys.stderr)
        sys.exit(1)


# ============================================================================
# 主循环（wrapper 内部）
# ============================================================================
def _game_loop(stdscr, config: Config, game_map) -> None:
    """curses.wrapper 内执行的主循环。"""
    renderer = Renderer(stdscr, no_color=config.no_color)

    # 终端尺寸检查
    h, w = stdscr.getmaxyx()
    if h < MIN_LINES or w < MIN_COLS:
        renderer.draw(Game(game_map, config))  # 触发尺寸不足分支渲染
        renderer.wait_any_key()
        return

    # 构建对局
    game = Game(game_map, config)

    # 主循环
    last_frame = time.monotonic()
    log_targets = {}

    while True:
        now = time.monotonic()
        dt = now - last_frame
        last_frame = now

        # 输入（不阻塞）
        try:
            keycode = stdscr.getch()
        except curses.error:
            keycode = -1

        if keycode != -1:
            key_str = keycode_to_str(keycode)
            action = parse_key(key_str)
            if action == Action.QUIT:
                return
            elif action == Action.PAUSE:
                if game.status == Status.PLAYING:
                    game.pause()
                elif game.status == Status.PAUSED:
                    game.resume()
            elif game.status == Status.PLAYING:
                if action == Action.TURN_UP:
                    game.player.request_turn(Dir.UP)
                elif action == Action.TURN_DOWN:
                    game.player.request_turn(Dir.DOWN)
                elif action == Action.TURN_LEFT:
                    game.player.request_turn(Dir.LEFT)
                elif action == Action.TURN_RIGHT:
                    game.player.request_turn(Dir.RIGHT)
                # Action.NONE：忽略

        # 暂停时只渲染暂停画面，不推进
        if game.status == Status.PLAYING:
            game.tick()
        elif game.status == Status.GAME_OVER:
            # 等待任意键退出（由 render 内 wait_any_key 在下次 draw 时处理）
            pass

        # --log-ai：每 tick 记录各幽灵目标
        if config.log_ai and game.status == Status.PLAYING:
            from .ghost_ai import target_cell, format_ai_log
            blinky = next((g for g in game.ghosts if g.kind.name == "BLINKY"), None)
            for g in game.ghosts:
                if g.in_house:
                    continue
                log_targets[g.kind] = target_cell(g, game.player, blinky, game_map)
            try:
                sys.stderr.write(format_ai_log(game.ghosts, log_targets, game.player) + "\n")
                sys.stderr.flush()
            except (OSError, ValueError):
                # stderr 不可写：降级静默
                pass

        # 渲染
        renderer.draw(game)

        # 帧率控制：到 100ms 才推进（与 TICK_MS 对齐）
        sleep_for = max(0.0, 0.1 - dt)
        if sleep_for > 0:
            time.sleep(sleep_for)

        # 结算退出
        if game.status == Status.GAME_OVER:
            # 渲染完结算画面后等待任意键
            renderer.wait_any_key()
            return


# ============================================================================
# 公开入口（main_cli）
# ============================================================================
def main_cli(argv=None) -> int:
    """CLI 主入口（被 __main__ / run.py 调用）。"""
    config = _parse_args(argv)
    _check_tty()

    # 加载地图（FR-03 三项离线判定在此执行）
    try:
        game_map = load_map(config.map_path)
    except MapError as e:
        print(f"地图加载失败：{e}", file=sys.stderr)
        return 1

    # curses.wrapper 启动：保证异常路径下终端状态恢复（FR-16）
    try:
        curses.wrapper(_game_loop, config, game_map)
    except KeyboardInterrupt:
        # wrapper 通常已处理；此处兜底
        print("\n已退出。", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"未捕获异常：{e}", file=sys.stderr)
        return 1
    return 0


# ============================================================================
# 便捷入口（用于测试：直接传入 Map）
# ============================================================================
def _ensure_curses_available():
    """测试 / 调试时检查 curses 可用。"""
    if curses is None:
        raise RuntimeError(
            f"无法导入 curses：{_CURSES_IMPORT_ERROR}。"
            "在 Debian/Ubuntu 极简发行版请执行：apt install python3-curses"
        )


if __name__ == "__main__":
    sys.exit(main_cli())
