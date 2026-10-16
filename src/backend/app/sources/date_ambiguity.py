"""Recognize date strings with two distinct valid day/month interpretations."""

from datetime import date
import re

_DATE = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")
DATE_FORMAT_AMBIGUITY = "date_format_ambiguous: DD/MM/YYYY or MM/DD/YYYY"


def detect_date_ambiguity(value: str) -> str | None:
    """Report slash-date ambiguity without choosing a format or changing value."""
    match = _DATE.fullmatch(value.strip())
    if match is None:
        return None
    first, second, year = map(int, match.groups())
    try:
        month_first = date(year, first, second)
        day_first = date(year, second, first)
    except ValueError:
        return None
    return DATE_FORMAT_AMBIGUITY if month_first != day_first else None
