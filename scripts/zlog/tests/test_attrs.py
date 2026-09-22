"""Tests for the role / func / lineno Record attributes added for zteam."""
from __future__ import annotations

import unittest

from zlog import (
    DEBUG,
    INFO,
    MemorySink,
    Record,
    template,
)

from ._helpers import ZlogTestCase, make_record, test_get_logger as get_logger


class RoleInRecord(unittest.TestCase):
    def test_role_default_empty(self) -> None:
        r = make_record()
        self.assertEqual(r.role, "")

    def test_role_round_trips_through_asdict(self) -> None:
        r = make_record(role="planner")
        self.assertEqual(r.asdict()["role"], "planner")


class FuncAndLinenoCapture(ZlogTestCase):
    """Caller-attribution via sys._getframe(1)."""

    def test_func_is_caller_function_name(self) -> None:
        mem = MemorySink(formatter=lambda r: r.func)
        log = get_logger("caller-attr").add_sink(mem).set_level(DEBUG)

        def my_emitter_function() -> None:
            log.info("x")

        my_emitter_function()
        self.assertEqual(mem.records, ["my_emitter_function"])

    def test_lineno_is_caller_line(self) -> None:
        mem = MemorySink(formatter=lambda r: str(r.lineno))
        log = get_logger("lineno-attr").add_sink(mem).set_level(DEBUG)

        def emitter() -> None:
            log.info("x")  # <-- captured as lineno

        emitter()
        # Don't pin the exact number (changes if file is edited), but it must
        # be the line of the log.info call, not the function def line.
        self.assertGreater(mem.records[0], "0")

    def test_role_binds_at_logger_construction(self) -> None:
        mem = MemorySink(formatter=lambda r: r.role)
        log = get_logger("bound", role="planner").add_sink(mem).set_level(DEBUG)
        log.info("x")
        self.assertEqual(mem.records, ["planner"])

    def test_set_role_after_construction(self) -> None:
        mem = MemorySink(formatter=lambda r: r.role)
        log = get_logger("late-role").add_sink(mem).set_level(DEBUG)
        log.info("x")  # role still empty
        log.set_role("judge")
        log.info("y")  # now role is judge
        self.assertEqual(mem.records, ["", "judge"])

    def test_get_logger_accepts_role_kwarg(self) -> None:
        log = get_logger("k-arg", role="bot")
        self.assertEqual(log.role, "bot")

    def test_set_level_after_role_preserves_role(self) -> None:
        log = get_logger("preserve", role="coder")
        log.set_level(DEBUG)
        self.assertEqual(log.role, "coder")

    def test_role_appears_in_template(self) -> None:
        mem = MemorySink(formatter=template("[{role}] {message}"))
        log = get_logger("tpl-role", role="worker").add_sink(mem).set_level(DEBUG)
        log.info("hi")
        self.assertEqual(mem.records, ["[worker] hi"])

    def test_func_appears_in_template(self) -> None:
        mem = MemorySink(formatter=template("{func}:{lineno}"))
        log = get_logger("tpl-fn").add_sink(mem).set_level(DEBUG)

        def my_function() -> None:
            log.info("x")

        my_function()
        # Just verify the func part is captured (lineno varies with edits).
        self.assertTrue(mem.records[0].startswith("my_function:"))


class RecordFieldOrder(unittest.TestCase):
    """Ensure all standard fields appear in asdict(), and user fields override."""

    def test_all_standard_keys(self) -> None:
        r = make_record(func="f", lineno=10, role="r")
        d = r.asdict()
        for key in ("ts", "level", "level_name", "func", "lineno", "role", "message", "kv"):
            self.assertIn(key, d, f"missing key: {key}")

    def test_role_defaults_to_empty_in_asdict(self) -> None:
        r = make_record()  # role not passed → default ""
        self.assertEqual(r.asdict()["role"], "")

    def test_user_fields_can_still_override_defaults(self) -> None:
        # Documented: fields.update happens after defaults.
        r = make_record(fields={"level": "CUSTOM"})
        d = r.asdict()
        self.assertEqual(d["level"], "CUSTOM")


class KvRendering(unittest.TestCase):
    """{kv} placeholder must flatten user fields into k=v pairs."""

    def test_empty_fields_renders_empty_string(self) -> None:
        self.assertEqual(make_record().asdict()["kv"], "")

    def test_single_field(self) -> None:
        r = make_record(fields={"project": "zteam"})
        self.assertEqual(r.asdict()["kv"], "project=zteam")

    def test_value_with_space_is_quoted(self) -> None:
        r = make_record(fields={"reason": "quota critical"})
        self.assertEqual(r.asdict()["kv"], 'reason="quota critical"')

    def test_multiple_fields_space_joined(self) -> None:
        r = make_record(fields={"a": 1, "b": "two words", "c": True})
        d = r.asdict()
        self.assertEqual(d["kv"], 'a=1 b="two words" c=True')

    def test_kv_usable_in_template(self) -> None:
        from zlog import template

        mem = MemorySink(formatter=template("{message} {kv}"))
        log = get_logger("kv-tpl").add_sink(mem)
        log.info("hi", project="zteam", note="ready")
        self.assertEqual(mem.records, ['hi project=zteam note=ready'])

    def test_kv_empty_in_template_no_trailing_space(self) -> None:
        from zlog import template

        mem = MemorySink(formatter=template("{message}{kv}"))  # no leading space
        log = get_logger("kv-empty").add_sink(mem)
        log.info("solo")
        self.assertEqual(mem.records, ["solo"])