"""Tests for RotatingFileSink: size-based rotation."""
from __future__ import annotations

import os
import tempfile
import unittest

from zlog import RotatingFileSink, template

from ._helpers import ZlogTestCase


class RotatingFileSinkTests(ZlogTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "app.log")

    # ---- single rotation ------------------------------------------------

    def test_rotates_when_size_exceeded(self) -> None:
        # max_bytes = 10 → can hold ~3-4 lines of "x" before rotating
        sink = RotatingFileSink(self.path, max_bytes=10, backup_count=3)
        self.addCleanup(sink.close)

        for _ in range(10):
            sink._emit("xxxxxxx")  # 7 bytes + 1 newline = 8 per line

        # Current is small (just last write); backups should exist.
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".1"))

    def test_no_rotation_when_under_limit(self) -> None:
        sink = RotatingFileSink(self.path, max_bytes=1024, backup_count=3)
        self.addCleanup(sink.close)

        sink._emit("small")
        sink._emit("small")

        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".1"))

    # ---- backup_count semantics: N total files -------------------------

    def test_total_file_count_is_backup_count(self) -> None:
        # backup_count=2 means app.log + app.log.1 = 2 files max
        sink = RotatingFileSink(self.path, max_bytes=4, backup_count=2)
        self.addCleanup(sink.close)

        for _ in range(20):
            sink._emit("aaaa")  # 5 bytes incl. newline

        existing = sorted(
            f for f in os.listdir(self._tmp.name)
            if f.startswith("app.log")
        )
        # Must be at most 2 files.
        self.assertEqual(len(existing), 2)
        self.assertIn("app.log", existing)
        self.assertIn("app.log.1", existing)

    def test_oldest_dropped_on_overflow(self) -> None:
        # backup_count=2: app.log + app.log.1. On overflow, app.log.1 dropped.
        sink = RotatingFileSink(self.path, max_bytes=4, backup_count=2)
        self.addCleanup(sink.close)

        # Fill enough to create app.log.1
        for _ in range(5):
            sink._emit("aaaa")
        # Now app.log.1 exists. One more write should drop it.
        sink._emit("bbbb")

        # app.log.1 should still exist (just contains bbbb), no app.log.2.
        self.assertFalse(os.path.exists(self.path + ".2"))

    # ---- no_rotate mode -------------------------------------------------

    def test_no_rotate_grows_unbounded(self) -> None:
        sink = RotatingFileSink(self.path, max_bytes=10, backup_count=3, mode="no_rotate")
        self.addCleanup(sink.close)

        for _ in range(100):
            sink._emit("xxxxxxx")

        # File exists, no rotation happened.
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".1"))
        # File should be quite large.
        self.assertGreater(os.path.getsize(self.path), 100)

    # ---- rotation triggered BEFORE write (single-line never lost) -----

    def test_no_line_is_lost_during_rotation(self) -> None:
        # backup_count=60 keeps all 50 lines across multiple rotations
        # (max_bytes=6 triggers a rotate per line, but never drops any).
        sink = RotatingFileSink(self.path, max_bytes=6, backup_count=60)
        self.addCleanup(sink.close)

        lines = [f"L{i:04d}" for i in range(50)]  # L0000..L0049
        for line in lines:
            sink._emit(line)

        # Collect every line across all files in chronological order.
        # .N is the oldest backup, .1 the newest, current is the freshest.
        backup_count = 60
        all_files = [self.path + f".{i}" for i in range(backup_count - 1, 0, -1)]
        all_files.append(self.path)
        collected = []
        for path in all_files:
            if os.path.exists(path):
                with open(path) as f:
                    collected.extend(line for line in f.read().splitlines() if line)

        self.assertEqual(collected, lines)

    # ---- argument validation ------------------------------------------

    def test_backup_count_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            RotatingFileSink(self.path, backup_count=0)

    def test_unknown_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RotatingFileSink(self.path, mode="circular")

    def test_close_stops_writes(self) -> None:
        sink = RotatingFileSink(self.path, max_bytes=4, backup_count=3)
        sink._emit("hi")
        sink.close()
        sink._emit("after")  # no-op
        self.assertFalse(os.path.exists(self.path + ".1"))