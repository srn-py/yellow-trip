# services/analytics/analytics_service/database.py
"""Read-only, pooled access to the warehouse.

Two safety nets, both set when a connection is opened:
* `default_transaction_read_only=on`: even a bug (or an attack) cannot change data through this service.
* `statement_timeout`: a runaway query is cancelled after 30 seconds instead of hogging the database.

A *pool* keeps a few connections open and lends them out, because opening a new database connection
for every request is slow.

`psycopg2` is imported inside functions so the rest of the code (and the tests) work without it installed.
"""

import logging
import threading
import time

from shared.config import Settings

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 30_000


class ModelsNotBuiltError(RuntimeError):
    """Raised when a queried table does not exist yet (dbt has not built the models)."""


class Database:
    """A small read-only connection pool for the warehouse."""

    def __init__(self, host: str, port: int, dbname: str, user: str, password: str, pool_size: int = 8):
        self._params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
        }
        self._pool_size = pool_size
        self._pool = None
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        """Create a Database from the application settings.

        Args:
            settings: Application settings (`POSTGRES_*`).

        Returns:
            A configured `Database` (no connection is opened yet).
        """
        return cls(
            settings.postgres_host,
            settings.postgres_port,
            settings.postgres_db,
            settings.postgres_user,
            settings.postgres_password,
        )

    def _get_pool(self):
        """Create the connection pool on first use."""
        import psycopg2.pool

        with self._lock:
            if self._pool is None:
                self._pool = psycopg2.pool.ThreadedConnectionPool(
                    1,
                    self._pool_size,
                    connect_timeout=5,
                    options=f"-c default_transaction_read_only=on -c statement_timeout={STATEMENT_TIMEOUT_MS}",
                    **self._params,
                )
        return self._pool

    def wait_until_ready(self, timeout_seconds: int = 90) -> None:
        """Wait until PostgreSQL accepts connections.

        Args:
            timeout_seconds: Give up (raise) after this many seconds.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                self.query("SELECT 1")
                return
            except Exception as exc:  # Any connection problem means "not ready yet".
                with self._lock:
                    self._pool = None  # start with a fresh pool on the next attempt
                if time.monotonic() >= deadline:
                    raise
                logger.info("Warehouse not ready yet (%s). Retrying...", type(exc).__name__)
                time.sleep(2)

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Run a read-only query and return the rows as dictionaries.

        Args:
            sql: SQL text; values must be passed through `params` (as %s placeholders), never pasted in.
            params: Values for the placeholders.

        Returns:
            One dict per row.

        Raises:
            ModelsNotBuiltError: If a table does not exist yet.
        """
        import psycopg2
        from psycopg2 import errors
        from psycopg2.extras import RealDictCursor

        pool = self._get_pool()
        conn = pool.getconn()
        broken = False
        try:
            conn.autocommit = True  # every statement is its own (read-only) transaction
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params or None)
                return [dict(row) for row in cur.fetchall()]
        except errors.UndefinedTable as exc:
            raise ModelsNotBuiltError(
                "The warehouse tables are not built yet. Run dbt first "
                "(ETL service: POST /transform/run, or the taxi_dbt_rebuild DAG in Airflow)."
            ) from exc
        except psycopg2.OperationalError:
            broken = True  # do not hand a damaged connection to the next request
            raise
        finally:
            pool.putconn(conn, close=broken)

    def is_reachable(self) -> bool:
        """Check that the warehouse answers a trivial query.

        Returns:
            True if the query succeeds.
        """
        try:
            self.query("SELECT 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close every pooled connection (at shutdown)."""
        with self._lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None
