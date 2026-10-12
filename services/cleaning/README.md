<!-- services/cleaning/README.md -->
# Cleaning service

**Job:** turn one month of raw trips into trustworthy data. For each month it writes a **clean**
file, a **quarantine** file (rejected rows plus the reasons) and a **cleaning report**.

| Endpoint | Purpose |
|---|---|
| `POST /clean/trips` | Body `{"start":"2024-01","end":"2024-03","force":false}` |
| `GET /reports/trips` | Summary of every cleaning report |
| `GET /reports/trips/{year}/{month}` | Full report for one month |
| `GET /health`, `GET /health/ready` | Liveness / readiness |

Interactive docs: http://localhost:8100/docs

## Code map (`cleaning_service/`)

| File | Responsibility |
|---|---|
| `rules.py` | The validation rules and thresholds |
| `sql_builder.py` | Column mapping and SQL generation |
| `engine.py` | Runs the rules in DuckDB; writes clean and quarantine files |
| `contract.py` | Pandera data contract on the cleaned output |
| `cleaner.py` | One month, end to end: fetch, clean, verify, reconcile, upload, report |
| `ingestion_client.py` | Asks the ingestion API which file belongs to a month |
| `routes.py`, `schemas.py`, `main.py` | HTTP layer |