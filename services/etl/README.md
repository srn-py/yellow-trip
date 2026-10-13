<!-- services/etl/README.md -->
# ETL service

**Job:** load clean data into the PostgreSQL warehouse, then transform it with dbt into a star schema.

| Endpoint | Purpose |
|---|---|
| `POST /load/trips` | Body `{"start":"2024-01","end":"2024-03","force":false}`: clean files into `landing.trips` |
| `POST /load/zones` | Zone lookup into `landing.zones` |
| `GET /load/status` | Which months are loaded |
| `POST /transform/run` | Run dbt: `{"command":"build","select":null,"full_refresh":false}` |
| `POST /transform/docs` | Generate the dbt documentation site |
| `GET /transform/last-run` | Summary of the most recent dbt run |
| `/dbt-docs/` | The dbt documentation site (lineage graph) |
| `GET /health`, `GET /health/ready` | Liveness / readiness |

Interactive docs: http://localhost:8200/docs

## Code map (`etl_service/`)

| File | Responsibility |
|---|---|
| `landing.py` | Definition of the landing tables; the column contract |
| `export.py` | Parquet/CSV to bulk-load CSV, using DuckDB |
| `warehouse.py` | PostgreSQL access: load in a transaction, load log |
| `loader.py` | One month end to end: report, download, convert, load, verify |
| `clients.py` | HTTP clients for the cleaning and ingestion APIs |
| `transform.py` | Runs dbt safely and summarises the result |
| `schemas.py`, `routes.py`, `main.py` | HTTP layer |
