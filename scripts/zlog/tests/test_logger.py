"""Tests for zlog.logger: filtering, dispatch, chaining, hierarchy."""
from __future__ import annotations

import io
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr

from zlog import (
    DEBUG,
    ERROR,
    INFO,
    MemorySink,
    Sink,
)
from zlog.logger import Logger

from ._helpers import ZlogTestCase, test_get_logger as get_logger


def messages(records: list[str]) -> list[str]:
    """Extract just the message portion from formatted lines."""
    return [r.split(" ", 4)[-1] if " " in r else r for r in records]


# ---- Basic dispatch -------------------------------------------------------


class LoggerFiltersBelowLevel(ZlogTestCase):
    def test_debug_filtered_when_logger_info(self) -> None:
        mem = MemorySink(level=DEBUG, formatter=lambda r: r.message)
        log = get_logger("a").add_sink(mem).set_level(INFO)

        log.debug("d")
        log.info("i")
        log.warn("w")
        log.error("e")

        self.assertEqual(mem.records, ["i", "w", "e"])

    def test_sink_threshold_independent(self) -> None:
        mem = MemorySink(level=ERROR, formatter=lambda r: r.message)
        log = get_logger("b").add_sink(mem).set_level(DEBUG)

        log.info("filtered by sink")
        log.error("passed both")

        self.assertEqual(mem.records, ["passed both"])


# ---- Convenience methods --------------------------------------------------


class ConvenienceMethods(ZlogTestCase):
    def test_all_levels_exist(self) -> None:
        log = get_logger("c")
        self.assertEqual(log.debug("x").level, 10) if False else None  # ensure method exists
        for name in ("debug", "info", "warn", "error", "critical"):
            self.assertTrue(hasattr(log, name), f"missing method: {name}")

    def test_short_log_signature(self) -> None:
        # Use template() rather than r.level_name (which is an asdict-only key).
        from zlog import template as tpl

        mem = MemorySink(formatter=tpl("{level_name}|{message}|{k}"))
        log = get_logger("d").add_sink(mem)

        log.info("msg", k=1)
        self.assertEqual(mem.records, ["INFO|msg|1"])


# ---- Positional key/value pairs ------------------------------------------


class PositionalPairs(ZlogTestCase):
    def test_pairs_merge_into_fields(self) -> None:
        mem = MemorySink(formatter=lambda r: f"{r.message}|{dict(r.fields)}")
        log = get_logger("e").add_sink(mem)

        log.info("m", "a", 1, "b", 2, c=3)
        # Positional pairs preserved in call order, kwargs after.
        self.assertEqual(mem.records, ["m|{'a': 1, 'b': 2, 'c': 3}"])

    def test_uneven_pairs_raise(self) -> None:
        log = get_logger("f")
        with self.assertRaises(ValueError):
            log.info("m", "a", 1, "b")  # missing value for "b"


# ---- Chainable API --------------------------------------------------------


class Chainable(ZlogTestCase):
    def test_mutators_return_self(self) -> None:
        log = get_logger("g")
        self.assertIs(log.add_sink(MemorySink()), log)
        self.assertIs(log.set_level(DEBUG), log)
        self.assertIs(log.remove_sink(log.sinks[0]), log)

    def test_log_methods_return_self(self) -> None:
        log = get_logger("h").add_sink(MemorySink())
        self.assertIs(log.info("x"), log)
        self.assertIs(log.error("y"), log)


# ---- Hierarchy to root ----------------------------------------------------


class HierarchyToRoot(ZlogTestCase):
    def test_child_logger_emits_to_root_sinks(self) -> None:
        from zlog.logger import _loggers

        # Set up a root sink via the configure-free path.
        root = get_logger("root")
        mem_root = MemorySink(formatter=lambda r: f"root:{r.message}")
        root.add_sink(mem_root)

        child = get_logger("child")
        mem_child = MemorySink(formatter=lambda r: f"child:{r.message}")
        child.add_sink(mem_child)

        child.info("hello")

        self.assertEqual(mem_root.records, ["root:hello"])
        self.assertEqual(mem_child.records, ["child:hello"])

    def test_logger_walk_does_not_loop(self) -> None:
        # Defensive: if root ever points at a non-root node, walk must stop.
        from zlog.logger import _loggers

        root = get_logger("root")
        fake = Logger("fake", level=INFO)
        root.parent = fake  # type: ignore[attr-defined]
        fake.sinks = []  # no recursion test needed; just confirm no infinite loop

        mem = MemorySink(formatter=lambda r: r.message)
        root.add_sink(mem)
        root.info("x")

        self.assertEqual(mem.records, ["x"])
        # Clean up the bogus parent attribute so other tests aren't affected.
        del root.parent  # type: ignore[attr-defined]


# ---- Fault isolation ------------------------------------------------------


class FaultIsolation(ZlogTestCase):
    def test_failing_sink_does_not_block_others(self) -> None:
        class BombSink(Sink):
            def _emit(self, line: str) -> None:
                raise RuntimeError("boom")

        captured: list[str] = []

        class CatchSink(Sink):
            def _emit(self, line: str) -> None:
                captured.append(line)

        log = get_logger("fault").add_sink(BombSink()).add_sink(CatchSink())

        err = io.StringIO()
        with redirect_stderr(err):
            log.info("payload")

        self.assertEqual(len(captured), 1)
        self.assertIn("payload", captured[0])
        # The error went to stderr, not stdout.
        self.assertIn("boom", err.getvalue())


# ---- get_logger registry --------------------------------------------------


class Registry(ZlogTestCase):
    def test_same_name_returns_same_instance(self) -> None:
        self.assertIs(get_logger("reuse"), get_logger("reuse"))

    def test_different_names_different_instances(self) -> None:
        self.assertIsNot(get_logger("one"), get_logger("two"))


# ---- Direct Logger construction -------------------------------------------


class DirectConstruction(unittest.TestCase):
    def test_logger_without_registry(self) -> None:
        log = Logger("solo", level=DEBUG)
        mem = MemorySink(level=DEBUG, formatter=lambda r: r.message)
        log.add_sink(mem)
        log.info("hi")
        self.assertEqual(mem.records, ["hi"])
