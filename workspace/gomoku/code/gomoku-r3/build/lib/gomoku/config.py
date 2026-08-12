"""Configuration model and defaults (plan §3 / §4 / §8).

This module is pure data: no I/O, no rich, no side effects. It exposes a
``Config`` dataclass that the CLI (main.py) builds from argparse and that
the rest of the code consumes read-only.

Defaults (plan §8):
    size:         15       (alternatives: 13)
    difficulty:   "medium" (alternatives: "weak" / "strong"; TQ1)
    forbidden:    False    (alternatives: True; plan Q4)
    human_color:  "B"      (alternatives: "W"; plan Q5)
"""
from __future__ import annotations

from dataclasses import dataclass


# Plan §3 / §4: only 13 and 15 are accepted sizes.
ALLOWED_SIZES = (13, 15)

# Plan §3 / §8: three difficulty tiers.
ALLOWED_DIFFICULTIES = ("weak", "medium", "strong")

# Plan §3 / §4 / §5.2: black is the only color subject to forbidden-move
# rules. White has no forbidden-move constraint.
ALLOWED_COLORS = ("B", "W")


@dataclass(frozen=True)
class Config:
    """Immutable game configuration (plan §4)."""

    size: int = 15
    difficulty: str = "medium"
    forbidden: bool = False
    human_color: str = "B"

    def __post_init__(self) -> None:  # pragma: no cover - trivial validation
        if self.size not in ALLOWED_SIZES:
            raise ValueError(
                f"size must be one of {ALLOWED_SIZES}, got {self.size!r}"
            )
        if self.difficulty not in ALLOWED_DIFFICULTIES:
            raise ValueError(
                f"difficulty must be one of {ALLOWED_DIFFICULTIES}, "
                f"got {self.difficulty!r}"
            )
        if self.human_color not in ALLOWED_COLORS:
            raise ValueError(
                f"human_color must be one of {ALLOWED_COLORS}, "
                f"got {self.human_color!r}"
            )

    @property
    def ai_color(self) -> str:
        """Color the AI plays. Always the opposite of the human color."""
        return "W" if self.human_color == "B" else "B"
