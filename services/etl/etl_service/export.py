# services/etl/etl_service/export.py
"""Convert files to a format PostgreSQL can bulk-load very fast.

Inserting millions of rows one by one would take hours. PostgreSQL's `COPY` command streams
CSV data in at hundreds of thousands of rows per second. DuckDB writes that CSV from the
Parquet file in a few seconds (and spills to disk if memory is tight).

CSV conventions used here: NULL is written as an empty, unquoted field, which is exactly
what PostgreSQL's `COPY ... (FORMAT CSV)` reads back as NULL.
"""

from pathlib import Path

import duckdb

from .landing import TRIP_COLUMN_NAMES, check_columns


class ZoneFileError(ValueError):
    """Raised when the zone lookup CSV does not have the expected shape."""


def _literal(value: str) -> str:
    """Turn text into a safe SQL string literal (doubles single quotes)."""
    return "'" + value.replace("'", "''") + "'"


def _quote(name: str) -> str:
    """Quote a column name for SQL."""
    return '"' + name.replace('"', '""') + '"'


def parquet_to_csv(parquet_path: Path, csv_path: Path, memory_limit: str = "2GB") -> int:
    """Write a clean Parquet file as headerless CSV, columns in landing-table order.

    Args:
        parquet_path: Clean Parquet file (from the cleaning service).
        csv_path: Output CSV file.
        memory_limit: Maximum memory DuckDB may use.

    Returns:
        The number of rows written.

    Raises:
        SchemaContractError: If the file's columns differ from the landing table.
    """
    source = f"read_parquet({_literal(str(parquet_path))})"
    con = duckdb.connect(config={"memory_limit": memory_limit})
    try:
        found = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
        check_columns(found)
        columns = ", ".join(TRIP_COLUMN_NAMES)  # explicit order = landing table order
        result = con.execute(
            f"COPY (SELECT {columns} FROM {source}) TO {_literal(str(csv_path))} (FORMAT CSV, HEADER false)"
        ).fetchone()
        return int(result[0])
    finally:
        con.close()


def zones_to_csv(raw_csv: Path, csv_path: Path) -> int:
    """Convert the TLC zone lookup CSV into headerless CSV for the `landing.zones` table.

    Args:
        raw_csv: The zone lookup file as downloaded (4 columns with a header line).
        csv_path: Output CSV file.

    Returns:
        The number of rows written.

    Raises:
        ZoneFileError: If the file does not have exactly 4 columns.
    """
    source = f"read_csv({_literal(str(raw_csv))}, header = true)"
    con = duckdb.connect()
    try:
        names = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
        if len(names) != 4:
            raise ZoneFileError(f"Zone lookup should have 4 columns, found {len(names)}: {names}")
        location, borough, zone, service_zone = (_quote(name) for name in names)
        result = con.execute(
            f"COPY (SELECT CAST({location} AS INTEGER), CAST({borough} AS VARCHAR), "
            f"CAST({zone} AS VARCHAR), CAST({service_zone} AS VARCHAR) FROM {source}) "
            f"TO {_literal(str(csv_path))} (FORMAT CSV, HEADER false)"
        ).fetchone()
        return int(result[0])
    finally:
        con.close()
