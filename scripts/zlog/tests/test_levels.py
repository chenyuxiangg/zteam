"""Tests for zlog.levels: constants, lookup dicts, parse_level."""
from __future__ import annotations

import unittest

from zlog import CRITICAL, DEBUG, ERROR, INFO, LEVEL_NAMES, WARN, parse_level
from zlog.levels import NAME_TO_VALUE


class LevelConstants(unittest.TestCase):
    def test_values_are_increasing_by_ten(self) -> None:
        self.assertEqual([DEBUG, INFO, WARN, ERROR, CRITICAL], [10, 20, 30, 40, 50])

    def test_name_dict_covers_every_constant(self) -> None:
        self.assertEqual(
            set(LEVEL_NAMES.values()), {"DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"}
        )
        # Bidirectional lookup must agree.
        self.assertEqual(NAME_TO_VALUE, {v: k for k, v in LEVEL_NAMES.items()})
        for value, name in LEVEL_NAMES.items():
            self.assertEqual(parse_level(name), value)


class ParseLevelValid(unittest.TestCase):
    def test_accepts_name_string(self) -> None:
        self.assertEqual(parse_level("INFO"), 20)
        self.assertEqual(parse_level("info"), 20)  # case-insensitive
        self.assertEqual(parse_level("DEBUG"), 10)

    def test_accepts_int(self) -> None:
        self.assertEqual(parse_level(20), 20)
        self.assertEqual(parse_level(50), 50)


class ParseLevelInvalid(unittest.TestCase):
    def test_unknown_name(self) -> None:
        with self.assertRaises(ValueError):
            parse_level("TRACE")

    def test_unknown_int(self) -> None:
        with self.assertRaises(ValueError):
            parse_level(15)

    def test_negative_int(self) -> None:
        with self.assertRaises(ValueError):
            parse_level(-1)

    def test_none(self) -> None:
        with self.assertRaises(ValueError):
            parse_level(None)

    def test_float(self) -> None:
        with self.assertRaises(ValueError):
            parse_level(20.5)

    def test_bool_rejected(self) -> None:
        # bool is a subclass of int but is not a valid level value.
        with self.assertRaises(ValueError):
            parse_level(True)
