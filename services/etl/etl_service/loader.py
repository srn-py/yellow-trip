# services/etl/etl_service/loader.py
"""Loads clean data from the lake into the warehouse's landing schema.

Order of work for one month:
 1. Ask the cleaning service for the month's report (it says where the clean file is and how
    many rows it must contain). No report means the month was never cleaned.
 2. Skip if this exact cleaning run is already loaded (idempotent).
 3. Download the clean Parquet file and convert it to CSV (DuckDB).
 4. Check the converted row count against the report.
 5. Replace the month in PostgreSQL in one transaction, which checks the count again.
"""

import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from shared.config import Settings

from .export import parquet_to_csv, zones_to_csv
from .warehouse import LoadMismatchError

logger = logging.getLogger(__name__)

# One load at a time. Loads are heavy, and dbt's incremental logic relies on loads being
# committed one after another (see decision 004).
_JOB_LOCK = threading.Lock()


class NotCleanedError(LookupError):
    """The month has no cleaning report yet."""


class ZoneFileNotFoundError(LookupError):
    """The zone lookup file has not been ingested."""


@dataclass(frozen=True)
class LoadOutcome:
    """Result of a load.

    Attributes:
        status: "loaded" (work done now) or "skipped" (already up to date).
        record: The load log entry (or a small summary for zones).
    """

    status: str
    record: dict


class LoaderService:
    """Coordinates the cleaning API, the lake and the warehouse."""

    def __init__(self, storage, cleaning_client, ingestion_client, warehouse, settings: Settings):
        self._storage = storage
        self._cleaning = cleaning_client
        self._ingestion = ingestion_client
        self._warehouse = warehouse
        self._settings = settings

    def load_month(self, year: int, month: int, force: bool = False) -> LoadOutcome:
        """Load one cleaned month into `landing.trips`.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.
            force: Load again even if this cleaning run is already loaded.

        Returns:
            A `LoadOutcome`.

        Raises:
            NotCleanedError: The month has no cleaning report.
            SchemaContractError: The clean file's columns do not match the landing table.
            LoadMismatchError: Row counts do not add up (nothing was changed).
        """
        report = self._cleaning.get_report(year, month)
        if report is None:
            raise NotCleanedError(f"No cleaning report for {year}-{month:02d}. Clean it first (cleaning service).")

        cleaned_at = report["finished_at"]
        existing = self._warehouse.get_month_log(year, month)
        if existing and not force and existing["cleaned_at"] == cleaned_at:
            logger.info("%d-%02d already loaded from the same cleaning run", year, month)
            return LoadOutcome("skipped", existing)

        clean = report["outputs"]["clean"]
        expected = int(report["counts"]["rows_clean"])

        with _JOB_LOCK:
            started = time.monotonic()
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                parquet_path = work / "clean.parquet"
                csv_path = work / "trips.csv"

                self._storage.download_file(clean["bucket"], clean["object_key"], parquet_path)
                exported = parquet_to_csv(parquet_path, csv_path, self._settings.duckdb_memory_limit)
                if exported != expected:
                    raise LoadMismatchError(
                        f"{year}-{month:02d}: clean file has {exported} rows but the report says {expected}."
                    )
                record = self._warehouse.replace_month(
                    year,
                    month,
                    csv_path,
                    expected,
                    cleaned_at,
                    clean["object_key"],
                    round(time.monotonic() - started, 1),
                )
        logger.info("Loaded %d-%02d: %d rows", year, month, expected)
        return LoadOutcome("loaded", record)

    def load_zones(self) -> LoadOutcome:
        """Load the taxi zone lookup table into `landing.zones` (it is small, so always reloaded).

        Returns:
            A `LoadOutcome` whose record has the number of zones loaded.

        Raises:
            ZoneFileNotFoundError: The zone lookup file has not been ingested.
        """
        record = self._ingestion.get_zone_lookup_file()
        if record is None:
            raise ZoneFileNotFoundError(
                "Zone lookup not ingested. Run POST /ingest/zones/download on the ingestion service first."
            )
        with _JOB_LOCK, tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            raw_path = work / "zones.csv"
            csv_path = work / "zones_load.csv"
            self._storage.download_file(record["bucket"], record["object_key"], raw_path)
            zones_to_csv(raw_path, csv_path)
            rows = self._warehouse.replace_zones(csv_path)
        logger.info("Loaded %d zones", rows)
        return LoadOutcome("loaded", {"rows_loaded": rows, "source": record["object_key"]})
