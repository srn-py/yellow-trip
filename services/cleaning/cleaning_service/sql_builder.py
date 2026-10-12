# services/cleaning/cleaning_service/sql_builder.py
"""Generates the SQL that standardises, derives, flags and validates one month of trips.

Pure functions: they only build text, so they are easy to test and to read.

The generated pipeline, in plain words:
  base    - pick the columns we need, under clean snake_case names, with safe type casts
  timed   - add the trip duration
  derived - add speed, flags, lineage columns and a duplicate counter
  flagged - add `reject_reasons`: the names of every rule the row breaks (empty = clean)
"""

import re
from dataclasses import dataclass

from .rules import Rule


class SchemaMismatchError(ValueError):
    """Raised when a source file lacks a column that cleaning cannot do without."""


@dataclass(frozen=True)
class ColumnSpec:
    """One column of the clean dataset.

    Attributes:
        name: Clean (snake_case) column name.
        sql_type: DuckDB type the value is cast to.
        required: If True, the source file must contain this column.
    """

    name: str
    sql_type: str
    required: bool


# The standard schema every month is mapped onto, in output order.
SOURCE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("vendor_id", "INTEGER", False),
    ColumnSpec("tpep_pickup_datetime", "TIMESTAMP", True),
    ColumnSpec("tpep_dropoff_datetime", "TIMESTAMP", True),
    ColumnSpec("passenger_count", "INTEGER", False),
    ColumnSpec("trip_distance", "DOUBLE", True),
    ColumnSpec("ratecode_id", "INTEGER", False),
    ColumnSpec("store_and_fwd_flag", "VARCHAR", False),
    ColumnSpec("pu_location_id", "INTEGER", True),
    ColumnSpec("do_location_id", "INTEGER", True),
    ColumnSpec("payment_type", "INTEGER", True),
    ColumnSpec("fare_amount", "DOUBLE", True),
    ColumnSpec("extra", "DOUBLE", False),
    ColumnSpec("mta_tax", "DOUBLE", False),
    ColumnSpec("tip_amount", "DOUBLE", False),
    ColumnSpec("tolls_amount", "DOUBLE", False),
    ColumnSpec("improvement_surcharge", "DOUBLE", False),
    ColumnSpec("total_amount", "DOUBLE", True),
    ColumnSpec("congestion_surcharge", "DOUBLE", False),
    ColumnSpec("airport_fee", "DOUBLE", False),
    ColumnSpec("cbd_congestion_fee", "DOUBLE", False),
)

# Columns we calculate (they do not exist in the source).
DERIVED_COLUMNS: tuple[str, ...] = (
    "trip_duration_minutes",
    "avg_speed_mph",
    "has_missing_trip_details",
    "is_zero_passengers",
    "source_year",
    "source_month",
    "source_file",
    "source_row_number",
)

# Exact column list (and order) of the clean file.
OUTPUT_COLUMNS: tuple[str, ...] = tuple(spec.name for spec in SOURCE_COLUMNS) + DERIVED_COLUMNS


def sql_literal(value: str) -> str:
    """Turn text into a safe SQL string literal (doubles single quotes)."""
    return "'" + value.replace("'", "''") + "'"


def quote_ident(name: str) -> str:
    """Quote a column name so odd characters or capitals cannot break the SQL."""
    return '"' + name.replace('"', '""') + '"'


def normalize_name(name: str) -> str:
    """Reduce a column name to lowercase letters and digits only.

    `Airport_fee`, `airport_fee` and `AirportFee` all become `airportfee`; `PULocationID`
    and `pu_location_id` both become `pulocationid`. Comparing normalised names makes the
    mapping tolerant of capitalisation and underscore changes between TLC releases.

    Args:
        name: A column name.

    Returns:
        The normalised name.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def map_columns(source_columns: list[str]) -> dict[str, str | None]:
    """Match each standard column to the column that carries it in the source file.

    Args:
        source_columns: Column names found in the source file.

    Returns:
        A dict: clean column name -> actual source column name, or None if the source
        lacks it (optional columns then become NULL).

    Raises:
        SchemaMismatchError: If any required column is missing.
    """
    by_key: dict[str, str] = {}
    for column in source_columns:
        by_key.setdefault(normalize_name(column), column)  # first match wins

    mapping: dict[str, str | None] = {}
    missing = []
    for spec in SOURCE_COLUMNS:
        actual = by_key.get(normalize_name(spec.name))
        mapping[spec.name] = actual
        if actual is None and spec.required:
            missing.append(spec.name)
    if missing:
        raise SchemaMismatchError(f"Source file is missing required column(s): {', '.join(missing)}")
    return mapping


def build_flagged_table_sql(
    parquet_path: str,
    mapping: dict[str, str | None],
    year: int,
    month: int,
    source_file: str,
    rules: list[Rule],
    table: str = "flagged",
) -> str:
    """Build the SQL that creates the `flagged` table.

    Args:
        parquet_path: Local path of the raw Parquet file.
        mapping: Result of `map_columns`.
        year: Year of the file (from the registry).
        month: Month of the file (from the registry).
        source_file: Raw object key, stored in every row for lineage.
        rules: The rejection rules.
        table: Name of the table to create.

    Returns:
        A `CREATE TABLE ... AS ...` statement.
    """
    select_parts = []
    for spec in SOURCE_COLUMNS:
        actual = mapping[spec.name]
        if actual is None:
            expression = f"CAST(NULL AS {spec.sql_type})"
        else:
            # TRY_CAST gives NULL instead of an error when a value cannot be converted.
            expression = f"TRY_CAST({quote_ident(actual)} AS {spec.sql_type})"
        select_parts.append(f"{expression} AS {spec.name}")
    select_columns = ",\n        ".join(select_parts)

    # concat_ws skips NULLs, so a clean row gets '' and a bad row gets 'rule_a;rule_b'.
    reasons = ",\n        ".join(f"CASE WHEN ({rule.condition}) THEN {sql_literal(rule.name)} END" for rule in rules)

    return f"""
CREATE TABLE {table} AS
WITH base AS (
    SELECT
        {select_columns},
        file_row_number AS source_row_number
    FROM read_parquet({sql_literal(parquet_path)}, file_row_number = true)
),
timed AS (
    SELECT *,
        (epoch(tpep_dropoff_datetime) - epoch(tpep_pickup_datetime)) / 60.0 AS trip_duration_minutes
    FROM base
),
derived AS (
    SELECT *,
        CASE WHEN trip_duration_minutes > 0
             THEN trip_distance / (trip_duration_minutes / 60.0) END AS avg_speed_mph,
        (passenger_count IS NULL OR ratecode_id IS NULL OR store_and_fwd_flag IS NULL)
            AS has_missing_trip_details,
        coalesce(passenger_count = 0, false) AS is_zero_passengers,
        CAST({int(year)} AS INTEGER) AS source_year,
        CAST({int(month)} AS INTEGER) AS source_month,
        {sql_literal(source_file)} AS source_file,
        row_number() OVER (
            PARTITION BY tpep_pickup_datetime, tpep_dropoff_datetime,
                         pu_location_id, do_location_id, total_amount
            ORDER BY source_row_number
        ) AS duplicate_rank
    FROM timed
)
SELECT *,
    concat_ws(';',
        {reasons}
    ) AS reject_reasons
FROM derived
"""


def build_counts_sql(rules: list[Rule], table: str = "flagged") -> str:
    """Build one query that counts everything the report needs, in a single pass.

    Result columns, in order: rows_in, rows_clean, rows_quarantined,
    clean rows with missing details, clean rows with zero passengers, then one
    count per rule (in the order of `rules`).

    Args:
        rules: The rejection rules.
        table: Table to count.

    Returns:
        A SELECT statement.
    """
    per_rule = ",\n    ".join(f"count(*) FILTER (WHERE ({rule.condition})) AS {rule.name}" for rule in rules)
    return f"""
SELECT
    count(*),
    count(*) FILTER (WHERE reject_reasons = ''),
    count(*) FILTER (WHERE reject_reasons <> ''),
    count(*) FILTER (WHERE has_missing_trip_details AND reject_reasons = ''),
    count(*) FILTER (WHERE is_zero_passengers AND reject_reasons = ''),
    {per_rule}
FROM {table}
"""


def build_copy_sql(table: str, destination: str, quarantined: bool) -> str:
    """Build the statement that writes the clean or the quarantine Parquet file.

    Args:
        table: The flagged table.
        destination: Local output path.
        quarantined: True for rejected rows (adds the `reject_reasons` column),
            False for clean rows.

    Returns:
        A `COPY ... TO ...` statement.
    """
    columns = ", ".join(OUTPUT_COLUMNS)
    if quarantined:
        select = f"SELECT {columns}, reject_reasons FROM {table} WHERE reject_reasons <> ''"
    else:
        select = f"SELECT {columns} FROM {table} WHERE reject_reasons = ''"
    return f"COPY ({select}) TO {sql_literal(destination)} (FORMAT PARQUET, COMPRESSION ZSTD)"
