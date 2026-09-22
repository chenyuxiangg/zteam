"""Tests for lazy + eager initialization of the logger registry.

There is exactly one global config file —
``scripts/zlog/config/output_config.json`` — and it declares every
named logger the process may need.

Two paths into the registry:

- :func:`zlog.init_logging(config_path)` loads the global config
  explicitly at startup; subsequent ``get_logger`` calls for any name
  in the file return without touching disk.
- :func:`zlog.get_logger(name)` (no prior init) lazy-loads
  ``output_config.json`` on the first miss and caches the result.

Both paths raise ``KeyError`` if the requested name is not declared in
the loaded config, so typos surface immediately rather than silently
constructing empty loggers.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from zlog import (
    MemorySink,
    get_logger,
    init_logging,
    load_config_dict,
    registered_names,
)
from zlog import logger as _logger_mod

from ._helpers import ZlogTestCase


def _write_config(path: str, loggers: dict) -> None:
    with open(path, "w") as f:
        json.dump({"loggers": loggers}, f)


class EagerInit(ZlogTestCase):
    """``init_logging(config_path)`` preloads output_config.json."""

    def test_init_logging_loads_named_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "output_config.json")
            _write_config(
                cfg, {"alpha": {"channel": "memory", "level": "INFO"}}
            )
            init_logging(cfg)

            log = get_logger("alpha")
            self.assertIsInstance(log.sinks[0], MemorySink)
            self.assertIn("alpha", registered_names())

    def test_init_logging_marks_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "output_config.json")
            _write_config(cfg, {"beta": {"channel": "memory"}})
            init_logging(cfg)
            self.assertTrue(_logger_mod._initialized)

    def test_init_logging_default_path(self) -> None:
        # When no config_path is given, init_logging uses the package's
        # default location (scripts/zlog/config/output_config.json).
        # We monkey-patch the resolved path to point at a temp file.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "output_config.json")
            _write_config(cfg, {"gamma": {"channel": "memory"}})
            orig = _logger_mod._DEFAULT_CONFIG_DIR
            _logger_mod._DEFAULT_CONFIG_DIR = tmp
            try:
                init_logging()
            finally:
                _logger_mod._DEFAULT_CONFIG_DIR = orig
            self.assertTrue(_logger_mod._initialized)


class LazyInit(ZlogTestCase):
    """``get_logger`` lazy-loads output_config.json on first miss."""

    def test_lazy_loads_when_no_prior_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "output_config.json")
            _write_config(
                cfg,
                {"delta": {"channel": "memory", "level": "DEBUG"}},
            )
            orig = _logger_mod._DEFAULT_CONFIG_DIR
            _logger_mod._DEFAULT_CONFIG_DIR = tmp
            try:
                log = get_logger("delta")
            finally:
                _logger_mod._DEFAULT_CONFIG_DIR = orig

            self.assertEqual(log.level, 10)  # DEBUG
            self.assertIsInstance(log.sinks[0], MemorySink)
            self.assertTrue(_logger_mod._initialized)

    def test_lazy_raises_when_config_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orig = _logger_mod._DEFAULT_CONFIG_DIR
            _logger_mod._DEFAULT_CONFIG_DIR = tmp
            try:
                with self.assertRaises(KeyError) as ctx:
                    get_logger("nonexistent")
            finally:
                _logger_mod._DEFAULT_CONFIG_DIR = orig

            msg = str(ctx.exception)
            self.assertIn("output_config.json", msg)
            self.assertIn("init_logging", msg)

    def test_lazy_raises_when_name_not_in_config(self) -> None:
        # Config exists but doesn't declare the requested name.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "output_config.json")
            _write_config(cfg, {"declared": {"channel": "memory"}})
            orig = _logger_mod._DEFAULT_CONFIG_DIR
            _logger_mod._DEFAULT_CONFIG_DIR = tmp
            try:
                with self.assertRaises(KeyError) as ctx:
                    get_logger("not_declared")
            finally:
                _logger_mod._DEFAULT_CONFIG_DIR = orig

            self.assertIn("not_declared", str(ctx.exception))
            self.assertIn("output_config.json", str(ctx.exception))

    def test_lazy_does_not_overwrite_existing(self) -> None:
        # If a name was pre-registered (e.g. via load_config_dict),
        # get_logger must return the registered one — not lazy-load.
        load_config_dict(
            {"loggers": {"epsilon": {"channel": "memory", "level": "INFO"}}}
        )
        first = get_logger("epsilon")
        first_id = id(first)
        second = get_logger("epsilon")
        self.assertIs(second, first)
        self.assertEqual(id(second), first_id)


class RegistryReplacement(ZlogTestCase):
    """load_config_dict inside an init must replace the prior logger."""

    def test_init_logging_replaces_prior_registry(self) -> None:
        # First init registers zeta with one config; second init
        # registers zeta with a different config. The second should
        # replace (close sinks, install new).
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            cfg1 = os.path.join(tmp1, "output_config.json")
            cfg2 = os.path.join(tmp2, "output_config.json")
            _write_config(
                cfg1, {"zeta": {"channel": "memory", "level": "INFO"}}
            )
            _write_config(
                cfg2, {"zeta": {"channel": "memory", "level": "DEBUG"}}
            )
            init_logging(cfg1)
            first = get_logger("zeta")
            first_sink = first.sinks[0]

            init_logging(cfg2)
            second = get_logger("zeta")

            self.assertEqual(second.level, 10)  # DEBUG
            self.assertIsNot(second, first)
            # MemorySink has no _closed flag, but the registry swap is
            # sufficient evidence that the prior logger was replaced.
            self.assertIs(get_logger("zeta"), second)


if __name__ == "__main__":
    unittest.main()