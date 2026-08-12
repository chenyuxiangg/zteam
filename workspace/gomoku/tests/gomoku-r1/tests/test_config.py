"""Tests for the :mod:`gomoku.config` module (FR-01 / FR-02 / NFR-07).

Covers:

* ``Config`` dataclass defaults (TC-SYS-04).
* ``build_arg_parser`` + ``config_from_args`` roundtrip (FR-01).
* Invalid CLI args rejected by argparse (TC-SYS-02).
* ``--forbidden on/off`` switching (TC-SYS-05 / TC-SYS-06).
* ``--size 13/15`` switching (TC-SYS-03).
* ``--human white/black`` switching (TC-SYS-06b).
* Derived helpers (``forbidden_enabled``, ``ai_color``, ``human_letter``).
"""

from __future__ import annotations

import pytest

from gomoku.board import BLACK, WHITE
from gomoku.config import (
    ALLOWED_DIFFICULTIES,
    ALLOWED_FORBIDDEN,
    ALLOWED_HUMAN_COLORS,
    ALLOWED_SIZES,
    Config,
    build_arg_parser,
    config_from_args,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_config_defaults():
    """Default Config matches the README: 15x15, medium, off, black."""
    cfg = Config(size=15, difficulty="medium", forbidden="off", human_color="black")
    assert cfg.size == 15
    assert cfg.difficulty == "medium"
    assert cfg.forbidden == "off"
    assert cfg.human_color == "black"
    assert cfg.debug_timing is False


def test_config_derived_helpers():
    """``forbidden_enabled``, ``ai_color``, ``human_letter`` semantics."""
    cfg = Config(size=15, difficulty="medium", forbidden="on", human_color="black")
    assert cfg.forbidden_enabled is True
    assert cfg.ai_color == WHITE  # human is black → AI is white
    assert cfg.human_letter == BLACK

    cfg2 = Config(size=15, difficulty="medium", forbidden="off", human_color="white")
    assert cfg2.forbidden_enabled is False
    assert cfg2.ai_color == BLACK  # human is white → AI is black
    assert cfg2.human_letter == WHITE


def test_config_is_frozen():
    """Config is a frozen dataclass — attempts to mutate raise."""
    cfg = Config(size=15, difficulty="medium", forbidden="off", human_color="black")
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.size = 13  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


@pytest.fixture
def parser():
    return build_arg_parser()


def test_argparser_size_choices():
    """TC-SYS-02: only 13/15 accepted as size."""
    for ok in ["13", "15"]:
        p = build_arg_parser()
        args = p.parse_args(["--size", ok])
        cfg = config_from_args(args)
        assert cfg.size == int(ok)
        assert cfg.size in ALLOWED_SIZES

    # Bad size rejected by argparse
    for bad in ["12", "19", "abc", "0"]:
        p = build_arg_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["--size", bad])


def test_argparser_difficulty_choices():
    """Only weak/medium/strong accepted."""
    for ok in ALLOWED_DIFFICULTIES:
        p = build_arg_parser()
        args = p.parse_args(["--difficulty", ok])
        cfg = config_from_args(args)
        assert cfg.difficulty == ok

    p = build_arg_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--difficulty", "xxx"])


def test_argparser_forbidden_choices():
    """TC-SYS-05/06: only on/off accepted for --forbidden."""
    for ok in ALLOWED_FORBIDDEN:
        p = build_arg_parser()
        args = p.parse_args(["--forbidden", ok])
        cfg = config_from_args(args)
        assert cfg.forbidden == ok
        assert cfg.forbidden_enabled == (ok == "on")

    p = build_arg_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--forbidden", "maybe"])


def test_argparser_human_color():
    """--human white is accepted (P2 experimental)."""
    p = build_arg_parser()
    args = p.parse_args(["--human", "white"])
    cfg = config_from_args(args)
    assert cfg.human_color == "white"
    assert cfg.human_letter == WHITE
    assert cfg.ai_color == BLACK

    p = build_arg_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--human", "red"])


def test_argparser_debug_timing_flag():
    """--debug-timing enables the timing hook (NFR-02 verification)."""
    p = build_arg_parser()
    args = p.parse_args(["--debug-timing"])
    cfg = config_from_args(args)
    assert cfg.debug_timing is True

    p = build_arg_parser()
    args = p.parse_args([])
    cfg = config_from_args(args)
    assert cfg.debug_timing is False


def test_argparser_roundtrip():
    """All flags combined produce a coherent Config."""
    p = build_arg_parser()
    args = p.parse_args(
        [
            "--size", "13",
            "--difficulty", "strong",
            "--forbidden", "on",
            "--human", "white",
            "--debug-timing",
        ]
    )
    cfg = config_from_args(args)
    assert cfg == Config(
        size=13, difficulty="strong", forbidden="on",
        human_color="white", debug_timing=True,
    )
