<!-- airflow/README.md -->
# Airflow (orchestration)

**Job:** run the platform's steps in order, on a schedule, with retries, backfills and alerts.
Airflow never handles data itself: it calls each service's API.

| DAG | Schedule | Purpose |
|---|---|---|
| `taxi_month_pipeline` | `@monthly` + manual + backfill | One month: ingest, clean, load, dbt, verify |
| `taxi_dbt_rebuild` | manual | Run dbt on demand |
| `taxi_retry_demo` | manual | Practice retries and failure alerts |

UI: http://localhost:8080 (local only). DAG files are in `dags/`; reusable code is in `dags/taxi_pipeline/`.

| File | Responsibility |
|---|---|
| `taxi_pipeline/months.py` | Which month does a run process? |
| `taxi_pipeline/services.py` | HTTP calls to the ingestion, cleaning and ETL services |
| `taxi_pipeline/alerts.py` | What a failure alert does |
| `.airflowignore` | Keeps Airflow from parsing the helper package as DAGs |
