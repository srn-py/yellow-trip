# airflow/dags/taxi_pipeline/months.py
"""Decides which month of data a DAG run should process.

Rules, in order:
1. If the run was started with a `month` parameter, use it.
2. Otherwise use the month of the run's *logical date* (the date the run is "for").
   For a backfill from 2024-01-01 to 2024-03-31 the logical dates are Jan 1, Feb 1 and Mar 1,
   so the months processed are January, February and March, which is what you would expect.
3. For *scheduled* runs only, subtract `lag_months`: TLC publishes data about two months late,
   so a run on October 1st should look at August, not at a month that does not exist yet.
"""

import re

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class MonthResolutionError(ValueError):
    """Raised when no month can be worked out for a run."""


def parse_month(text: str) -> tuple[int, int]:
    """Convert "2024-01" into (2024, 1).

    Args:
        text: A month in YYYY-MM format.

    Returns:
        (year, month).

    Raises:
        MonthResolutionError: If the text is not a valid month.
    """
    match = _MONTH_RE.match(text.strip())
    if not match:
        raise MonthResolutionError(f"'{text}' is not a valid month. Use YYYY-MM, for example 2024-01.")
    return int(match.group(1)), int(match.group(2))


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Move a month forwards or backwards.

    Args:
        year: Four-digit year.
        month: Month 1 to 12.
        delta: Months to add (negative to go back).

    Returns:
        The shifted (year, month).
    """
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_label(year: int, month: int) -> str:
    """Format a month as YYYY-MM.

    Args:
        year: Four-digit year.
        month: Month 1 to 12.

    Returns:
        e.g. "2024-01".
    """
    return f"{year}-{month:02d}"


def normalise_run_type(run_type) -> str:
    """Turn Airflow's run type (a string or an enum) into a lowercase string.

    Args:
        run_type: Value taken from the DAG run, such as "scheduled", "manual" or "backfill".

    Returns:
        The lowercase text, or "" if unknown.
    """
    raw = getattr(run_type, "value", run_type)
    return str(raw or "").lower()


def resolve_target_month(
    *,
    param_month: str | None,
    logical_date,
    data_interval_start,
    run_type: str,
    lag_months: int,
) -> tuple[int, int]:
    """Work out which month a run should process.

    Args:
        param_month: Value of the `month` run parameter (empty means "work it out").
        logical_date: The run's logical date (a datetime) or None.
        data_interval_start: Start of the run's data interval or None (fallback).
        run_type: Normalised run type ("scheduled", "manual", "backfill", ...).
        lag_months: Months to subtract for scheduled runs.

    Returns:
        (year, month).

    Raises:
        MonthResolutionError: If the parameter is invalid, or nothing tells us the month.
    """
    if param_month and param_month.strip():
        return parse_month(param_month)

    reference = logical_date or data_interval_start
    if reference is None:
        raise MonthResolutionError(
            "This run has no logical date, so Airflow cannot tell which month to process. "
            "Start it with the `month` parameter, for example 2024-01."
        )

    year, month = reference.year, reference.month
    if run_type == "scheduled" and lag_months:
        year, month = shift_month(year, month, -lag_months)
    return year, month
