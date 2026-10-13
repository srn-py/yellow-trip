# services/quality/quality_service/sources.py
"""Where the quality checks get their data from.

* The warehouse (read-only): load log and per-month row counts of the fact table.
* The cleaning service API: cleaning reports.
* The ETL service API: the last dbt run.

As everywhere in this platform, other services are reached through their APIs, never their files.
`psycopg2` is imported inside functions so the rest of the code works without it installed.
"""

import httpx

from shared.config import Settings


def _month(year: int, month: int) -> str:
    """Format a month as YYYY-MM."""
    return f"{year}-{month:02d}"


class Warehouse:
    """Read-only access to the warehouse for the checks."""

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

    def _query(self, sql: str) -> list[dict]:
        """Run a read-only query (a new short connection: checks run only every few minutes)."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=120000",
            **self._params,
        )
        try:
            conn.autocommit = True
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def load_log(self) -> list[dict]:
        """The load log: one row per loaded month.

        Returns:
            Dicts with year, month, rows_loaded and loaded_at.
        """
        return self._query("SELECT year, month, rows_loaded, loaded_at FROM landing.load_log ORDER BY year, month")

    def fact_rows_by_month(self) -> dict[str, int]:
        """Rows per month in `analytics.fct_trips`.

        Returns:
            {"2024-01": rows, ...}; empty if dbt has not built the table yet.
        """
        from psycopg2 import errors

        try:
            rows = self._query("SELECT month_key, count(*) AS rows FROM analytics.fct_trips GROUP BY month_key")
        except errors.UndefinedTable:
            return {}
        return {_month(row["month_key"] // 100, row["month_key"] % 100): int(row["rows"]) for row in rows}


class PlatformSources:
    """Everything the monitor needs: the warehouse plus the cleaning and ETL APIs."""

    def __init__(
        self,
        warehouse: Warehouse,
        cleaning_url: str,
        etl_url: str,
        client: httpx.Client | None = None,
    ):
        self._warehouse = warehouse
        self._cleaning_url = cleaning_url.rstrip("/")
        self._etl_url = etl_url.rstrip("/")
        self._client = client or httpx.Client(timeout=60.0)

    def load_log(self) -> list[dict]:
        """See `Warehouse.load_log`."""
        return self._warehouse.load_log()

    def fact_rows_by_month(self) -> dict[str, int]:
        """See `Warehouse.fact_rows_by_month`."""
        return self._warehouse.fact_rows_by_month()

    def cleaning_summaries(self) -> list[dict]:
        """One summary line per cleaned month (rows and quarantine percentage).

        Returns:
            Dicts with year, month, rows_in, rows_clean, rows_quarantined, pct_quarantined.
        """
        response = self._client.get(f"{self._cleaning_url}/reports/trips")
        response.raise_for_status()
        return response.json()["reports"]

    def cleaning_reports(self) -> list[dict]:
        """The full cleaning report of every cleaned month.

        Returns:
            One report per month.
        """
        reports = []
        for summary in self.cleaning_summaries():
            response = self._client.get(f"{self._cleaning_url}/reports/trips/{summary['year']}/{summary['month']}")
            response.raise_for_status()
            reports.append(response.json())
        return reports

    def dbt_last_run(self) -> dict | None:
        """The summary of the latest dbt run.

        Returns:
            The summary, or None if dbt has not run yet.
        """
        response = self._client.get(f"{self._etl_url}/transform/last-run")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
