<!-- services/explorer/README.md -->
# Explorer service

**Job:** a workbench (JupyterLab) for exploring and profiling the data lake with SQL and charts.

- URL: http://localhost:8888 (token from `JUPYTER_TOKEN` in `.env`, default `taxi`)
- Notebooks: `/notebooks` in the repo (mounted into the container)
- Reusable code: `shared/lake.py` (DuckDB connection) and `shared/profiling.py` (profiling helpers)

This service only **reads** from the lake. It never changes raw data.
