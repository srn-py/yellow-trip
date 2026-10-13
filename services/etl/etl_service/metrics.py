# services/etl/etl_service/metrics.py
"""Pipeline metrics of the ETL service (loading and dbt)."""

from prometheus_client import Counter, Gauge, Histogram

LOADS = Counter("taxi_etl_loads_total", "Load requests by outcome", ["status"])
ROWS_LOADED = Counter("taxi_etl_rows_loaded_total", "Rows loaded into the warehouse")
LOAD_DURATION = Histogram(
    "taxi_etl_load_duration_seconds",
    "Time to load one month",
    buckets=(5, 15, 30, 60, 120, 300, 600, 1200, 3600),
)
LAST_LOAD = Gauge("taxi_etl_last_load_timestamp_seconds", "Unix time of the last successful load")
DBT_RUNS = Counter("taxi_etl_dbt_runs_total", "dbt runs by result", ["result"])
DBT_DURATION = Histogram(
    "taxi_etl_dbt_duration_seconds",
    "Time of a dbt run",
    buckets=(10, 30, 60, 120, 300, 600, 1200, 3600),
)
DBT_LAST_SUCCESS = Gauge("taxi_etl_dbt_last_run_success", "1 if the latest dbt run succeeded, 0 if it failed")


def record_load(status: str, record: dict | None = None) -> None:
    """Record the outcome of loading one month.

    Args:
        status: loaded, skipped, not_cleaned, rejected or failed.
        record: The load log entry (for "loaded").
    """
    LOADS.labels(status).inc()
    if status == "loaded" and record:
        ROWS_LOADED.inc(record.get("rows_loaded") or 0)
        LOAD_DURATION.observe(record.get("duration_seconds") or 0)
        LAST_LOAD.set_to_current_time()


def record_dbt(summary: dict) -> None:
    """Record one dbt run.

    Args:
        summary: The summary returned by the transform runner (`success`, `duration_seconds`).
    """
    success = bool(summary.get("success"))
    DBT_RUNS.labels("success" if success else "failure").inc()
    DBT_DURATION.observe(summary.get("duration_seconds") or 0)
    DBT_LAST_SUCCESS.set(1 if success else 0)
