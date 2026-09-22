"""zlog - minimal structured logging for zteam.

Public API:

Levels
    DEBUG, INFO, WARN, ERROR, CRITICAL
    parse_level(name_or_value) -> int

Data
    Record            (frozen dataclass; ts / level / func / lineno /
                       role / message / fields)

Formatting
    Formatter         (Protocol: callable ``Record -> str``)
    template(fmt)     (formatter factory using ``str.format`` placeholders)
    DEFAULT_FORMAT    (the canonical pipe-delimited template)

Sinks
    Sink              (base class; override ``_emit``)
    StdoutSink, StderrSink, FileSink, MemorySink
    RotatingFileSink  (size-based rotation; ``delete_oldest`` or ``no_rotate``)

Logger
    Logger                          (instance)
    get_logger(name)                (lazy: auto-loads config/<name>.json on first call)
    registered_names()              (diagnostics; snapshot of registry)
    init_logging(name=None, config_dir=None)
                                  (preload config/<name>.json before any get_logger)
    load_config(path)              (initialize loggers from a JSON file path)
    load_config_dict({...})        (initialize loggers from a dict)

Typical usage (lazy init)::

    # Anywhere in the codebase — no explicit setup needed if
    # scripts/zlog/config/<name>.json exists:
    from zlog import get_logger
    log = get_logger("statectl")
    log.info("worker finished", project="zteam", worker="build", duration_s=2.3)

Typical usage (eager init)::

    # At process startup, preload a config explicitly:
    import zlog
    zlog.init_logging("statectl")

Default config directory: ``<zlog package>/config/``. Drop a
``<logger_name>.json`` file there to make ``get_logger("<logger_name>")``
work without any explicit setup.

Default line shape (pipe-delimited for unambiguous parsing)::

    {ts}|{level_name:8}|{func}:{lineno}|{role:10}|{message}|{kv}

Parse with ``line.split("|", 5)`` — yields six fields: ts, level,
func:lineno, role, message, kv (kv is ``k=v k="quoted value"`` joined
by spaces; empty when no user fields were passed).
"""
from __future__ import annotations

from .config import load_config, load_config_dict
from .formatter import Formatter, template
from .levels import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    LEVEL_NAMES,
    WARN,
    parse_level,
)
from .logger import Logger, get_logger, init_logging, registered_names
from .record import Record
from .sink import DEFAULT_FORMAT, FileSink, MemorySink, RotatingFileSink, Sink, StderrSink, StdoutSink

__all__ = [
    # levels
    "DEBUG",
    "INFO",
    "WARN",
    "ERROR",
    "CRITICAL",
    "LEVEL_NAMES",
    "parse_level",
    # data
    "Record",
    # formatting
    "Formatter",
    "template",
    "DEFAULT_FORMAT",
    # sinks
    "Sink",
    "StdoutSink",
    "StderrSink",
    "FileSink",
    "MemorySink",
    "RotatingFileSink",
    # logger
    "Logger",
    "get_logger",
    "registered_names",
    "init_logging",
    "load_config",
    "load_config_dict",
]