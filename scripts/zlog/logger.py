"""Logger: the entry point for emitting log records.

A Logger owns a list of Sinks and a global level. Every ``log()`` call
filters once at the Logger level, then walks every Sink for per-sink
filtering and emission. Formatting is per-sink, so the same Record can
appear as plain text in one file and JSON in another.

Thread safety
-------------
- ``get_logger`` is guarded by ``_registry_lock`` and only returns
  already-registered loggers; concurrent callers asking for the same
  name receive the same instance.
- ``add_sink`` / ``remove_sink`` snapshot the sink list under ``_lock``
  before dispatching, so mutating sinks mid-emit does not crash.
- ``log()`` is reentrant across threads: records are emitted to each
  sink serially in registration order. A slow or failing sink cannot
  starve its siblings (faults are caught and logged to stderr), but it
  does block the dispatch loop until it returns — dispatch is
  intentionally synchronous to preserve order and avoid thread churn.

Caller attribution
------------------
Every Record carries ``func`` (caller function name) and ``lineno``
(caller line number), captured via ``sys._getframe(1)``. This makes
records self-locating without the caller having to pass file/line
info manually. The capture cost is paid only for records that pass
the level filter.

Lazy initialization
-------------------
There is exactly one global config file: ``<default_config_dir>/output_config.json``
(``scripts/zlog/config/output_config.json`` in this repo). It declares
every named logger the process may need.

On the first ``get_logger(name)`` call the registry checks whether
logging has been initialized. If not, it loads
``output_config.json`` and registers every logger declared inside.
Subsequent ``get_logger`` calls return from the registry without
touching disk. If the requested name is not declared in the config,
``KeyError`` is raised so missing-config typos surface immediately.

To preload the config explicitly before any ``get_logger`` call, use
:func:`init_logging` (e.g. at the top of an entry-point script).

Direct construction via ``Logger(...)`` is permitted but documented as
a test-only escape hatch; production code must go through the JSON
config.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from typing import Any, List, Optional, Union

from .levels import CRITICAL, DEBUG, ERROR, INFO, WARN, parse_level
from .record import Record
from .sink import Sink


LevelArg = Union[int, str]


class Logger:
    def __init__(
        self,
        name: str = "root",
        level: int = INFO,
        role: str = "",
        sinks: Optional[List[Sink]] = None,
    ):
        self.name = name           # internal: registry key + root sentinel
        self.level = level
        self.role = role           # bound role, surfaces in every Record
        self.sinks: List[Sink] = list(sinks) if sinks is not None else []
        self._lock = threading.Lock()

    # ---- configuration ---------------------------------------------------

    def add_sink(self, sink: Sink) -> "Logger":
        with self._lock:
            self.sinks.append(sink)
        return self

    def remove_sink(self, sink: Sink) -> "Logger":
        with self._lock:
            self.sinks = [s for s in self.sinks if s is not sink]
        return self

    def set_level(self, level: LevelArg) -> "Logger":
        self.level = parse_level(level)
        return self

    def set_role(self, role: str) -> "Logger":
        """Bind a role string to every subsequent Record from this Logger.

        Use this when one subsystem shifts between roles mid-run, or to
        override a constructor-bound role.
        """
        self.role = role
        return self

    # ---- dispatch ---------------------------------------------------------

    def log(
        self,
        level: LevelArg,
        message: str,
        *fields_pairs: Any,
        **fields: Any,
    ) -> "Logger":
        """Emit a record at ``level`` (int or name).

        Positional ``fields_pairs`` must come in (key, value) pairs and
        are merged into ``fields``. Lets callers build field dicts
        inline without an intermediate variable.

        The caller function name and line number are captured
        automatically via ``sys._getframe(1)`` so the Record is
        self-locating. Capture happens after the filter check to avoid
        paying the cost for dropped records.
        """
        if len(fields_pairs) % 2 != 0:
            raise ValueError("positional fields must be key/value pairs")
        # Positional pairs first (preserves call order), then kwargs.
        merged: dict[str, Any] = {}
        for i in range(0, len(fields_pairs), 2):
            merged[fields_pairs[i]] = fields_pairs[i + 1]
        merged.update(fields)

        lvl = parse_level(level)
        if lvl < self.level:
            return self

        # Capture the real caller's frame. Frame 1 is whoever called
        # log() — usually a convenience method (info/warn/...), whose
        # name would be uninteresting. Skip past those so the recorded
        # func is the user's actual function.
        frame = sys._getframe(1)
        convenience = {"debug", "info", "warn", "error", "critical"}
        while frame is not None and frame.f_code.co_name in convenience:
            frame = frame.f_back
        if frame is None:
            func = "<unknown>"
            lineno = 0
        else:
            func = frame.f_code.co_name
            lineno = frame.f_lineno

        record = Record(
            ts=datetime.now().astimezone(),
            level=lvl,
            func=func,
            lineno=lineno,
            role=self.role,
            message=message,
            fields=merged,
        )

        # Snapshot the sink list under the lock; emit outside it so a
        # misbehaving sink cannot block sibling sinks.
        # Walk the chain to root so configuration on root reaches all loggers.
        node: Optional["Logger"] = self
        visited: set[int] = set()
        while node is not None and id(node) not in visited:
            visited.add(id(node))
            with node._lock:
                sinks = list(node.sinks)
            for sink in sinks:
                if not sink.accepts(lvl):
                    continue
                try:
                    sink._emit(sink.formatter(record))
                except Exception as e:  # noqa: BLE001
                    print(f"[zlog] sink {sink!r} failed: {e}", file=sys.stderr)
            if node.name == "root":
                break
            node = _loggers.get("root")
        return self

    # ---- convenience methods (return self for chaining) ------------------

    def debug(self, message: str, *pairs: Any, **f: Any) -> "Logger":
        return self.log(DEBUG, message, *pairs, **f)

    def info(self, message: str, *pairs: Any, **f: Any) -> "Logger":
        return self.log(INFO, message, *pairs, **f)

    def warn(self, message: str, *pairs: Any, **f: Any) -> "Logger":
        return self.log(WARN, message, *pairs, **f)

    def error(self, message: str, *pairs: Any, **f: Any) -> "Logger":
        return self.log(ERROR, message, *pairs, **f)

    def critical(self, message: str, *pairs: Any, **f: Any) -> "Logger":
        return self.log(CRITICAL, message, *pairs, **f)


# ---- global registry ---------------------------------------------------

_loggers: dict[str, Logger] = {}
_registry_lock = threading.Lock()

# Default config directory: scripts/zlog/config/
# A single global file — output_config.json — declares every named
# logger the process may need.
_DEFAULT_CONFIG_DIR = None      # resolved lazily on first init
_DEFAULT_CONFIG_FILENAME = "output_config.json"
_initialized = False            # process-wide flag; flips true after first init


def _resolve_default_config_dir() -> str:
    """Return the package's default config directory.

    Layout: ``<zlog package>/config/``. Resolved once and cached on the
    module so multiple ``get_logger`` calls don't re-stat the path.
    """
    global _DEFAULT_CONFIG_DIR
    if _DEFAULT_CONFIG_DIR is None:
        from pathlib import Path

        _DEFAULT_CONFIG_DIR = str(Path(__file__).resolve().parent / "config")
    return _DEFAULT_CONFIG_DIR


def _resolve_default_config_path() -> str:
    """Absolute path to the single global config file."""
    return os.path.join(_resolve_default_config_dir(), _DEFAULT_CONFIG_FILENAME)


def init_logging(config_path: Optional[str] = None) -> None:
    """Initialize the registry from the global config before any ``get_logger``.

    ``config_path`` defaults to ``scripts/zlog/config/output_config.json``.
    Pass an explicit path to point at a test fixture or alternate
    deployment config.

    After this call, :func:`get_logger` for any name declared in the
    JSON returns the registered logger; names not in the JSON still
    raise ``KeyError``.
    """
    global _initialized
    if config_path is None:
        config_path = _resolve_default_config_path()

    from .config import load_config

    load_config(config_path)
    # Only flip the flag on success — a failed load leaves the registry
    # untouched (load_config_dict is atomic) so we want lazy init to be
    # retried on a later get_logger.
    with _registry_lock:
        _initialized = True


def _lazy_init() -> None:
    """Lazy fallback: load the global config from the default path.

    Called from :func:`get_logger` when the registry is empty. If the
    file does not exist, the original ``KeyError`` is re-raised so the
    caller sees the same diagnostic regardless of whether init was
    eager or lazy.
    """
    global _initialized
    cfg_path = _resolve_default_config_path()
    if not os.path.exists(cfg_path):
        raise KeyError(
            f"no zlog config found at {cfg_path!r}; create scripts/zlog/"
            "config/output_config.json or call zlog.init_logging(path) "
            "explicitly"
        )
    from .config import load_config

    load_config(cfg_path)
    # Only flip the flag on success; failed loads leave the flag clear
    # so get_logger can be retried after the user fixes the JSON.
    with _registry_lock:
        _initialized = True


def get_logger(name: str) -> Logger:
    """Return the configured logger named ``name``.

    On the first call for an unregistered name, lazy-loads the global
    ``output_config.json`` and registers every logger declared inside.
    If the config file is missing or the name is not declared,
    ``KeyError`` is raised with a hint about the missing config.

    Safe to call from multiple threads concurrently: the registry lock
    makes the read atomic with any concurrent ``_register``.
    """
    with _registry_lock:
        if name in _loggers:
            return _loggers[name]

    # Drop the lock while loading the JSON file so we don't hold the
    # registry mutex across a (potentially slow) disk read. Re-check
    # under the lock after the load to avoid double-init when two
    # threads race on the first call.
    _lazy_init()

    with _registry_lock:
        if name not in _loggers:
            raise KeyError(
                f"logger {name!r} not declared in output_config.json; "
                "add it under the 'loggers' key and reload"
            )
        return _loggers[name]


def _register(name: str, logger: Logger) -> None:
    """Internal hook for ``load_config`` and tests.

    Production code must not call this directly. It exists so that
    ``load_config_dict`` can atomically install loggers and tests can
    pre-register loggers without going through the JSON loader.
    """
    with _registry_lock:
        # If an old logger is being replaced, close its sinks to release
        # any file handles before they get orphaned.
        existing = _loggers.get(name)
        if existing is not None and existing is not logger:
            for sink in existing.sinks:
                try:
                    sink.close()
                except Exception:  # noqa: BLE001
                    pass
        _loggers[name] = logger


def registered_names() -> list[str]:
    """Return a snapshot of currently registered logger names.

    Useful for diagnostics; not for hot-path lookups.
    """
    with _registry_lock:
        return list(_loggers.keys())


def reset_registry() -> None:
    """Drop all registered loggers and clear the init flag.

    Test-only escape hatch — production code never calls this. After
    calling it, the next ``get_logger`` will trigger lazy init again.
    """
    global _initialized
    with _registry_lock:
        for lg in list(_loggers.values()):
            for sink in lg.sinks:
                try:
                    sink.close()
                except Exception:  # noqa: BLE001
                    pass
        _loggers.clear()
        _initialized = False