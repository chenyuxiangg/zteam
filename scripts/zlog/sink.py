"""Output sinks: write formatted log lines somewhere.

Each Sink has its own level threshold and its own Formatter, independent
of every other Sink. A Sink's job is only to emit a string it has been
given — formatting decisions live one layer up.

The default formatter is pipe-delimited (``|`` between every standard
field) so the line is unambiguously machine-parseable. See
``DEFAULT_FORMAT`` for the template string.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import List, Optional

from .formatter import Formatter, template
from .levels import ERROR, INFO, parse_level


DEFAULT_FORMAT = "{ts}|{level_name:8}|{func}:{lineno}|{role:10}|{message}|{kv}"


class Sink:
    """Base class. Subclasses implement ``_emit(line)``.

    ``accepts(level)`` is the per-sink filter: enabled AND level high enough.
    The Logger calls this once per record per sink, so a sink can be
    individually silenced (enabled=False) without touching anything else.
    """

    def __init__(
        self,
        level: int = INFO,
        formatter: Optional[Formatter] = None,
        enabled: bool = True,
    ):
        self.level = parse_level(level) if isinstance(level, str) else level
        self.formatter: Formatter = formatter or template(DEFAULT_FORMAT)
        self.enabled = enabled

    def set_level(self, level) -> "Sink":
        self.level = parse_level(level)
        return self

    def set_enabled(self, enabled: bool) -> "Sink":
        self.enabled = enabled
        return self

    def accepts(self, level: int) -> bool:
        return self.enabled and level >= self.level

    def _emit(self, line: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Release resources. Safe to call multiple times."""

    # Convenience for tests / introspection
    def __repr__(self) -> str:
        return f"<{type(self).__name__} level={self.level} enabled={self.enabled}>"


class StdoutSink(Sink):
    """Write to stdout. Typical target for cron ``deliver=telegram``."""

    def __init__(self, level: int = INFO, formatter: Optional[Formatter] = None):
        super().__init__(level, formatter)

    def _emit(self, line: str) -> None:
        print(line, flush=True)


class StderrSink(Sink):
    """Write to stderr. Defaults to ERROR so routine info does not pollute it."""

    def __init__(self, level: int = ERROR, formatter: Optional[Formatter] = None):
        super().__init__(level, formatter)

    def _emit(self, line: str) -> None:
        print(line, file=sys.stderr, flush=True)


class FileSink(Sink):
    """Append to a file. Thread-safe via an internal lock.

    Creates parent directories if missing. The file handle stays open for
    the lifetime of the sink; call ``close()`` to release it.
    """

    def __init__(
        self,
        path: str,
        level: int = INFO,
        formatter: Optional[Formatter] = None,
        mode: str = "a",
        encoding: str = "utf-8",
    ):
        super().__init__(level, formatter)
        self.path = path
        self.mode = mode
        self.encoding = encoding
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._fp = open(path, mode, encoding=encoding)  # noqa: SIM115
        self._closed = False

    def _emit(self, line: str) -> None:
        if self._closed:
            return
        with self._lock:
            if self._closed:
                return
            self._fp.write(line + "\n")
            self._fp.flush()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._fp.close()


class RotatingFileSink(FileSink):
    """File sink with size-based rotation.

    ``backup_count`` is the **total number of files** kept on disk
    (current + backups). For example, ``backup_count=5`` keeps::

        app.log      ← current
        app.log.1    ← most recent backup
        app.log.2
        app.log.3
        app.log.4    ← oldest, dropped on next rotation

    Two rotation modes:

    - ``"delete_oldest"`` (default): when ``current_size + new_line_bytes
      > max_bytes``, shift backups down by one (drop the oldest) and
      rename the current file to ``app.log.1``. Then write the new line.

    - ``"no_rotate"``: ignore ``max_bytes`` and never rotate; the file
      grows unbounded. Useful when external logrotate handles rotation.

    Thread-safe via the parent's ``_lock``. Rotation happens **before**
    write so the new line always fits; no single line is ever lost or
    truncated mid-rotation.
    """

    def __init__(
        self,
        path: str,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        mode: str = "delete_oldest",
        level: int = INFO,
        formatter: Optional[Formatter] = None,
        encoding: str = "utf-8",
    ):
        super().__init__(
            path,
            level=level,
            formatter=formatter,
            mode="a",
            encoding=encoding,
        )
        if backup_count < 1:
            raise ValueError("backup_count must be >= 1")
        if mode not in ("delete_oldest", "no_rotate"):
            raise ValueError(f"unknown rotation mode: {mode!r}")
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.rotation_mode = mode

    def _current_size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def _should_rotate(self, incoming_size: int) -> bool:
        if self.rotation_mode == "no_rotate":
            return False
        return self._current_size() + incoming_size > self.max_bytes

    def _rotate(self) -> None:
        """Shift backups: drop oldest, rename current to .1.

        Caller must have the file handle closed (we re-open afterward).
        Single-filesystem ``os.rename`` is atomic; conflicting
        destinations are removed first.
        """
        oldest = f"{self.path}.{self.backup_count - 1}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(self.backup_count - 2, 0, -1):
            src = f"{self.path}.{i}"
            dst = f"{self.path}.{i + 1}"
            if os.path.exists(src):
                os.rename(src, dst)
        if os.path.exists(self.path):
            os.rename(self.path, f"{self.path}.1")

    def _emit(self, line: str) -> None:
        if self._closed:
            return
        incoming = len((line + "\n").encode(self.encoding))
        needs_rotation = self._should_rotate(incoming)

        with self._lock:
            if self._closed:
                return
            if needs_rotation:
                self._fp.close()
                self._closed = True
                self._rotate()
                self._fp = open(self.path, "a", encoding=self.encoding)
                self._closed = False
            self._fp.write(line + "\n")
            self._fp.flush()


class MemorySink(Sink):
    """Store emitted lines in memory. Useful for tests and inspection."""

    def __init__(self, level: int = INFO, formatter: Optional[Formatter] = None):
        super().__init__(level, formatter)
        self.records: List[str] = []

    def _emit(self, line: str) -> None:
        self.records.append(line)

    def clear(self) -> None:
        self.records.clear()