# services/ingestion/ingestion_service/ingest.py
"""The heart of the ingestion service: take a file, check it, store it, record it.

Every way of getting data in (TLC download, API upload, drop folder) ends up in
`IngestionService.ingest_file`, so all of them follow identical rules:

1. Fingerprint the file (SHA-256). Already seen? Stop: it is a duplicate.
2. Check it is readable and count its rows.
3. Decide where it belongs in the raw bucket.
4. Upload it untouched.
5. Write a registry record.

Running the same ingestion twice is therefore harmless (it is *idempotent*).
"""

import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.config import Settings

from .downloader import build_trip_filename, build_trip_url, download_to_file
from .file_utils import (
    CONTENT_TYPES,
    count_rows,
    detect_format,
    parse_trip_filename,
    safe_filename,
    sha256_of_file,
)
from .metrics import record_ingest
from .registry import FileRegistry
from .storage import ObjectStorage

logger = logging.getLogger(__name__)

# Dataset names (stored in the registry)
DATASET_TRIPS = "yellow_tripdata"
DATASET_ZONES = "taxi_zone_lookup"
DATASET_UPLOADS = "uploads"

# Where a file came from (stored in the registry)
SOURCE_TLC = "tlc_download"
SOURCE_UPLOAD = "upload"
SOURCE_DROPZONE = "dropzone"


@dataclass(frozen=True)
class IngestResult:
    """Outcome of one ingestion attempt.

    Attributes:
        status: "ingested" (new file stored), "duplicate" (identical content already
            present) or "skipped" (that month was already ingested; no download made).
        record: The registry record of the file.
    """

    status: str
    record: dict


class IngestionService:
    """Coordinates storage, registry and downloading."""

    def __init__(self, storage: ObjectStorage, registry: FileRegistry, settings: Settings):
        self._storage = storage
        self._registry = registry
        self._settings = settings

    def ingest_file(self, local_path: Path, original_name: str, source: str) -> IngestResult:
        """Validate, store and register one local file.

        Args:
            local_path: Where the file currently is on local disk.
            original_name: Its original file name (decides format and destination).
            source: Where it came from (SOURCE_* constants).

        Returns:
            An `IngestResult`.

        Raises:
            UnsupportedFormatError: Extension not supported.
            UnreadableFileError: File is corrupt/invalid for its format.
        """
        name = safe_filename(original_name)
        file_format = detect_format(name)

        checksum = sha256_of_file(local_path)
        existing = self._registry.find_by_checksum(checksum)
        if existing:
            logger.info("Duplicate content, skipping: %s", name)
            record_ingest("duplicate", source)
            return IngestResult("duplicate", existing)

        row_count = count_rows(local_path, file_format)
        dataset, year, month, key = self._destination(name, checksum)

        self._storage.upload_file(
            self._settings.bucket_raw,
            key,
            local_path,
            content_type=CONTENT_TYPES[file_format],
            metadata={"sha256": checksum, "source": source},
        )
        record = self._registry.add(
            {
                "sha256": checksum,
                "filename": name,
                "dataset": dataset,
                "file_format": file_format,
                "source": source,
                "bucket": self._settings.bucket_raw,
                "object_key": key,
                "size_bytes": local_path.stat().st_size,
                "row_count": row_count,
                "year": year,
                "month": month,
            }
        )
        logger.info("Ingested %s -> %s/%s (%d rows)", name, record["bucket"], key, row_count)
        record_ingest("ingested", source, rows=row_count, size_bytes=record["size_bytes"])
        return IngestResult("ingested", record)

    def ingest_trip_month(self, year: int, month: int) -> IngestResult:
        """Download one month of yellow taxi data from TLC and ingest it.

        If the month is already registered, nothing is downloaded.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            An `IngestResult` ("skipped" if already present).
        """
        existing = self._registry.find_by_period(DATASET_TRIPS, year, month)
        if existing:
            return IngestResult("skipped", existing)

        filename = build_trip_filename(year, month)
        url = build_trip_url(self._settings.tlc_base_url, year, month)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / filename
            download_to_file(url, dest, max_retries=self._settings.download_max_retries)
            return self.ingest_file(dest, filename, SOURCE_TLC)

    def ingest_zone_lookup(self) -> IngestResult:
        """Download the taxi zone lookup CSV (zone IDs to borough/zone names).

        Returns:
            An `IngestResult` ("skipped" if we already have one).
        """
        existing = self._registry.list_files(dataset=DATASET_ZONES, limit=1)
        if existing:
            return IngestResult("skipped", existing[0])

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "taxi_zone_lookup.csv"
            download_to_file(
                self._settings.tlc_zone_lookup_url,
                dest,
                max_retries=self._settings.download_max_retries,
            )
            return self.ingest_file(dest, dest.name, SOURCE_TLC)

    def list_files(self, dataset: str | None = None, limit: int = 100) -> list[dict]:
        """List registered files (delegates to the registry).

        Args:
            dataset: Optional dataset filter.
            limit: Maximum number of records.

        Returns:
            Registry records, newest first.
        """
        return self._registry.list_files(dataset=dataset, limit=limit)

    @staticmethod
    def _destination(name: str, checksum: str) -> tuple[str, int | None, int | None, str]:
        """Decide dataset and object key for a file.

        Layout inside the raw bucket:
            yellow_tripdata/year=2024/month=01/<file>   (official TLC trip files)
            reference/taxi_zone_lookup.csv              (zone lookup)
            uploads/<YYYYMMDD>/<checksum8>_<file>       (anything else)

        The `year=.../month=...` folder style is called Hive partitioning; query
        engines such as DuckDB and Spark understand it and can skip irrelevant months.

        Args:
            name: Sanitised file name.
            checksum: The file's SHA-256.

        Returns:
            (dataset, year, month, object_key).
        """
        period = parse_trip_filename(name)
        if period:
            year, month = period
            return (
                DATASET_TRIPS,
                year,
                month,
                f"{DATASET_TRIPS}/year={year}/month={month:02d}/{name}",
            )
        if name.lower().startswith("taxi_zone_lookup"):
            return DATASET_ZONES, None, None, f"reference/{name}"
        today = datetime.now(UTC).strftime("%Y%m%d")
        return DATASET_UPLOADS, None, None, f"uploads/{today}/{checksum[:8]}_{name}"
