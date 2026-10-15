"""The `StrEnum` compatibility surface behaves like the standard library.

`app/agent/compat.py` provides a `str`-valued enum on Python 3.10. Generated JSON,
log lines and contract dumps all depend on it stringifying like `enum.StrEnum`, so
the equivalence is asserted rather than assumed.
"""

from __future__ import annotations

import json

from app.agent.compat import STRICT_MODEL_PYTHON_FLOOR, StrEnum
from app.agent.contracts import Disposition, FindingCode, Severity, SourceType, TransformName


class Colour(StrEnum):
    RED = "red"
    GREEN = "green"


def test_str_returns_the_value_not_the_enum_repr():
    assert str(Colour.RED) == "red"
    assert f"{Colour.RED}" == "red"
    assert "{}".format(Colour.RED) == "red"  # noqa: UP032 - the format path is the point
    assert "%s" % Colour.RED == "red"  # noqa: UP031 - the format path is the point
    assert f"{Colour.RED:>5}" == "  red"


def test_json_and_equality_behave_like_plain_strings():
    assert json.dumps({"colour": Colour.RED}) == '{"colour": "red"}'
    assert Colour.RED == "red"
    assert "red" == Colour.RED
    assert {"red": 1}[Colour.RED] == 1
    # Mixed with plain strings, ordering follows the string value on both runtimes.
    assert sorted([Colour.GREEN, Colour.RED, "amber"]) == ["amber", Colour.GREEN, Colour.RED]


def test_contract_enums_stringify_into_their_wire_values():
    assert str(SourceType.TEXT) == "text"
    assert str(Disposition.RAW_ONLY) == "raw_only"
    assert str(Severity.BLOCKER) == "blocker"
    assert str(TransformName.DATE_FORMAT) == "date_format"
    assert str(FindingCode.INVALID_MERGE_KEY) == "invalid_merge_key"
    assert json.loads(json.dumps({"severity": Severity.BLOCKER})) == {"severity": "blocker"}
    assert json.loads(json.dumps({"type": SourceType.TIMESTAMP})) == {"type": "timestamp"}


def test_the_declared_python_floor_is_at_most_the_running_interpreter():
    import sys

    assert STRICT_MODEL_PYTHON_FLOOR <= sys.version_info[:2]
