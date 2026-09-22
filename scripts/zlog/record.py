"""Immutable log record: one piece of logging data on its way to sinks.

A Record is constructed once by the Logger and then passed through
Formatters and Sinks. It carries no I/O or formatting concerns itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .levels import LEVEL_NAMES


@dataclass(frozen=True, slots=True)
class Record:
    ts: datetime
    level: int
    func: str           # caller function / method name
    lineno: int         # caller line number
    message: str
    fields: Mapping[str, Any]
    role: str = ""      # optional subsystem role bound to the Logger

    def asdict(self) -> dict[str, Any]:
        """Return a flat dict suitable for ``str.format(**...)`` templates.

        Includes both ``level`` (int) and ``level_name`` (str) so templates
        can pick whichever reads better. User-supplied ``fields`` are merged
        last, so they can override defaults if desired (rarely useful).

        Also computes ``kv`` — a space-joined ``key=value`` rendering of
        ``self.fields`` (with quoted values when the value contains
        whitespace). Empty string when no fields are present, so
        templates can always include ``{kv}`` unconditionally.
        """
        d: dict[str, Any] = {
            "ts": self.ts.isoformat(timespec="milliseconds"),
            "level": self.level,
            "level_name": LEVEL_NAMES[self.level],
            "func": self.func,
            "lineno": self.lineno,
            "role": self.role,
            "message": self.message,
            "kv": _render_kv(self.fields),
        }
        d.update(self.fields)
        return d


def _render_kv(fields: Mapping[str, Any]) -> str:
    """Render a fields mapping as ``k=v`` pairs, quoting values with spaces.

    Examples::

        {}                                     -> ""
        {"project": "zteam"}                   -> "project=zteam"
        {"reason": "quota critical"}           -> 'reason="quota critical"'
        {"a": 1, "b": "two words", "c": True}  -> 'a=1 b="two words" c=True'
    """
    parts: list[str] = []
    for k, v in fields.items():
        sv = str(v)
        if " " in sv or "\t" in sv:
            sv = f'"{sv}"'
        parts.append(f"{k}={sv}")
    return " ".join(parts)