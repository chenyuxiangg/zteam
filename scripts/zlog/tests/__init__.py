"""zlog test suite.

Runs as::

    python3 -m unittest discover -s scripts/zlog/tests -v

This __init__ ensures the zlog package is importable from any working
directory, since unittest discover only adds the tests/ folder to
sys.path, not the parent scripts/ folder where zlog lives.
"""
from __future__ import annotations

import os
import sys

# scripts/zlog/tests/__init__.py -> scripts/ (where zlog/ sits)
_SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
