"""Make `tests/` importable so test modules can share `_platform`.

The test suite has no package markers (`__init__.py`), so pytest puts each test
file's own directory on `sys.path` — not `tests/` itself. This bootstrap adds
`tests/` explicitly, which keeps `from _platform import BASH` working regardless
of pytest's import mode.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
