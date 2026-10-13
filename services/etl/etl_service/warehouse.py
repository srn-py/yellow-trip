# services/etl/etl_service/warehouse.py
"""All PostgreSQL access of the ETL service.

The key idea is the **transaction**: everything in `replace_month` happens as one
all-or-nothing unit. If the row count does not match, or anything fails half-way, PostgreSQL
rolls everything back and the warehouse is exactly as it was before. Readers never see a
month that is half deleted or half loaded.

`psycopg2` is imported lazily (inside functions) so the rest of the code, and the tests, can
be used without a PostgreSQL driver installed.
"""

import logging
import time
from pathlib import Path

from shared.config import Settings

from .landing import TRIP_COLUMN_NAMES, build_landing_ddl

logger = logging.getLogger(__name__)

_UPSERT_LOG = """
INSERT INTO landing.load_log
    (year, month, rows_loaded, cleaned_at, clean_object_key, duration_seconds, loaded_at)
VALUES (%s, %s, %s, %s, %s, %s, now())
ON CONFLICT (year, month) DO UPDATE SET
    rows_loaded = EXCLUDED.rows_loaded,
    cleaned_at = EXCLUDED.cleaned_at,
    clean_object_key = EXCLUDED.clean_object_key,
    duration_seconds = EXCLUDED.duration_seconds,
    loaded_at = EXCLUDED.loaded_at
RETURNING *
"""


class LoadMismatchError(RuntimeError):
    """Raised when the number of rows in the warehouse does not match what was expected."""


def _serialize(row: dict | None) -> dict | None:
    """Make a database row JSON-friendly (timestamps become text)."""
    if row is None:
        return None
    return {key: (value.isoformat() if hasattr(value, "isoformat") else value) for key, value in row.items()}


class Warehouse:
    """Connects to PostgreSQL and performs the load operations."""

    def __init__(self, host: str, port: int, dbname: str, user: str, password: str):
        self._params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> "Warehouse":
        """Create a Warehouse from the application settings.

        Args:
            settings: Application settings (`POSTGRES_*`).

        Returns:
            A configured `Warehouse`.
        """
        return cls(
            settings.postgres_host,
            settings.postgres_port,
            settings.postgres_db,
            settings.postgres_user,
            settings.postgres_password,
        )

    def _connect(self):
        """Open a new connection; rows come back as dictionaries."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        return psycopg2.connect(cursor_factory=RealDictCursor, connect_timeout=5, **self._params)

    def wait_until_ready(self, timeout_seconds: int = 90) -> None:
        """Wait until PostgreSQL accepts connections.

        Args:
            timeout_seconds: Give up (raise) after this many seconds.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                self._connect().close()
                return
            except Exception as exc:  # Any connection problem means "not ready yet".
                if time.monotonic() >= deadline:
                    raise
                logger.info("Warehouse not ready yet (%s). Retrying...", type(exc).__name__)
                time.sleep(2)

    def ensure_schema(self) -> None:
        """Create the landing schema and tables if they do not exist."""
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:  # `with conn` = one transaction
                for statement in build_landing_ddl():
                    cur.execute(statement)
        finally:
            conn.close()

    def is_reachable(self) -> bool:
        """Check that PostgreSQL answers a trivial query.

        Returns:
            True if the query succeeds.
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return True
            finally:
                conn.close()
        except Exception:
            return False

    def get_month_log(self, year: int, month: int) -> dict | None:
        """Look up the load log entry of a month.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            The log entry, or None if the month was never loaded.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM landing.load_log WHERE year = %s AND month = %s", (year, month))
                return _serialize(cur.fetchone())
        finally:
            conn.close()

    def replace_month(
        self,
        year: int,
        month: int,
        csv_path: Path,
        expected_rows: int,
        cleaned_at: str,
        clean_object_key: str,
        duration_seconds: float,
    ) -> dict:
        """Replace one month in `landing.trips`, all-or-nothing.

        Steps inside ONE transaction: delete the month's old rows, bulk-load the CSV with COPY,
        count the rows now stored for that month, compare with the expected number, write the log.

        Args:
            year: Four-digit year of the month.
            month: Month 1 to 12.
            csv_path: Headerless CSV in landing column order.
            expected_rows: How many rows must end up stored.
            cleaned_at: Finish time of the cleaning report this data came from.
            clean_object_key: Lake location of the clean file (for the log).
            duration_seconds: How long preparing the load took (for the log).

        Returns:
            The load log entry.

        Raises:
            LoadMismatchError: If the stored row count differs from `expected_rows`
                (the transaction is rolled back, nothing changes).
        """
        columns = ", ".join(TRIP_COLUMN_NAMES)
        copy_sql = f"COPY landing.trips ({columns}) FROM STDIN WITH (FORMAT CSV)"
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:  # commit on success, roll back on any exception
                cur.execute(
                    "DELETE FROM landing.trips WHERE source_year = %s AND source_month = %s",
                    (year, month),
                )
                with Path(csv_path).open("r", encoding="utf-8", newline="") as handle:
                    cur.copy_expert(copy_sql, handle)
                cur.execute(
                    "SELECT count(*) AS n FROM landing.trips WHERE source_year = %s AND source_month = %s",
                    (year, month),
                )
                stored = int(cur.fetchone()["n"])
                if stored != expected_rows:
                    raise LoadMismatchError(
                        f"{year}-{month:02d}: {stored} rows stored but {expected_rows} expected. "
                        "Rolled back; nothing was changed."
                    )
                cur.execute(
                    _UPSERT_LOG,
                    (year, month, stored, cleaned_at, clean_object_key, duration_seconds),
                )
                return _serialize(cur.fetchone())
        finally:
            conn.close()

    def replace_zones(self, csv_path: Path) -> int:
        """Replace the whole zone lookup table.

        Args:
            csv_path: Headerless CSV with columns location_id, borough, zone, service_zone.

        Returns:
            The number of zones now stored.
        """
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("TRUNCATE landing.zones")
                with Path(csv_path).open("r", encoding="utf-8", newline="") as handle:
                    cur.copy_expert(
                        "COPY landing.zones (location_id, borough, zone, service_zone) FROM STDIN WITH (FORMAT CSV)",
                        handle,
                    )
                cur.execute("SELECT count(*) AS n FROM landing.zones")
                return int(cur.fetchone()["n"])
        finally:
            conn.close()

    def list_load_log(self) -> list[dict]:
        """List which months are loaded, oldest first.

        Returns:
            One entry per loaded month.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM landing.load_log ORDER BY year, month")
                return [_serialize(row) for row in cur.fetchall()]
        finally:
            conn.close()
