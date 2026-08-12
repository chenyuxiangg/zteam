"""Configuration model for gomoku.

The :class:`Config` dataclass is the single source of truth for runtime
parameters.  It is constructed from CLI arguments in :mod:`gomoku.main` and
immutable thereafter.  See plan §4 (interfaces) and §5.4 (edge handling).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Literal

ALLOWED_SIZES = (13, 15)
ALLOWED_DIFFICULTIES = ("weak", "medium", "strong")
ALLOWED_HUMAN_COLORS = ("black", "white")
ALLOWED_FORBIDDEN = ("on", "off")

Size = Literal[13, 15]
Difficulty = Literal["weak", "medium", "strong"]
HumanColor = Literal["black", "white"]
Forbidden = Literal["on", "off"]


@dataclass(frozen=True)
class Config:
    """Immutable game configuration.

    Attributes
    ----------
    size:
        Board side length.  Only 13 or 15 are accepted (plan §1).
    difficulty:
        AI strength: ``weak`` / ``medium`` / ``strong``.
    forbidden:
        Whether Renju forbidden moves apply (``on`` / ``off``).
    human_color:
        Which side the human plays.  ``black`` (default) means the human
        moves first.  ``white`` is the experimental swap.
    debug_timing:
        When True, ``ui.render`` records per-frame render timings to stderr.
    """

    size: Size
    difficulty: Difficulty
    forbidden: Forbidden
    human_color: HumanColor = "black"
    debug_timing: bool = False

    # -- derived helpers --------------------------------------------------

    @property
    def forbidden_enabled(self) -> bool:
        """Whether forbidden-move detection is active for this game."""

        return self.forbidden == "on"

    @property
    def ai_color(self) -> str:
        """The color the AI plays (``'W'`` if human is black, else ``'B'``)."""

        return "W" if self.human_color == "black" else "B"

    @property
    def human_letter(self) -> str:
        """The color letter used on the board for the human side."""

        return "B" if self.human_color == "black" else "W"


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.  Kept in :mod:`config` so it can be
    reused by tests and tools."""

    parser = argparse.ArgumentParser(
        prog="gomoku",
        description="Linux terminal gomoku (human vs AI).",
    )
    parser.add_argument(
        "--size",
        choices=[str(s) for s in ALLOWED_SIZES],
        default="15",
        help="Board side length (13 or 15).",
    )
    parser.add_argument(
        "--difficulty",
        choices=ALLOWED_DIFFICULTIES,
        default="medium",
        help="AI strength: weak / medium / strong.",
    )
    parser.add_argument(
        "--forbidden",
        choices=ALLOWED_FORBIDDEN,
        default="off",
        help="Renju forbidden-move rule (black double-three / double-four / overline).",
    )
    parser.add_argument(
        "--human",
        dest="human_color",
        choices=ALLOWED_HUMAN_COLORS,
        default="black",
        help="Side the human plays.  Default: black (human moves first).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="gomoku 0.4.0",
    )
    parser.add_argument(
        "--debug-timing",
        action="store_true",
        help="Emit per-frame render timings to stderr (NFR-02 verification).",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    """Build a :class:`Config` from parsed CLI args."""

    return Config(
        size=int(args.size),  # type: ignore[arg-type]
        difficulty=args.difficulty,  # type: ignore[arg-type]
        forbidden=args.forbidden,  # type: ignore[arg-type]
        human_color=args.human_color,  # type: ignore[arg-type]
        debug_timing=bool(args.debug_timing),
    )
