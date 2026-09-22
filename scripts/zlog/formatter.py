"""Formatters: turn a Record into a string.

A Formatter is anything callable that takes a Record and returns a str.
Two helpers are provided:

- ``template(fmt)`` — placeholder substitution from a template string.
- Use any callable directly (lambda, function) for fully custom logic.
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from .record import Record


@runtime_checkable
class Formatter(Protocol):
    """Protocol for anything callable ``Record -> str``."""

    def __call__(self, record: Record) -> str: ...


def template(fmt: str) -> Formatter:
    """Build a Formatter from a template string.

    Placeholders match Record.asdict() keys plus any user-supplied field::

        template("{ts}|{level_name:8}|{func}:{lineno}|{message}")
        template("{ts} [{level_name}] {func}: {message} (project={project})")
    """

    def _format(record: Record) -> str:
        return fmt.format(**record.asdict())

    return _format
