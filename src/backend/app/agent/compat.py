"""Small standard-library compatibility surface.

`STRICT_MODEL_PYTHON_FLOOR` is the oldest interpreter the agent package supports.
`StrEnum` landed in Python 3.11; `collections.abc` already provides the behaviour
on 3.10, so the fallback below is a two-line adaptation rather than a second
implementation. The rest of the package uses only names available in 3.10.
"""

from __future__ import annotations

import sys
from enum import Enum

STRICT_MODEL_PYTHON_FLOOR = (3, 10)

if sys.version_info >= (3, 11):  # pragma: no cover - version-dependent
    from enum import StrEnum
else:  # pragma: no cover - version-dependent

    class StrEnum(str, Enum):  # noqa: UP042 - the pre-3.11 shim
        """`str`-valued enum with the 3.11 semantics the contracts expect."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = ["STRICT_MODEL_PYTHON_FLOOR", "StrEnum"]
