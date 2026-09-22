"""Tests for JSON-driven logger configuration: load_config / load_config_dict."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from zlog import (
    FileSink,
    MemorySink,
    RotatingFileSink,
    StderrSink,
    StdoutSink,
    get_logger,
    load_config,
    load_config_dict,
    registered_names,
)
from zlog.sink import DEFAULT_FORMAT, template
from zlog.logger import _loggers

from ._helpers import ZlogTestCase


class StrictMode(ZlogTestCase):
    """get_logger must raise for unregistered names with a helpful hint."""

    def test_unknown_name_raises_keyerror(self) -> None:
        # Patch the default config dir away from the package so we don't
        # accidentally load the real output_config.json sitting in
        # scripts/zlog/config/.
        import zlog.logger as _logger_mod

        with tempfile.TemporaryDirectory() as tmp:
            orig = _logger_mod._DEFAULT_CONFIG_DIR
            _logger_mod._DEFAULT_CONFIG_DIR = tmp
            try:
                with self.assertRaises(KeyError) as ctx:
                    get_logger("never-registered")
            finally:
                _logger_mod._DEFAULT_CONFIG_DIR = orig

        msg = str(ctx.exception)
        # Hint points at the global config file and init_logging.
        self.assertIn("output_config.json", msg)
        self.assertIn("init_logging", msg)

    def test_unknown_name_when_config_lacks_it(self) -> None:
        # Config exists but does not declare the requested name.
        import zlog.logger as _logger_mod

        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "output_config.json")
            with open(cfg, "w") as f:
                json.dump({"loggers": {}}, f)
            orig = _logger_mod._DEFAULT_CONFIG_DIR
            _logger_mod._DEFAULT_CONFIG_DIR = tmp
            try:
                with self.assertRaises(KeyError) as ctx:
                    get_logger("never-declared")
            finally:
                _logger_mod._DEFAULT_CONFIG_DIR = orig

        msg = str(ctx.exception)
        self.assertIn("never-declared", msg)
        self.assertIn("output_config.json", msg)

    def test_after_load_returns_registered(self) -> None:
        load_config_dict({"loggers": {"x": {"channel": "memory", "level": "INFO"}}})
        log = get_logger("x")
        self.assertEqual(log.name, "x")


class LoadConfigDictBasic(ZlogTestCase):
    def test_memory_channel(self) -> None:
        load_config_dict({"loggers": {"foo": {"channel": "memory", "level": "DEBUG"}}})
        log = get_logger("foo")
        self.assertEqual(len(log.sinks), 1)
        self.assertIsInstance(log.sinks[0], MemorySink)
        self.assertEqual(log.level, 10)  # DEBUG

    def test_stdout_channel(self) -> None:
        load_config_dict({"loggers": {"foo": {"channel": "stdout"}}})
        log = get_logger("foo")
        self.assertIsInstance(log.sinks[0], StdoutSink)

    def test_stderr_channel(self) -> None:
        load_config_dict({"loggers": {"foo": {"channel": "stderr"}}})
        log = get_logger("foo")
        self.assertIsInstance(log.sinks[0], StderrSink)

    def test_file_channel_no_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "app.log")
            load_config_dict(
                {"loggers": {"foo": {"channel": path, "rotation": "no_rotate"}}}
            )
            log = get_logger("foo")
            self.assertIsInstance(log.sinks[0], FileSink)
            self.assertFalse(isinstance(log.sinks[0], RotatingFileSink))

    def test_file_channel_with_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "app.log")
            load_config_dict(
                {
                    "loggers": {
                        "foo": {
                            "channel": path,
                            "single_file_size": 1024,
                            "file_count": 3,
                            "rotation": "delete_oldest",
                        }
                    }
                }
            )
            log = get_logger("foo")
            self.assertIsInstance(log.sinks[0], RotatingFileSink)
            self.assertEqual(log.sinks[0].backup_count, 3)
            self.assertEqual(log.sinks[0].max_bytes, 1024)


class ChannelAsArray(ZlogTestCase):
    """Channels can be a list to attach multiple sinks to one logger."""

    def test_array_channel_attaches_multiple_sinks(self) -> None:
        load_config_dict(
            {
                "loggers": {
                    "dual": {
                        "channel": ["stdout", "stderr"],
                        "level": "INFO",
                    }
                }
            }
        )
        log = get_logger("dual")
        self.assertEqual(len(log.sinks), 2)
        # StdoutSink first, StderrSink second.
        self.assertIsInstance(log.sinks[0], StdoutSink)
        self.assertIsInstance(log.sinks[1], StderrSink)

    def test_array_with_files_and_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.log")
            load_config_dict(
                {
                    "loggers": {
                        "audit": {
                            "channel": [path, "stderr"],
                            "level": "WARN",
                        }
                    }
                }
            )
            log = get_logger("audit")
            self.assertEqual(len(log.sinks), 2)
            self.assertIsInstance(log.sinks[0], FileSink)
            self.assertIsInstance(log.sinks[1], StderrSink)


class LoadConfigReplace(ZlogTestCase):
    def test_reload_replaces_logger(self) -> None:
        load_config_dict({"loggers": {"x": {"channel": "memory", "level": "INFO"}}})
        first = get_logger("x")
        first_id = id(first)

        # Reload with different spec; should replace.
        load_config_dict({"loggers": {"x": {"channel": "memory", "level": "DEBUG"}}})
        second = get_logger("x")
        self.assertEqual(second.level, 10)
        # Old sink should be closed (MemorySink has no handle, but close is idempotent).

    def test_reload_closes_previous_sinks(self) -> None:
        """A reload must close the old logger's sinks to release file handles."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.log")
            load_config_dict({"loggers": {"x": {"channel": path, "rotation": "no_rotate"}}})
            first = get_logger("x")
            first_sink = first.sinks[0]
            self.assertFalse(first_sink._closed)

            load_config_dict({"loggers": {"x": {"channel": "memory"}}})
            self.assertTrue(first_sink._closed)


class LoadConfigErrors(ZlogTestCase):
    def test_missing_channel_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_config_dict({"loggers": {"x": {"level": "INFO"}}})

    def test_empty_channel_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_config_dict({"loggers": {"x": {"channel": []}}})

    def test_delete_oldest_requires_single_file_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.log")
            with self.assertRaises(ValueError):
                load_config_dict(
                    {
                        "loggers": {
                            "x": {
                                "channel": path,
                                "file_count": 3,
                                "rotation": "delete_oldest",
                            }
                        }
                    }
                )

    def test_unknown_rotation_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_config_dict(
                {
                    "loggers": {
                        "x": {
                            "channel": "/tmp/x.log",
                            "rotation": "compress",
                        }
                    }
                }
            )

    def test_invalid_file_count_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_config_dict(
                {
                    "loggers": {
                        "x": {
                            "channel": "/tmp/x.log",
                            "single_file_size": 1024,
                            "file_count": 0,
                            "rotation": "delete_oldest",
                        }
                    }
                }
            )

    def test_failure_leaves_registry_intact(self) -> None:
        """A bad spec must not partially overwrite the registry."""
        load_config_dict({"loggers": {"good": {"channel": "memory"}}})
        try:
            load_config_dict(
                {"loggers": {"bad": {"channel": "/tmp/x.log", "rotation": "lol"}}}
            )
        except ValueError:
            pass
        # 'good' still registered.
        self.assertIn("good", _loggers)


class LoadConfigFromFile(ZlogTestCase):
    def test_loads_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "zlog.json")
            with open(path, "w") as f:
                json.dump(
                    {
                        "loggers": {
                            "alpha": {"channel": "memory", "level": "DEBUG"},
                            "beta": {"channel": "stdout", "level": "WARN"},
                        }
                    },
                    f,
                )
            load_config(path)
            self.assertIn("alpha", registered_names())
            self.assertIn("beta", registered_names())
            self.assertEqual(get_logger("alpha").level, 10)
            self.assertEqual(get_logger("beta").level, 30)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_config("/nonexistent/path/zlog.json")


class BaseDir(ZlogTestCase):
    """Relative file paths are anchored under top-level ``base_dir``."""

    def test_relative_path_joined_under_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.realpath(tmp)
            load_config_dict(
                {
                    "base_dir": base,
                    "loggers": {
                        "rel": {
                            "channel": "logs/rel.log",
                            "rotation": "no_rotate",
                            "level": "INFO",
                        }
                    },
                }
            )
            sink = get_logger("rel").sinks[0]
            self.assertEqual(sink.path, os.path.join(base, "logs", "rel.log"))
            self.assertTrue(os.path.exists(sink.path))

    def test_absolute_path_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            abs_path = os.path.join(tmp, "abs.log")
            load_config_dict(
                {
                    "base_dir": "/var/log/whatever",
                    "loggers": {
                        "abs": {
                            "channel": abs_path,
                            "rotation": "no_rotate",
                            "level": "INFO",
                        }
                    },
                }
            )
            sink = get_logger("abs").sinks[0]
            self.assertEqual(sink.path, abs_path)

    def test_relative_path_without_base_dir_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            load_config_dict(
                {
                    "loggers": {
                        "x": {
                            "channel": "logs/x.log",
                            "rotation": "no_rotate",
                        }
                    }
                }
            )
        self.assertIn("base_dir", str(ctx.exception))

    def test_base_dir_must_be_absolute(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            load_config_dict(
                {
                    "base_dir": "relative/dir",
                    "loggers": {"x": {"channel": "memory"}},
                }
            )
        self.assertIn("absolute", str(ctx.exception).lower())

    def test_base_dir_must_be_non_empty_string(self) -> None:
        for bad in ("", 42):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    load_config_dict(
                        {
                            "base_dir": bad,
                            "loggers": {"x": {"channel": "memory"}},
                        }
                    )

    def test_base_dir_explicit_none_raises(self) -> None:
        # Distinguish "omitted" (allowed) from "explicitly null" (rejected).
        with self.assertRaises(ValueError):
            load_config_dict(
                {
                    "base_dir": None,
                    "loggers": {"x": {"channel": "memory"}},
                }
            )

    def test_base_dir_works_with_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.realpath(tmp)
            load_config_dict(
                {
                    "base_dir": base,
                    "loggers": {
                        "rot": {
                            "channel": "rot.log",
                            "single_file_size": 1024,
                            "file_count": 2,
                            "rotation": "delete_oldest",
                            "level": "INFO",
                        }
                    },
                }
            )
            sink = get_logger("rot").sinks[0]
            self.assertEqual(sink.path, os.path.join(base, "rot.log"))
            self.assertEqual(sink.backup_count, 2)

    def test_stdio_channels_unaffected_by_base_dir(self) -> None:
        # stdout/stderr/memory are not file paths, so base_dir is ignored.
        load_config_dict(
            {
                "base_dir": "/nonexistent/anchor",
                "loggers": {
                    "out": {"channel": "stdout"},
                    "err": {"channel": "stderr"},
                    "mem": {"channel": "memory"},
                },
            }
        )
        # All three register without trying to create the anchor.
        self.assertIn("out", registered_names())
        self.assertIn("err", registered_names())
        self.assertIn("mem", registered_names())


class DefaultLevel(ZlogTestCase):
    def test_default_level_applies_when_missing(self) -> None:
        load_config_dict(
            {
                "default_level": "WARN",
                "loggers": {"x": {"channel": "memory"}},
            }
        )
        self.assertEqual(get_logger("x").level, 30)

    def test_per_logger_level_overrides_default(self) -> None:
        load_config_dict(
            {
                "default_level": "WARN",
                "loggers": {"x": {"channel": "memory", "level": "DEBUG"}},
            }
        )
        self.assertEqual(get_logger("x").level, 10)