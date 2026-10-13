# shared/lake.py
"""Connect DuckDB to the data lake.

DuckDB is an analytics SQL engine that runs inside our own Python process (no server
to install). Through its `httpfs` extension it can read files straight out of
S3-compatible storage, so we can write SQL against the Parquet files in the raw
bucket without downloading or loading them first.

This module hides the connection details so notebooks (and later services) can do:

    con = open_lake()
    con.execute("SELECT count(*) FROM trips_raw").df()
"""

import logging
from urllib.parse import urlparse

import duckdb

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Names of the SQL views we create. Views are saved queries; no data is copied.
TRIPS_VIEW = "trips_raw"
ZONES_VIEW = "zones"


class LakeEmptyError(RuntimeError):
    """Raised when no trip files can be read from the raw bucket."""


def _sql_literal(value: str) -> str:
    """Turn text into a safe SQL string literal (doubles any single quotes)."""
    return "'" + value.replace("'", "''") + "'"


def build_secret_sql(settings: Settings) -> str:
    """Build the SQL that gives DuckDB the S3 address and credentials.

    A DuckDB *secret* stores connection details once, so later queries can
    just say `s3://bucket/path`.

    Args:
        settings: Application settings holding endpoint and credentials.

    Returns:
        A `CREATE SECRET` SQL statement.
    """
    parsed = urlparse(settings.s3_endpoint_url)
    use_ssl = "true" if parsed.scheme == "https" else "false"
    return (
        "CREATE OR REPLACE SECRET lake_secret ("
        "TYPE S3, "
        f"KEY_ID {_sql_literal(settings.s3_access_key)}, "
        f"SECRET {_sql_literal(settings.s3_secret_key)}, "
        f"ENDPOINT {_sql_literal(parsed.netloc)}, "  # host:port without http://
        f"REGION {_sql_literal(settings.s3_region)}, "
        "URL_STYLE 'path', "
        f"USE_SSL {use_ssl})"
    )


def trips_glob(settings: Settings, year: int | None = None, month: int | None = None) -> str:
    """Build the S3 path pattern that selects trip files.

    A "glob" uses `*` as a wildcard. Our raw layout is
    `yellow_tripdata/year=YYYY/month=MM/<file>.parquet`.

    Args:
        settings: Application settings (bucket name).
        year: Restrict to one year, or None for all years.
        month: Restrict to one month (1-12), or None for all months.

    Returns:
        A pattern such as `s3://raw/yellow_tripdata/year=*/month=*/*.parquet`.
    """
    year_part = str(year) if year else "*"
    month_part = f"{month:02d}" if month else "*"
    return f"s3://{settings.bucket_raw}/yellow_tripdata/year={year_part}/month={month_part}/*.parquet"


def connect_lake(settings: Settings | None = None) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB connection that can read from the lake.

    Args:
        settings: Settings to use; defaults to the shared application settings.

    Returns:
        A ready-to-use DuckDB connection.
    """
    settings = settings or get_settings()
    con = duckdb.connect()  # in-memory: nothing is saved to disk
    con.execute("INSTALL httpfs")  # no-op when already installed (the Docker image does it)
    con.execute("LOAD httpfs")
    con.execute(build_secret_sql(settings))
    return con


def register_views(
    con: duckdb.DuckDBPyConnection,
    settings: Settings | None = None,
    year: int | None = None,
    month: int | None = None,
) -> None:
    """Create the `trips_raw` and `zones` views on top of the raw files.

    `union_by_name=true` matches columns by NAME across files, so months with
    different columns still combine (missing columns become NULL).
    `hive_partitioning=true` turns the `year=2024/month=01` folder names into
    real `year` and `month` columns. `filename=true` adds a `filename` column.

    Args:
        con: Connection from `connect_lake`.
        settings: Settings to use; defaults to the shared settings.
        year: Restrict to one year (optional).
        month: Restrict to one month (optional).

    Raises:
        LakeEmptyError: If trip files cannot be read.
    """
    settings = settings or get_settings()
    pattern = trips_glob(settings, year, month)
    try:
        con.execute(
            f"CREATE OR REPLACE VIEW {TRIPS_VIEW} AS "
            f"SELECT * FROM read_parquet({_sql_literal(pattern)}, "
            "union_by_name = true, hive_partitioning = true, filename = true)"
        )
    except duckdb.IOException as exc:
        raise LakeEmptyError(
            f"Could not read trip files from {pattern}: {exc}. "
            "Is the object store running, and did you ingest data (Milestone 1)?"
        ) from exc

    zones_path = f"s3://{settings.bucket_raw}/reference/taxi_zone_lookup.csv"
    try:
        con.execute(
            f"CREATE OR REPLACE VIEW {ZONES_VIEW} AS SELECT * FROM read_csv({_sql_literal(zones_path)}, header = true)"
        )
    except duckdb.Error:
        logger.warning("Zone lookup not found. Ingest it with POST /ingest/zones/download.")


def open_lake(
    settings: Settings | None = None, year: int | None = None, month: int | None = None
) -> duckdb.DuckDBPyConnection:
    """Connect to the lake and register the views in one step.

    Args:
        settings: Settings to use; defaults to the shared settings.
        year: Restrict to one year (optional).
        month: Restrict to one month (optional).

    Returns:
        A connection where `trips_raw` (and `zones`, if available) can be queried.
    """
    settings = settings or get_settings()
    con = connect_lake(settings)
    register_views(con, settings, year, month)
    return con
