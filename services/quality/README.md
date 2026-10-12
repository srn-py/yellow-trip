<!-- services/quality/README.md -->
# Data quality service

**Job:** keep asking "is the data still healthy?" and make the answer visible: as an API, as
Prometheus metrics (which Grafana draws and alert rules watch), and as a gate at the end of the Airflow pipeline.

Every `QUALITY_INTERVAL_SECONDS` (default 5 minutes) it runs six checks:

| Check | Fails or warns when |
|---|---|
| `freshness` | nothing was loaded for more than `QUALITY_MAX_LOAD_AGE_DAYS` days |
| `row_counts` | a month's rows differ a lot from the median of the other months (warn at the tolerance, fail at twice) |
| `quarantine_rate` | a month quarantined more than `QUALITY_MAX_QUARANTINE_PCT` percent |
| `schema_drift` | a raw file has columns the cleaning service does not know (they would be ignored silently) |
| `row_reconciliation` | cleaning, the landing table and `fct_trips` disagree on a month's row count |
| `dbt_last_run` | the last dbt run failed, or dbt has not run for too long |

| Endpoint | Purpose |
|---|---|
| `POST /checks/run` | Run all checks now and return the result |
| `GET /checks/latest` | The result of the most recent run |
| `GET /metrics` | Prometheus metrics (`taxi_quality_check_status{check}`: 0 fail, 1 warn, 2 ok) |
| `GET /health`, `GET /health/ready` | Liveness / readiness |

Interactive docs: http://localhost:8400/docs

| File | Responsibility |
|---|---|
| `checks.py` | The checks themselves: pure functions, no I/O |
| `monitor.py` | Gathers data, runs the checks, keeps the latest result |
| `sources.py` | Where the data comes from (warehouse, cleaning API, ETL API) |
| `metrics.py` | Prometheus gauges |
| `settings.py` | Thresholds from environment variables |
| `routes.py`, `main.py` | HTTP layer and start-up (including the background loop) |