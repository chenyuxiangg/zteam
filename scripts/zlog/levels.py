"""Log level constants and parsing.

Levels are numeric so they can be compared directly. Higher number = more severe.
The numeric gap (10) leaves room for custom levels between the built-ins.
"""
from __future__ import annotations

DEBUG = 10
INFO = 20
WARN = 30
ERROR = 40
CRITICAL = 50

# Bidirectional lookup for human-readable names.
LEVEL_NAMES: dict[int, str] = {
    DEBUG: "DEBUG",
    INFO: "INFO",
    WARN: "WARN",
    ERROR: "ERROR",
    CRITICAL: "CRITICAL",
}
NAME_TO_VALUE: dict[str, int] = {name: value for value, name in LEVEL_NAMES.items()}


def parse_level(level) -> int:
    """Accept a level as either an int (10/20/...) or a name ("INFO"/"info"/...).

    Returns the numeric value. Raises ValueError for anything unrecognized
    (None, floats, unknown names, unknown ints, bools, etc.).
    """
    if isinstance(level, str):
        upper = level.upper()
        if upper not in NAME_TO_VALUE:
            valid = ", ".join(NAME_TO_VALUE)
            raise ValueError(f"unknown level name: {level!r} (valid: {valid})")
        return NAME_TO_VALUE[upper]
    # bool is a subclass of int — exclude explicitly
    if isinstance(level, int) and not isinstance(level, bool):
        if level not in LEVEL_NAMES:
            valid = ", ".join(str(v) for v in LEVEL_NAMES)
            raise ValueError(f"unknown level value: {level} (valid: {valid})")
        return level
    raise ValueError(
        f"level must be int or str, got {type(level).__name__}"
    )
