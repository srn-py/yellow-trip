# services/ingestion/ingestion_service/metrics.py
"""Pipeline metrics of the ingestion service."""

from prometheus_client import Counter

INGEST_FILES = Counter("taxi_ingest_files_total", "Files seen by ingestion", ["status", "source"])
INGEST_ROWS = Counter("taxi_ingest_rows_total", "Rows in newly ingested files")
INGEST_BYTES = Counter("taxi_ingest_bytes_total", "Bytes of newly ingested files")


def record_ingest(status: str, source: str, rows: int | None = None, size_bytes: int | None = None) -> None:
    """Count one ingested or duplicate file.

    Args:
        status: "ingested" or "duplicate".
        source: Where the file came from (tlc_download, upload, dropzone).
        rows: Row count of a newly ingested file.
        size_bytes: Size of a newly ingested file.
    """
    INGEST_FILES.labels(status, source).inc()
    if status == "ingested":
        INGEST_ROWS.inc(rows or 0)
        INGEST_BYTES.inc(size_bytes or 0)
