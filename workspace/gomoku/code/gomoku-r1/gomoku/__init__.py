"""Gomoku — Linux terminal gomoku (human vs AI).

A configurable, terminal-rendered gomoku implementation following the
project's plan §3 module layout.

Public submodules:
    config  - configuration model and defaults
    board   - rules engine (place / win / forbidden / full / parse_move)
    ai      - AI decision (weak / medium / strong)
    ui      - rich-based rendering and input loop
    main    - CLI entry point

Note: see roles/code-developer.md for the role contract; this package
implements plan §3-§5 of workspace/gomoku/plans/gomoku-r1.md.
"""
from __future__ import annotations

__all__ = ["config", "board", "ai", "ui", "main"]
__version__ = "0.2.0"
