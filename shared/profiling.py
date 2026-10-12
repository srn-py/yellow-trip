# shared/profiling.py
"""Reusable data-profiling helpers.

*Profiling* means measuring a dataset before changing it: how many rows, which
columns, how many missing values, what ranges, which values look impossible.
These helpers are used by the exploration notebooks now and by the cleaning
service in Milestone 3, so the rules we discover here become the rules we enforce.

All functions take a DuckDB connection and the name of a view/table to profile.
"""

import re

import pandas as pd
from duckdb import DuckDBPyConnection

from shared.lake import TRIPS_VIEW

# ---------------------------------------------------------------------------
# Data quality rules. Each entry is: check name -> SQL condition that is TRUE for
# a BAD row. These are the first draft of the cleaning rules for Milestone 3.
# They are trusted constants; never build these from user input.
# ---------------------------------------------------------------------------
QUALITY_CHECKS: dict[str, str] = {
    "negative_fare": "fare_amount < 0",
    "negative_total_amount": "total_amount < 0",
    "negative_tip": "tip_amount < 0",
    "zero_or_negative_distance": "trip_distance <= 0",
    "distance_over_100_miles": "trip_distance > 100",
    "dropoff_not_after_pickup": "tpep_dropoff_datetime <= tpep_pickup_datetime",
    "duration_over_24h": "epoch(tpep_dropoff_datetime) - epoch(tpep_pickup_datetime) > 86400",
    "speed_over_100_mph": (
        "epoch(tpep_dropoff_datetime) - epoch(tpep_pickup_datetime) > 0 AND "
        "trip_distance / ("
        "(epoch(tpep_dropoff_datetime) - epoch(tpep_pickup_datetime))"
        " / 3600.0) > 100"
    ),
    "null_passenger_count": "passenger_count IS NULL",
    "zero_passengers": "passenger_count = 0",
    "over_6_passengers": "passenger_count > 6",
    "pickup_outside_file_month": (
        "CAST(date_trunc('month', tpep_pickup_datetime) AS DATE) "
        "<> make_date(CAST(year AS INTEGER), CAST(month AS INTEGER), 1)"
    ),
    "invalid_pickup_zone": "PULocationID IS NULL OR PULocationID NOT BETWEEN 1 AND 265",
    "invalid_dropoff_zone": "DOLocationID IS NULL OR DOLocationID NOT BETWEEN 1 AND 265",
    "invalid_payment_type": "payment_type IS NULL OR payment_type NOT BETWEEN 0 AND 6",
}

# Two rows with the same values in all of these columns are treated as duplicates.
DEFAULT_DUPLICATE_KEYS = (
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "PULocationID",
    "DOLocationID",
    "total_amount",
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_identifier(name: str) -> str:
    """Allow only plain names (letters, digits, underscore) in generated SQL.

    Args:
        name: A view or column name.

    Returns:
        The same name, if it is safe.

    Raises:
        ValueError: If the name contains anything else.
    """
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def _sql_literal(value: str) -> str:
    """Turn text into a safe SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def row_counts_by_month(con: DuckDBPyConnection, view: str = TRIPS_VIEW) -> pd.DataFrame:
    """Count rows per source file month.

    The view must have `year` and `month` columns (from the folder names).

    Args:
        con: DuckDB connection.
        view: View or table to count.

    Returns:
        A table with columns year, month, trips.
    """
    view = _check_identifier(view)
    return con.execute(
        f"SELECT year, month, count(*) AS trips FROM {view} GROUP BY year, month ORDER BY year, month"
    ).df()


def column_profile(con: DuckDBPyConnection, view: str = TRIPS_VIEW) -> pd.DataFrame:
    """Profile every column: type, min, max, average, quartiles, null percentage.

    Uses DuckDB's built-in SUMMARIZE command.

    Args:
        con: DuckDB connection.
        view: View or table to profile.

    Returns:
        One row per column.
    """
    view = _check_identifier(view)
    profile = con.execute(f"SUMMARIZE {view}").df()
    profile["null_percentage"] = profile["null_percentage"].astype(float)
    return profile


def count_duplicates(
    con: DuckDBPyConnection,
    view: str = TRIPS_VIEW,
    key_columns: tuple[str, ...] = DEFAULT_DUPLICATE_KEYS,
) -> dict:
    """Count rows that repeat the same key values as an earlier row.

    Args:
        con: DuckDB connection.
        view: View or table to check.
        key_columns: Columns that together identify "the same trip".

    Returns:
        A dict with total_rows, duplicate_rows (the surplus copies) and duplicate_pct.
    """
    view = _check_identifier(view)
    keys = ", ".join(_check_identifier(column) for column in key_columns)
    total = con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
    extra = con.execute(
        f"SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) AS n FROM {view} GROUP BY {keys} HAVING count(*) > 1)"
    ).fetchone()[0]
    return {
        "total_rows": int(total),
        "duplicate_rows": int(extra),
        "duplicate_pct": round(100 * int(extra) / total, 4) if total else 0.0,
    }


def quality_report(
    con: DuckDBPyConnection,
    view: str = TRIPS_VIEW,
    checks: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Count how many rows break each quality rule, in a single pass over the data.

    Args:
        con: DuckDB connection.
        view: View or table to check.
        checks: Mapping of check name to SQL condition for a BAD row; defaults to
            `QUALITY_CHECKS`.

    Returns:
        A table with columns check, rule, bad_rows, bad_pct, total_rows.
    """
    view = _check_identifier(view)
    checks = checks or QUALITY_CHECKS
    selects = ", ".join(
        f"count(*) FILTER (WHERE {condition}) AS {_check_identifier(name)}" for name, condition in checks.items()
    )
    row = con.execute(f"SELECT count(*) AS total_rows, {selects} FROM {view}").fetchone()
    total = int(row[0])
    records = [
        {
            "check": name,
            "rule": condition,
            "bad_rows": int(count),
            "bad_pct": round(100 * int(count) / total, 4) if total else 0.0,
            "total_rows": total,
        }
        for (name, condition), count in zip(checks.items(), row[1:], strict=True)
    ]
    return pd.DataFrame(records)


def histogram(
    con: DuckDBPyConnection,
    column: str,
    low: float,
    high: float,
    bins: int = 50,
    view: str = TRIPS_VIEW,
) -> pd.DataFrame:
    """Count rows in equal-width buckets of a numeric column.

    Rows outside [low, high) are ignored, which keeps outliers from squashing the chart.

    Args:
        con: DuckDB connection.
        column: Numeric column name.
        low: Lower bound (inclusive).
        high: Upper bound (exclusive).
        bins: Number of buckets.
        view: View or table to read.

    Returns:
        A table with columns bin_start and trips.
    """
    column = _check_identifier(column)
    view = _check_identifier(view)
    low, high = float(low), float(high)
    width = (high - low) / bins
    return con.execute(
        f"SELECT {low} + floor(({column} - {low}) / {width}) * {width} AS bin_start, "
        f"count(*) AS trips FROM {view} "
        f"WHERE {column} >= {low} AND {column} < {high} GROUP BY 1 ORDER BY 1"
    ).df()


def _file_label(path: str) -> str:
    """Turn `.../year=2024/month=01/x.parquet` into `2024-01` (or the file name)."""
    match = re.search(r"year=(\d{4})/month=(\d{2})", path)
    return f"{match.group(1)}-{match.group(2)}" if match else path.rsplit("/", 1)[-1]


def schema_by_file(con: DuckDBPyConnection, pattern: str) -> pd.DataFrame:
    """Compare column names and types across many Parquet files.

    Each Parquet file stores its own schema. TLC changes theirs over time (columns
    added, renamed, retyped); this table makes such *schema drift* visible.

    Args:
        con: DuckDB connection (with S3 access if the pattern is an s3:// path).
        pattern: A file path pattern, e.g. `trips_glob(settings)`.

    Returns:
        A table: rows = column names, columns = file (e.g. "2024-01"), values = type.

    Raises:
        ValueError: If no file matches the pattern.
    """
    files = [row[0] for row in con.execute(f"SELECT file FROM glob({_sql_literal(pattern)}) ORDER BY file").fetchall()]
    if not files:
        raise ValueError(f"No files match {pattern}")

    frames = []
    for file in files:
        frame = con.execute(
            "SELECT name AS column_name, type, converted_type "
            f"FROM parquet_schema({_sql_literal(file)}) WHERE type IS NOT NULL"
        ).df()
        frame["file"] = _file_label(file)
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    combined["dtype"] = (combined["type"].fillna("") + " " + combined["converted_type"].fillna("")).str.strip()
    return combined.pivot_table(index="column_name", columns="file", values="dtype", aggfunc="first")


def find_schema_drift(schema: pd.DataFrame) -> pd.DataFrame:
    """Pick out columns that are missing from some files or have different types.

    Args:
        schema: The table returned by `schema_by_file`.

    Returns:
        Only the rows (columns of the data) that are not identical in every file.
    """
    missing_somewhere = schema.isna().any(axis=1)
    types_differ = schema.nunique(axis=1, dropna=True) > 1
    return schema[missing_somewhere | types_differ]
