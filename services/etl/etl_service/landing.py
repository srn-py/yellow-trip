# services/etl/etl_service/landing.py
"""Definition of the `landing` schema in PostgreSQL.

The landing tables hold clean data exactly as the cleaning service produced it, before
dbt turns it into a star schema. The column list below is a *contract* with the cleaning
service: the Parquet files must contain exactly these columns, in the same meaning. A test
(`tests/test_etl_landing.py`) compares this list with the cleaning service's own output
columns, so a change on one side without the other fails the test suite.
"""

# (column name, PostgreSQL type). Money uses numeric(12,2): exact decimals, never floating point.
TRIP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("vendor_id", "integer"),
    ("tpep_pickup_datetime", "timestamp"),
    ("tpep_dropoff_datetime", "timestamp"),
    ("passenger_count", "integer"),
    ("trip_distance", "double precision"),
    ("ratecode_id", "integer"),
    ("store_and_fwd_flag", "text"),
    ("pu_location_id", "integer"),
    ("do_location_id", "integer"),
    ("payment_type", "integer"),
    ("fare_amount", "numeric(12,2)"),
    ("extra", "numeric(12,2)"),
    ("mta_tax", "numeric(12,2)"),
    ("tip_amount", "numeric(12,2)"),
    ("tolls_amount", "numeric(12,2)"),
    ("improvement_surcharge", "numeric(12,2)"),
    ("total_amount", "numeric(12,2)"),
    ("congestion_surcharge", "numeric(12,2)"),
    ("airport_fee", "numeric(12,2)"),
    ("cbd_congestion_fee", "numeric(12,2)"),
    ("trip_duration_minutes", "double precision"),
    ("avg_speed_mph", "double precision"),
    ("has_missing_trip_details", "boolean"),
    ("is_zero_passengers", "boolean"),
    ("source_year", "integer"),
    ("source_month", "integer"),
    ("source_file", "text"),
    ("source_row_number", "bigint"),
)

TRIP_COLUMN_NAMES: tuple[str, ...] = tuple(name for name, _ in TRIP_COLUMNS)


class SchemaContractError(ValueError):
    """Raised when a clean file does not have exactly the columns the warehouse expects."""


def check_columns(found: list[str]) -> None:
    """Verify that a file's columns match the landing table exactly.

    Args:
        found: Column names found in the Parquet file.

    Raises:
        SchemaContractError: If columns are missing or unexpected.
    """
    missing = [name for name in TRIP_COLUMN_NAMES if name not in found]
    unexpected = [name for name in found if name not in TRIP_COLUMN_NAMES]
    if missing or unexpected:
        raise SchemaContractError(
            f"Clean file does not match the landing table. Missing: {missing or 'none'}. "
            f"Unexpected: {unexpected or 'none'}."
        )


def build_landing_ddl() -> list[str]:
    """Return the SQL statements that create the landing schema and its tables.

    Every statement is idempotent (`IF NOT EXISTS`), so running them at every start is safe.

    Returns:
        A list of SQL statements, to be run in order.
    """
    trip_columns = ",\n    ".join(f"{name} {sql_type}" for name, sql_type in TRIP_COLUMNS)
    return [
        "CREATE SCHEMA IF NOT EXISTS landing",
        # loaded_at is filled by the database: the time the loading transaction started.
        # dbt uses it to find months that are new or were reloaded.
        f"""CREATE TABLE IF NOT EXISTS landing.trips (
            {trip_columns},
            loaded_at timestamptz NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS trips_month_idx ON landing.trips (source_year, source_month)",
        """CREATE TABLE IF NOT EXISTS landing.zones (
            location_id integer PRIMARY KEY,
            borough text,
            zone text,
            service_zone text
        )""",
        """CREATE TABLE IF NOT EXISTS landing.load_log (
            year integer NOT NULL,
            month integer NOT NULL,
            rows_loaded bigint NOT NULL,
            cleaned_at text NOT NULL,
            clean_object_key text NOT NULL,
            duration_seconds double precision,
            loaded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (year, month)
        )""",
    ]
