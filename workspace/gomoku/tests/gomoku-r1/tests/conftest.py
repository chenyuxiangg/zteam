"""Shared pytest fixtures for the gomoku test suite.

We add the ``code/`` directory (which contains the ``gomoku`` package)
to ``sys.path`` so ``import gomoku`` works without an explicit
``PYTHONPATH=.`` prefix when developers run ``pytest`` from the
workspace root.

This keeps the test suite self-contained — no install step required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# Locate the code package — we expect a sibling `code/gomoku-r1/`
# directory that holds the actual gomoku source.  Allow override via
# the ``GOMOKU_CODE_DIR`` env var so CI / Docker smoke can inject a
# different location.
_DEFAULT_CODE_DIR = (
    Path(__file__).resolve().parents[4] / "code" / "gomoku-r1"
)


def _ensure_code_on_path() -> str:
    code_dir = os.environ.get("GOMOKU_CODE_DIR", str(_DEFAULT_CODE_DIR))
    code_dir = os.path.abspath(code_dir)
    if code_dir not in sys.path and os.path.isdir(code_dir):
        sys.path.insert(0, code_dir)
    return code_dir


CODE_DIR = _ensure_code_on_path()


@pytest.fixture(scope="session")
def code_dir() -> str:
    """Absolute path to the gomoku source directory added to sys.path."""
    return CODE_DIR


@pytest.fixture(scope="session")
def gomoku_pkg():
    """Import the gomoku package and return it (catches import errors)."""
    import gomoku  # noqa: WPS433 (deliberate late import)

    return gomoku
