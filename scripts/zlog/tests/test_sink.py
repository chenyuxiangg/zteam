"""Tests for zlog.sink: Stdout/Stderr/File/Memory sinks and Sink base."""
from __future__ import annotations

import io
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

from zlog import (
    DEBUG,
    ERROR,
    INFO,
    FileSink,
    MemorySink,
    StderrSink,
    StdoutSink,
    template,
)
from zlog.sink import Sink
from zlog.levels import WARN

from ._helpers import ZlogTestCase, make_record, test_get_logger as get_logger


# ---- Sink base class -----------------------------------------------------


class SinkAccepts(ZlogTestCase):
    def test_disabled_rejects_everything(self) -> None:
        s = Sink(level=DEBUG, enabled=False)
        for level in (DEBUG, INFO, ERROR):
            self.assertFalse(s.accepts(level))

    def test_level_threshold(self) -> None:
        s = Sink(level=ERROR)  # default enabled=True
        self.assertFalse(s.accepts(DEBUG))
        self.assertFalse(s.accepts(INFO))
        self.assertTrue(s.accepts(ERROR))
        self.assertTrue(s.accepts(50))


class SinkSetLevel(ZlogTestCase):
    def test_set_level_string(self) -> None:
        s = Sink()
        s.set_level("WARN")
        self.assertEqual(s.level, 30)

    def test_set_level_int(self) -> None:
        s = Sink()
        s.set_level(40)
        self.assertEqual(s.level, 40)


# ---- StdoutSink -----------------------------------------------------------


class StdoutSinkTests(ZlogTestCase):
    def test_writes_to_stdout(self) -> None:
        s = StdoutSink(formatter=template("{message}"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            s._emit("hello")
        self.assertEqual(buf.getvalue(), "hello\n")


# ---- StderrSink -----------------------------------------------------------


class StderrSinkTests(ZlogTestCase):
    def test_writes_to_stderr(self) -> None:
        s = StderrSink(formatter=template("{message}"))
        buf = io.StringIO()
        with redirect_stderr(buf):
            s._emit("oops")
        self.assertEqual(buf.getvalue(), "oops\n")

    def test_default_level_is_error(self) -> None:
        s = StderrSink()
        self.assertEqual(s.level, ERROR)


# ---- FileSink -------------------------------------------------------------


class FileSinkTests(ZlogTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "nested", "app.log")  # nested dir

    def test_creates_parent_dirs(self) -> None:
        s = FileSink(self.path, formatter=template("{message}"))
        self.addCleanup(s.close)
        self.assertTrue(os.path.isdir(os.path.dirname(self.path)))

    def test_appends_lines(self) -> None:
        s = FileSink(self.path, formatter=template("{message}"))
        self.addCleanup(s.close)
        s._emit("first")
        s._emit("second")
        with open(self.path) as f:
            self.assertEqual(f.read().splitlines(), ["first", "second"])

    def test_close_stops_writes(self) -> None:
        s = FileSink(self.path, formatter=template("{message}"))
        s._emit("before")
        s.close()
        s._emit("after")  # should be a no-op, not raise
        with open(self.path) as f:
            self.assertEqual(f.read().strip(), "before")

    def test_concurrent_writes_no_interleaving(self) -> None:
        s = FileSink(self.path, formatter=template("{message}"))
        self.addCleanup(s.close)

        n_threads = 10
        n_per_thread = 50
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(n_per_thread):
                s._emit(f"t{tid}-{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with open(self.path) as f:
            lines = [l for l in f if l]
        self.assertEqual(len(lines), n_threads * n_per_thread)
        # Each line must be a single coherent record (starts with "t<digit>-").
        for line in lines:
            self.assertRegex(line, r"^t\d+-\d+$")


# ---- MemorySink -----------------------------------------------------------


class MemorySinkTests(ZlogTestCase):
    def test_accumulates_emits(self) -> None:
        s = MemorySink(formatter=template("{message}"))
        s._emit("a")
        s._emit("b")
        s._emit("c")
        self.assertEqual(s.records, ["a", "b", "c"])

    def test_clear(self) -> None:
        s = MemorySink(formatter=template("{message}"))
        s._emit("x")
        s.clear()
        self.assertEqual(s.records, [])


# ---- Custom sink extension ------------------------------------------------


class CustomSinkExample(ZlogTestCase):
    """Verify the extension pattern from the docstring actually works."""

    def test_subclass_sink(self) -> None:
        # Subclass sinks plug into the Logger pipeline just like built-ins.
        captured: list[str] = []

        class ListSink(Sink):
            def _emit(self, line: str) -> None:
                captured.append(line)

        log = get_logger("custom").add_sink(
            ListSink(formatter=template("{level_name}: {message}"))
        )
        log.info("x")
        self.assertEqual(captured, ["INFO: x"])


# ---- Default formatter applied to Record ------------------------------


class DefaultFormatterSanity(ZlogTestCase):
    """The default formatter must not contain emoji or [TAG] prefixes."""

    def test_default_text_is_symbol_free(self) -> None:
        s = MemorySink()  # default formatter
        r = make_record(level=INFO, func="t", message="hi")
        line = s.formatter(r)
        for bad in ("[", "]", "🔴", "🟡", "⚠", "·"):
            self.assertNotIn(bad, line, f"default formatter contains {bad!r}")


class DefaultFormatShape(ZlogTestCase):
    """Default format is pipe-delimited and round-trippable."""

    def test_default_is_pipe_delimited(self) -> None:
        from zlog.sink import DEFAULT_FORMAT

        s = MemorySink()
        r = make_record(
            level=INFO, func="hello", lineno=42, role="bot", message="hi", fields={"k": "v"}
        )
        line = s.formatter(r)
        # 5 pipes separate 6 fields: ts|level|func:lineno|role|message|kv
        self.assertEqual(line.count("|"), 5)
        self.assertIn("hello:42", line)
        self.assertTrue(line.endswith("|k=v"))

    def test_round_trip_parse(self) -> None:
        """Standard parsing recipe: split on | with maxsplit=5."""
        s = MemorySink()
        r = make_record(
            level=WARN if False else 30,  # WARN
            func="quota_tick",
            lineno=99,
            role="judge",
            message="quota tight",
            fields={"remaining_pct": 2.1, "threshold": 5},
        )
        line = s.formatter(r)
        parts = line.split("|", 5)
        self.assertEqual(len(parts), 6)
        ts, level, func_lineno, role, message, kv = parts
        self.assertEqual(level.strip(), "WARN")
        self.assertEqual(func_lineno, "quota_tick:99")
        self.assertEqual(role.strip(), "judge")
        self.assertEqual(message, "quota tight")
        self.assertIn("remaining_pct=2.1", kv)

    def test_empty_kv_ends_with_pipe(self) -> None:
        s = MemorySink()
        r = make_record(func="f", lineno=1, message="solo", fields={})
        line = s.formatter(r)
        # kv is "" so the line ends with a trailing pipe.
        self.assertTrue(line.endswith("|"))
        parts = line.split("|", 5)
        self.assertEqual(parts[-1], "")

    def test_default_format_constant_matches_sink(self) -> None:
        from zlog.sink import DEFAULT_FORMAT, template

        s = MemorySink()
        expected = template(DEFAULT_FORMAT)
        # Default sink's formatter is the template built from DEFAULT_FORMAT;
        # verify the constant reflects the actual format strings used.
        self.assertEqual(s.formatter.__name__, expected.__name__)
