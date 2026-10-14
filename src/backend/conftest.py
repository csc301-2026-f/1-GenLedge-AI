"""Pytest configuration for the backend suite.

Ensures `app` and the `tests` package resolve regardless of the directory pytest is
invoked from, so `python -m pytest tests` and `python -m pytest` behave the same.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
