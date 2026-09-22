"""Tests for zlog.formatter: template substitution and custom callables."""
from __future__ import annotations

import unittest

from zlog import INFO, Formatter, template

from ._helpers import make_record


class TemplateFormatter(unittest.TestCase):
    def test_basic_substitution(self) -> None:
        f = template("{ts} {level_name} {func} {message}")
        r = make_record(level=INFO, func="statectl", message="hello")
        # ts uses milliseconds precision, so naive datetimes get ".000".
        self.assertEqual(f(r), "2026-01-01T12:00:00.000 INFO statectl hello")

    def test_user_field_substitution(self) -> None:
        f = template("{func}: {message} project={project}")
        r = make_record(func="statectl", message="ok", fields={"project": "zteam"})
        self.assertEqual(f(r), "statectl: ok project=zteam")

    def test_width_format_spec(self) -> None:
        # :7 right-aligns level_name in a 7-char field.
        f = template("{level_name:7}")
        r = make_record(level=INFO)
        self.assertEqual(f(r), "INFO   ")

    def test_missing_field_raises(self) -> None:
        # str.format is strict by default; missing keys surface KeyError.
        f = template("{nonexistent}")
        r = make_record()
        with self.assertRaises(KeyError):
            f(r)


class CallableFormatter(unittest.TestCase):
    def test_lambda_formatter(self) -> None:
        f: Formatter = lambda r: f"{r.func}={r.message}"
        r = make_record(func="x", message="y")
        self.assertEqual(f(r), "x=y")

    def test_function_formatter(self) -> None:
        def upper(record):
            return record.message.upper()

        r = make_record(message="hello")
        self.assertEqual(upper(r), "HELLO")

    def test_formatter_satisfies_protocol(self) -> None:
        # The runtime-checkable Protocol allows isinstance checks.
        f = template("{message}")
        self.assertIsInstance(f, Formatter)
