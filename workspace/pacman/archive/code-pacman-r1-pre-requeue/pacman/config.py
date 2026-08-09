"""运行配置与命令行解析。

职责：保存需求默认值、校验 CLI 覆盖项；对应开发方案 §3.2、§4.1、§5.4。
依赖：Python 标准库 argparse/dataclasses/pathlib。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_MAP = PACKAGE_DIR / "data" / "map_classic.txt"
TICK_SECONDS = 0.1
MIN_TERM_COLS = 80
MIN_TERM_LINES = 24


@dataclass(frozen=True)
class Config:
    """一次游戏会话的不可变配置。"""

    map_path: Path = DEFAULT_MAP
    ghost_count: int = 4
    lives: int = 3
    no_color: bool = False
    speed: float = 1.0
    start_level: int = 1


def _bounded_int(name: str, minimum: int, maximum: Optional[int] = None):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} 必须是整数") from exc
        if number < minimum or (maximum is not None and number > maximum):
            upper = f"..{maximum}" if maximum is not None else " 或更大"
            raise argparse.ArgumentTypeError(f"{name} 必须在 {minimum}{upper} 范围内")
        return number

    return parse


def _speed(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("speed 必须是数字") from exc
    if not 0.5 <= number <= 2.0:
        raise argparse.ArgumentTypeError("speed 必须在 0.5..2.0 范围内")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pacman",
        description="Linux 终端版 Pac-Man（Python curses，零第三方依赖）",
    )
    parser.add_argument("--map", dest="map_path", type=Path, default=DEFAULT_MAP,
                        help="地图文件路径（默认使用内置 22x19 地图）")
    parser.add_argument("--ghosts", dest="ghost_count", type=int,
                        choices=(2, 3, 4), default=4,
                        help="幽灵数量：2、3 或 4（默认 4）")
    parser.add_argument("--lives", type=_bounded_int("lives", 1, 9), default=3,
                        help="初始命数 1..9（默认 3）")
    parser.add_argument("--no-color", action="store_true",
                        help="禁用颜色，仅用字符区分元素")
    parser.add_argument("--speed", type=_speed, default=1.0,
                        help="全局速度倍率 0.5..2.0（默认 1.0）")
    parser.add_argument("--level", dest="start_level",
                        type=_bounded_int("level", 1), default=1,
                        help="起始关卡（默认 1）")
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> Config:
    args = build_parser().parse_args(argv)
    return Config(
        map_path=args.map_path.expanduser(),
        ghost_count=args.ghost_count,
        lives=args.lives,
        no_color=args.no_color,
        speed=args.speed,
        start_level=args.start_level,
    )
