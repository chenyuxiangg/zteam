"""Gomoku — Linux terminal gomoku (human vs AI).

A configurable, terminal-rendered gomoku implementation following the
project's plan §3 module layout.

Public submodules:
    config  - configuration model and defaults (immutable dataclass)
    board   - rules engine (place / win / forbidden / full / parse_move)
    ai      - AI decision (weak / medium / strong) with forbidden-move prefilter
    ui      - rich-based rendering and input loop
    main    - CLI entry point
"""

__all__ = ["config", "board", "ai", "ui", "main"]
__version__ = "0.4.0"
