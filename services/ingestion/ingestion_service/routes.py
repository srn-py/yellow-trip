# services/ingestion/ingestion_service/routes.py
"""HTTP endpoints of the ingestion service."""

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from .downloader import DataNotAvailableError, DownloadError
from .file_utils import UnreadableFileError, UnsupportedFormatError, safe_filename
from .ingest import SOURCE_UPLOAD, IngestionService, IngestResult
from .schemas import (
    DownloadResponse,
    FileListResponse,
    FileRecord,
    IngestOutcome,
    TripDownloadRequest,
)

router = APIRouter()


def get_ingestion_service(request: Request) -> IngestionService:
    """Dependency that hands each endpoint the shared IngestionService.

    The service is created once at startup (see main.py) and stored on the app.
    Tests can replace this function to inject a fake.
    """
    return request.app.state.ingestion_service


ServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]

_STATUS_MESSAGES = {
    "duplicate": "Identical file already ingested (same checksum). Nothing to do.",
    "skipped": "Already ingested earlier. Download skipped.",
}


def _outcome(label: str, result: IngestResult) -> IngestOutcome:
    """Convert an internal result into an API response item."""
    record = result.record
    if result.status == "ingested":
        message = f"Stored {record['row_count']} rows at {record['bucket']}/{record['object_key']}."
    else:
        message = _STATUS_MESSAGES[result.status]
    return IngestOutcome(label=label, status=result.status, message=message, file=FileRecord(**record))


@router.post(
    "/ingest/trips/download",
    response_model=DownloadResponse,
    tags=["ingestion"],
    summary="Download one or more months of yellow taxi data from NYC TLC",
)
def download_trips(body: TripDownloadRequest, service: ServiceDep) -> DownloadResponse:
    """Download monthly Parquet files and store them in the raw bucket.

    One bad month never stops the others: each month reports its own status.
    """
    outcomes = []
    for year, month in body.months():
        label = f"{year}-{month:02d}"
        try:
            outcomes.append(_outcome(label, service.ingest_trip_month(year, month)))
        except DataNotAvailableError as exc:
            outcomes.append(IngestOutcome(label=label, status="not_available", message=str(exc)))
        except DownloadError as exc:
            outcomes.append(IngestOutcome(label=label, status="failed", message=str(exc)))
        except (UnsupportedFormatError, UnreadableFileError) as exc:
            outcomes.append(IngestOutcome(label=label, status="rejected", message=str(exc)))
    return DownloadResponse(results=outcomes)


@router.post(
    "/ingest/zones/download",
    response_model=IngestOutcome,
    tags=["ingestion"],
    summary="Download the taxi zone lookup table",
)
def download_zones(service: ServiceDep) -> IngestOutcome:
    """Download the zone lookup CSV (location ID to borough and zone name)."""
    try:
        return _outcome("taxi_zone_lookup", service.ingest_zone_lookup())
    except DownloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (UnsupportedFormatError, UnreadableFileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/ingest/upload",
    response_model=IngestOutcome,
    tags=["ingestion"],
    summary="Upload a data file (Parquet, CSV or NDJSON)",
)
def upload_file(
    service: ServiceDep,
    file: Annotated[UploadFile, File(description="Parquet, CSV, JSON (one object per line)")],
) -> IngestOutcome:
    """Upload a file from your computer into the raw bucket.

    Files named like the official TLC files (`yellow_tripdata_YYYY-MM.parquet`)
    are filed under the matching year/month; anything else goes to `uploads/`.
    """
    filename = file.filename or "upload"
    with tempfile.TemporaryDirectory() as tmp:
        # Save the upload to disk first so we can fingerprint and inspect it.
        dest = Path(tmp) / safe_filename(filename)
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            result = service.ingest_file(dest, filename, SOURCE_UPLOAD)
        except UnsupportedFormatError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except UnreadableFileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _outcome(filename, result)


@router.get(
    "/files",
    response_model=FileListResponse,
    tags=["registry"],
    summary="List files recorded in the file registry",
)
def list_files(
    service: ServiceDep,
    dataset: str | None = Query(None, description="yellow_tripdata | taxi_zone_lookup | uploads"),
    limit: int = Query(100, ge=1, le=1000),
) -> FileListResponse:
    """Show everything that has been ingested (newest first)."""
    records = service.list_files(dataset=dataset, limit=limit)
    return FileListResponse(count=len(records), files=[FileRecord(**r) for r in records])
