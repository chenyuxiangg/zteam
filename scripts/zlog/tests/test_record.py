"""Tests for zlog.record: immutability and asdict serialization."""
from __future__ import annotations

import unittest

from zlog import ERROR, INFO, Record

from ._helpers import make_record


class RecordAsDict(unittest.TestCase):
    def test_contains_all_keys(self) -> None:
        r = make_record(level=INFO, func="statectl", message="hello", fields={"k": "v"})
        d = r.asdict()
        for key in ("ts", "level", "level_name", "func", "lineno", "role", "message"):
            self.assertIn(key, d)
        # User fields merged in.
        self.assertEqual(d["k"], "v")

    def test_level_and_level_name(self) -> None:
        r = make_record(level=ERROR)
        d = r.asdict()
        self.assertEqual(d["level"], 40)
        self.assertEqual(d["level_name"], "ERROR")

    def test_ts_is_iso_string(self) -> None:
        r = make_record()
        d = r.asdict()
        # Should round-trip through fromisoformat.
        from datetime import datetime

        parsed = datetime.fromisoformat(d["ts"])
        self.assertEqual(parsed, r.ts)

    def test_user_fields_can_override_defaults(self) -> None:
        # Documented behavior: fields.update happens after defaults,
        # so a user field named "level" would replace the int.
        r = make_record(fields={"level": "CUSTOM"})
        d = r.asdict()
        self.assertEqual(d["level"], "CUSTOM")


class RecordImmutability(unittest.TestCase):
    def test_frozen_rejects_assignment(self) -> None:
        r = make_record()
        with self.assertRaises(Exception):  # FrozenInstanceError subclass of AttributeError
            r.message = "tampered"  # type: ignore[misc]

    def test_slots_reject_new_attribute(self) -> None:
        r = make_record()
        # Accept either FrozenInstanceError (3.11+), AttributeError, or
        # the TypeError that Python 3.10's dataclass+slots combo emits
        # because of a super() quirk in the auto-generated __setattr__.
        with self.assertRaises((AttributeError, TypeError)):
            r.injected = "nope"  # type: ignore[attr-defined]


class RecordDirect(unittest.TestCase):
    def test_construction_without_helper(self) -> None:
        from datetime import datetime

        r = Record(
            ts=datetime(2026, 9, 19, 16, 0, 0),
            level=INFO,
            func="x",
            lineno=42,
            message="y",
            fields={},
            role="",
        )
        self.assertEqual(r.func, "x")
        self.assertEqual(r.lineno, 42)
        self.assertEqual(r.message, "y")
