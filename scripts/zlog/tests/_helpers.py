"""Shared test helpers.

Test isolation is the hard part of a module with global state. The
``_loggers`` registry in ``zlog.logger`` persists across tests, so every
test must start from a clean slate.

Under the strict API, ``get_logger(name)`` raises for unregistered
names. Tests bypass strict mode by registering their own loggers via
the ``register_test_logger`` helper, which uses ``load_config_dict``
internally so the registry behaves the same as production code.
"""
from __future__ import annotations

import os
import sys
import unittest

# Ensure the zlog package is importable when running tests directly via
# ``python3 -m unittest`` from the project root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(os.path.dirname(_HERE))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


class ZlogTestCase(unittest.TestCase):
    """Base class that resets zlog's global state around every test."""

    def setUp(self) -> None:
        from zlog import logger as _logger_mod  # noqa: WPS433

        self._logger_mod = _logger_mod
        self._saved_loggers = dict(_logger_mod._loggers)
        self._saved_initialized = _logger_mod._initialized
        _logger_mod._loggers.clear()
        _logger_mod._initialized = False

    def tearDown(self) -> None:
        from zlog import logger as _logger_mod  # noqa: WPS433

        for lg in _logger_mod._loggers.values():
            for sink in lg.sinks:
                sink.close()
        _logger_mod._loggers.clear()
        _logger_mod._loggers.update(self._saved_loggers)
        _logger_mod._initialized = self._saved_initialized


def register_test_logger(name: str, level: str = "DEBUG", channel: str = "memory"):
    """Register a logger for tests via the production config loader.

    Each logger gets a single channel (default: memory). Production
    code uses :func:`zlog.load_config`; tests use this helper to avoid
    hand-rolling ``load_config_dict`` for every name they need.
    """
    from zlog import load_config_dict

    load_config_dict(
        {"loggers": {name: {"channel": channel, "level": level}}}
    )


def register_test_loggers(*names: str, level: str = "DEBUG", channel: str = "memory"):
    """Register several loggers at once. Convenience wrapper."""
    from zlog import load_config_dict

    spec = {n: {"channel": channel, "level": level} for n in names}
    load_config_dict({"loggers": spec})


def test_get_logger(name: str, *, role: str = ""):
    """Test-only ``get_logger`` that auto-registers on first call.

    Production code uses :func:`zlog.get_logger`, which raises
    ``KeyError`` for unregistered names. Tests can import this helper
    under the name ``get_logger`` to keep their fixtures small::

        from ._helpers import test_get_logger as get_logger

    ``role`` is forwarded via ``set_role`` so existing tests using
    ``get_logger("name", role="...")`` continue to work.
    """
    from zlog import get_logger as _prod_get_logger

    try:
        log = _prod_get_logger(name)
    except KeyError:
        register_test_logger(name)
        log = _prod_get_logger(name)
    if role:
        log.set_role(role)
    return log


def make_record(
    level=20,
    func="test_func",
    lineno=1,
    role="",
    message="m",
    fields=None,
):
    """Build a Record without coupling tests to private constructors."""
    from datetime import datetime

    from zlog import Record

    return Record(
        ts=datetime(2026, 1, 1, 12, 0, 0),
        level=level,
        func=func,
        lineno=lineno,
        role=role,
        message=message,
        fields=fields or {},
    )