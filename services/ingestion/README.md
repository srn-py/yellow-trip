<!-- services/ingestion/README.md -->
# Ingestion service

**Job:** get data files into the platform (download from NYC TLC, upload, or drop-folder).

| Milestone | State |
|---|---|
| M0 | Skeleton with `/health` |
| M1 | Download / upload / drop-folder, file registry, raw storage |

Run: `make up` from the repo root, then open http://localhost:8000/docs
Code lives in `ingestion_service/`; shared helpers in `/shared`.
