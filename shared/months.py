# shared/months.py
"""Helpers for month ranges such as "2024-01" to "2024-03"."""

import re

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
MAX_MONTHS_PER_REQUEST = 36


def parse_month(value: str) -> tuple[int, int]:
    """Convert "2024-01" into (2024, 1).

    Args:
        value: Text in YYYY-MM format.

    Returns:
        (year, month).

    Raises:
        ValueError: If the text is not a valid YYYY-MM month.
    """
    if not re.match(MONTH_PATTERN, value):
        raise ValueError(f"'{value}' is not a valid month. Use YYYY-MM, e.g. 2024-01.")
    year, month = value.split("-")
    return int(year), int(month)


def expand_months(
    start: str, end: str | None = None, max_months: int = MAX_MONTHS_PER_REQUEST
) -> list[tuple[int, int]]:
    """Expand a start (and optional end) month into every month in between.

    Args:
        start: First month, YYYY-MM.
        end: Last month, YYYY-MM. If omitted, only `start` is returned.
        max_months: Safety limit on the length of the range.

    Returns:
        A list of (year, month) pairs, both ends included.

    Raises:
        ValueError: If a month is invalid, the range is reversed, or it is too long.
    """
    first = parse_month(start)
    last = parse_month(end) if end else first
    if last < first:
        raise ValueError("'end' must not be before 'start'")
    count = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
    if count > max_months:
        raise ValueError(f"At most {max_months} months per request (asked for {count}).")

    months = []
    year, month = first
    while (year, month) <= last:
        months.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months
