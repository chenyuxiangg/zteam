"""config.py — 配置数据类与默认值。

与方案 §1（范围与默认值）、§5.4（边界处理）对应。
"""

from __future__ import annotations

from dataclasses import dataclass, replace


_VALID_SIZES = (13, 15)
_VALID_DIFFICULTIES = ("weak", "medium", "strong")
_VALID_FORBIDDEN = ("on", "off")
_VALID_HUMAN_COLORS = ("black", "white")


@dataclass(frozen=True)
class Config:
    """不可变配置。所有字段必须在构造时合法（构造期校验）。"""

    size: int = 15           # 棋盘边长；仅 13/15 合法
    difficulty: str = "medium"  # AI 难度；weak/medium/strong
    forbidden: str = "off"   # 禁手规则开关；on/off（仅黑方生效）
    human_color: str = "black"  # 人类执色；black/white（white 为实验性）

    def __post_init__(self) -> None:
        if self.size not in _VALID_SIZES:
            raise ValueError(
                f"size 必须是 {list(_VALID_SIZES)} 之一，得到 {self.size!r}"
            )
        if self.difficulty not in _VALID_DIFFICULTIES:
            raise ValueError(
                f"difficulty 必须是 {_VALID_DIFFICULTIES} 之一，得到 {self.difficulty!r}"
            )
        if self.forbidden not in _VALID_FORBIDDEN:
            raise ValueError(
                f"forbidden 必须是 {_VALID_FORBIDDEN} 之一，得到 {self.forbidden!r}"
            )
        if self.human_color not in _VALID_HUMAN_COLORS:
            raise ValueError(
                f"human_color 必须是 {_VALID_HUMAN_COLORS} 之一，得到 {self.human_color!r}"
            )

    def with_changes(self, **changes) -> "Config":
        """返回带修改字段的新 Config（保持 frozen 不可变）。"""
        return replace(self, **changes)


def parse_args(argv: list[str]) -> Config:
    """解析 CLI 参数为 Config。

    与方案 §2.3、§4（CLI 接口）对应：
        --size 13|15
        --difficulty weak|medium|strong
        --forbidden on|off
        --human black|white
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="gomoku",
        description="Linux 终端五子棋（人机对战）",
    )
    parser.add_argument(
        "--size", type=int, choices=list(_VALID_SIZES), default=15,
        help="棋盘边长（默认 15）",
    )
    parser.add_argument(
        "--difficulty",
        choices=list(_VALID_DIFFICULTIES), default="medium",
        help="AI 难度（默认 medium）",
    )
    parser.add_argument(
        "--forbidden", choices=list(_VALID_FORBIDDEN), default="off",
        help="黑方禁手规则开关（默认 off）",
    )
    parser.add_argument(
        "--human", choices=list(_VALID_HUMAN_COLORS), default="black",
        dest="human_color",
        help="人类执色（默认 black；white 为实验性）",
    )
    args = parser.parse_args(argv)
    return Config(
        size=args.size,
        difficulty=args.difficulty,
        forbidden=args.forbidden,
        human_color=args.human_color,
    )
