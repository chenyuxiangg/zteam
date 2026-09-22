"""JSON-driven logger configuration.

This module is the only sanctioned way to construct loggers at runtime
in production. Each entry in the JSON declares one named logger and its
sinks. ``load_config`` / ``load_config_dict`` install the loggers
atomically into the registry so :func:`zlog.get_logger` can find them.

Schema
------
::

    {
        "default_level": "INFO",          # optional fallback for missing "level"
        "base_dir": "/var/log/zteam",     # optional anchor for relative file paths
        "loggers": {
            "statectl": {
                "channel": [                # one or more sinks
                    "logs/statectl.log",    # relative → resolved under base_dir
                    "stderr"                # any of: stdout | stderr | memory | <file path>
                ],
                "level": "DEBUG",
                "single_file_size": 10485760,   # bytes, file channels only
                "file_count": 5,                # total files incl. current
                "rotation": "delete_oldest"     # delete_oldest | no_rotate
            },
            "zbot": {
                "channel": ["stderr"],
                "level": "INFO"
            }
        }
    }

File path resolution
--------------------
A file channel whose path is **absolute** is used as-is. A **relative**
path is anchored under the top-level ``base_dir`` (must be an absolute
path itself; relative ``base_dir`` is rejected). If ``base_dir`` is not
set, every file path must be absolute — relative paths raise
``ValueError`` so misconfigurations don't silently resolve against
``os.getcwd()``.

Channels may be a single string or a list. Each file channel respects
``single_file_size`` / ``file_count`` / ``rotation``; stdio channels
ignore those fields. ``channel="memory"`` attaches a MemorySink (handy
for tests/diagnostics).
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping, Optional

from .formatter import template
from .levels import parse_level
from .logger import Logger, _register
from .sink import (
    FileSink,
    MemorySink,
    RotatingFileSink,
    Sink,
    StderrSink,
    StdoutSink,
)


def load_config(path: str) -> None:
    """Load logger definitions from a JSON file at ``path``.

    Atomic: if the file is malformed or any spec is invalid, the
    registry is left untouched. Existing loggers with the same names are
    replaced (their sinks are closed before being discarded).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"zlog config not found: {path}")
    with open(path, encoding="utf-8") as fp:
        cfg = json.load(fp)
    load_config_dict(cfg)


def load_config_dict(cfg: Mapping[str, Any]) -> None:
    """Build loggers from an in-memory config dict.

    Validates the schema, builds new Loggers off to the side, then
    atomically swaps them into the registry via ``_register``.

    The optional top-level ``default_level`` is used as a fallback for
    loggers that omit their own ``level`` field. The optional top-level
    ``base_dir`` (absolute path) anchors any relative file-channel paths.
    """
    default_level = cfg.get("default_level", "INFO")
    if not isinstance(default_level, (str, int)):
        raise ValueError(
            f"'default_level' must be string or int, got {type(default_level).__name__}"
        )

    base_dir = cfg.get("base_dir", "__UNSET__")
    if base_dir != "__UNSET__":
        if not isinstance(base_dir, str) or not base_dir:
            raise ValueError(
                f"'base_dir' must be a non-empty string, got {base_dir!r}"
            )
        if not os.path.isabs(base_dir):
            raise ValueError(
                f"'base_dir' must be an absolute path, got {base_dir!r}"
            )
        base_dir = os.path.normpath(base_dir)
    else:
        base_dir = None

    specs: dict[str, dict[str, Any]] = {}
    for name, raw in cfg.get("loggers", {}).items():
        spec = _normalize_spec(name, raw, base_dir)
        if "level" not in spec:
            spec["level"] = default_level
        specs[name] = spec

    # Build first, register after — so a partial failure doesn't leave
    # the registry in a half-loaded state.
    built: dict[str, Logger] = {}
    for name, spec in specs.items():
        built[name] = _build_logger(name, spec)

    for name, log in built.items():
        _register(name, log)


def _normalize_spec(
    name: str, raw: Any, base_dir: Optional[str]
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"logger {name!r}: spec must be an object, got {type(raw).__name__}")
    spec = dict(raw)

    ch = spec.get("channel")
    if ch is None:
        raise ValueError(f"logger {name!r}: missing 'channel'")
    if isinstance(ch, str):
        spec["channel"] = [ch]
    elif isinstance(ch, list):
        spec["channel"] = list(ch)
    else:
        raise ValueError(
            f"logger {name!r}: 'channel' must be a string or list, got {type(ch).__name__}"
        )
    if not spec["channel"]:
        raise ValueError(f"logger {name!r}: 'channel' list is empty")

    if "level" in spec and not isinstance(spec["level"], (str, int)):
        raise ValueError(
            f"logger {name!r}: 'level' must be string or int, got {type(spec['level']).__name__}"
        )

    rotation = spec.get("rotation", "no_rotate")
    if rotation not in ("delete_oldest", "no_rotate"):
        raise ValueError(
            f"logger {name!r}: 'rotation' must be 'delete_oldest' or 'no_rotate', got {rotation!r}"
        )

    if any(_is_file(c) for c in spec["channel"]):
        if rotation == "delete_oldest":
            if "single_file_size" not in spec:
                raise ValueError(
                    f"logger {name!r}: file channel with rotation='delete_oldest' "
                    "requires 'single_file_size'"
                )
            if "file_count" not in spec:
                raise ValueError(
                    f"logger {name!r}: file channel with rotation='delete_oldest' "
                    "requires 'file_count'"
                )
            size = spec["single_file_size"]
            if not isinstance(size, int) or size <= 0:
                raise ValueError(
                    f"logger {name!r}: 'single_file_size' must be a positive int, got {size!r}"
                )
            count = spec["file_count"]
            if not isinstance(count, int) or count < 1:
                raise ValueError(
                    f"logger {name!r}: 'file_count' must be >= 1, got {count!r}"
                )

    # Resolve file-channel paths against base_dir if set.
    resolved: list[str] = []
    for c in spec["channel"]:
        if not _is_file(c):
            resolved.append(c)
            continue
        if os.path.isabs(c):
            resolved.append(os.path.normpath(c))
        elif base_dir is not None:
            resolved.append(os.path.normpath(os.path.join(base_dir, c)))
        else:
            raise ValueError(
                f"logger {name!r}: channel {c!r} is relative but no "
                "top-level 'base_dir' is set; either use an absolute path "
                "or declare 'base_dir' in the config"
            )
    spec["channel"] = resolved

    return spec


def _is_file(channel: str) -> bool:
    return channel not in ("stdout", "stderr", "memory")


def _build_logger(name: str, spec: Mapping[str, Any]) -> Logger:
    level_arg = spec.get("level", "INFO")
    level_int = parse_level(level_arg) if isinstance(level_arg, str) else level_arg

    log = _build_bare_logger(name, level_int)
    for sink in _build_sinks(name, spec, level_int):
        log.add_sink(sink)
    return log


def _build_bare_logger(name: str, level: int) -> Logger:
    """Construct a Logger that is *not* auto-registered.

    Bypasses :func:`get_logger` because the strict API would raise
    before we have anything to register. The constructed logger is
    installed in the registry later by ``load_config_dict`` via
    ``_register``.
    """
    return Logger(name, level=level)


def _build_sinks(name: str, spec: Mapping[str, Any], level: int) -> list[Sink]:
    rotation = spec.get("rotation", "no_rotate")
    max_bytes = spec.get("single_file_size")
    file_count = spec.get("file_count")
    fmt = spec.get("format")  # optional override

    sinks: list[Sink] = []
    for ch in spec["channel"]:
        if ch == "stdout":
            sinks.append(StdoutSink(level=level, formatter=_maybe_template(fmt)))
        elif ch == "stderr":
            sinks.append(StderrSink(level=level, formatter=_maybe_template(fmt)))
        elif ch == "memory":
            sinks.append(MemorySink(level=level, formatter=_maybe_template(fmt)))
        else:
            # File path (already resolved against base_dir if any)
            if rotation == "delete_oldest":
                sinks.append(
                    RotatingFileSink(
                        path=ch,
                        max_bytes=max_bytes,
                        backup_count=file_count,
                        level=level,
                        formatter=_maybe_template(fmt),
                    )
                )
            else:
                sinks.append(
                    FileSink(path=ch, level=level, formatter=_maybe_template(fmt))
                )
    return sinks


def _maybe_template(fmt: Any):
    """Return ``template(fmt)`` if ``fmt`` is a string, else return as-is."""
    if isinstance(fmt, str):
        return template(fmt)
    return fmt