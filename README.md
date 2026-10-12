<!-- README.md -->
# NYC Yellow Taxi Data Engineering Platform

A learning-oriented data platform built from small containerised services around the
public NYC TLC Yellow Taxi data. It grows milestone by milestone: ingestion, cleaning,
warehouse, orchestration, dashboards, monitoring, deployment.

## Quick start

1. Install **Docker Desktop** (or Docker Engine + Compose v2) and **Python 3.12**.
2. Create your settings file: `cp .env.example .env` (Windows: `copy .env.example .env`)
3. Start the platform: `docker compose up -d --build` (or `make up`)
4. Open http://localhost:8000/docs

## Documentation

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
mkdocs serve -a localhost:8001                         # or: make docs
```

Then open http://localhost:8001. Start with *How to run*, *Architecture* and the
*Milestones* section.