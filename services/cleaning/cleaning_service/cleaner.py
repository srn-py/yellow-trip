# services/cleaning/cleaning_service/cleaner.py
"""Cleans one month end to end.

Order of work (the order matters!):
 1. Ask the ingestion service for the month's raw file.
 2. Skip the work if this exact file was already cleaned with the same rules.
 3. Download the raw file; run the rules (engine).
 4. Verify the result against the data contract (Pandera).
 5. Reconcile the numbers: nothing may be lost or invented.
 6. ONLY NOW upload the clean file and the quarantine file.
 7. Upload the report LAST. A report in storage therefore always means "this month finished
    successfully". It acts as the commit marker, so a crash half-way leaves no report
    and the month is simply cleaned again next time.
"""

import json
import logging
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from shared.config import Settings

from .contract import build_clean_schema, validate_clean_file
from .engine import EngineResult, run_cleaning
from .rules import RULES_VERSION, thresholds

logger = logging.getLogger(__name__)

DATASET = "yellow_tripdata"
PARQUET_TYPE = "application/vnd.apache.parquet"

# Only one month is cleaned at a time: cleaning is memory-heavy, so concurrent
# requests simply wait their turn.
_JOB_LOCK = threading.Lock()


class SourceNotFoundError(LookupError):
    """The month has not been ingested yet."""


class UnsupportedSourceError(ValueError):
    """The raw file is not in a format the cleaning service handles."""


class ReconciliationError(RuntimeError):
    """Row counts do not add up (rows were lost or invented)."""


@dataclass(frozen=True)
class CleanOutcome:
    """Result of cleaning a month.

    Attributes:
        status: "cleaned" (work done now) or "skipped" (already up to date).
        report: The cleaning report (a JSON-style dict).
    """

    status: str
    report: dict


class CleaningService:
    """Coordinates ingestion lookup, cleaning, verification, upload and reporting."""

    def __init__(self, storage, ingestion_client, settings: Settings):
        self._storage = storage
        self._ingestion = ingestion_client
        self._settings = settings

    # ---- object keys -------------------------------------------------------
    @staticmethod
    def _prefix(year: int, month: int) -> str:
        """Folder-style prefix shared by all outputs of a month."""
        return f"{DATASET}/year={year}/month={month:02d}"

    def clean_key(self, year: int, month: int) -> str:
        """Object key of the clean file (in the clean bucket)."""
        return f"{self._prefix(year, month)}/{DATASET}_{year}-{month:02d}_clean.parquet"

    def quarantine_key(self, year: int, month: int) -> str:
        """Object key of the quarantine file (in the quarantine bucket)."""
        return f"{self._prefix(year, month)}/{DATASET}_{year}-{month:02d}_quarantine.parquet"

    def report_key(self, year: int, month: int) -> str:
        """Object key of the cleaning report (in the clean bucket)."""
        return f"reports/{self._prefix(year, month)}/cleaning_report.json"

    # ---- main entry point --------------------------------------------------
    def clean_month(self, year: int, month: int, force: bool = False) -> CleanOutcome:
        """Clean one month of trips.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.
            force: Clean again even if an up-to-date report exists.

        Returns:
            A `CleanOutcome`.

        Raises:
            SourceNotFoundError: The month was never ingested.
            UnsupportedSourceError: The raw file is not Parquet.
            SchemaMismatchError: A required column is missing (from the engine).
            ContractViolationError: The output broke the data contract.
            ReconciliationError: Row counts do not add up.
        """
        source = self._ingestion.get_trip_file(year, month)
        if source is None:
            raise SourceNotFoundError(f"No raw file for {year}-{month:02d}. Ingest it first (ingestion service).")
        if source["file_format"] != "parquet":
            raise UnsupportedSourceError(
                f"Raw file is {source['file_format']}; only Parquet trip files can be cleaned."
            )

        if not force:
            existing = self.get_report(year, month)
            if existing and self._is_up_to_date(existing, source):
                logger.info("%d-%02d already cleaned with the same source and rules", year, month)
                return CleanOutcome("skipped", existing)

        with _JOB_LOCK:
            report = self._clean(year, month, source)
        return CleanOutcome("cleaned", report)

    def _is_up_to_date(self, report: dict, source: dict) -> bool:
        """Does an existing report match the current source file and rules?"""
        return (
            report.get("source", {}).get("sha256") == source["sha256"]
            and report.get("rules_version") == RULES_VERSION
            and report.get("thresholds") == thresholds(self._settings)
        )

    def _clean(self, year: int, month: int, source: dict) -> dict:
        """Do the actual work for one month (see the module docstring for the order)."""
        started = datetime.now(UTC)
        settings = self._settings
        logger.info("Cleaning %d-%02d from %s", year, month, source["object_key"])

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            raw_path = work / "raw.parquet"
            self._storage.download_file(source["bucket"], source["object_key"], raw_path)

            result = run_cleaning(raw_path, work / "engine", year, month, source["object_key"], settings)

            contract_rows = validate_clean_file(result.clean_path, build_clean_schema(settings))
            self._reconcile(source, result, contract_rows)

            clean_key = self.clean_key(year, month)
            quarantine_key = self.quarantine_key(year, month)
            self._storage.upload_file(settings.bucket_clean, clean_key, result.clean_path, content_type=PARQUET_TYPE)
            self._storage.upload_file(
                settings.bucket_quarantine,
                quarantine_key,
                result.quarantine_path,
                content_type=PARQUET_TYPE,
            )

        finished = datetime.now(UTC)
        report = self._build_report(year, month, source, result, started, finished)
        # Written LAST: the report is the commit marker.
        self._storage.put_bytes(
            settings.bucket_clean,
            self.report_key(year, month),
            json.dumps(report, indent=2).encode("utf-8"),
            content_type="application/json",
        )
        logger.info(
            "Cleaned %d-%02d: %d in, %d clean, %d quarantined",
            year,
            month,
            result.rows_in,
            result.rows_clean,
            result.rows_quarantined,
        )
        return report

    @staticmethod
    def _reconcile(source: dict, result: EngineResult, contract_rows: int) -> None:
        """Prove that rows were neither lost nor invented.

        Raises:
            ReconciliationError: If any of the checks fails.
        """
        quarantine_rows = pq.ParquetFile(result.quarantine_path).metadata.num_rows
        problems = []
        if result.rows_in != result.rows_clean + result.rows_quarantined:
            problems.append("rows_in != rows_clean + rows_quarantined")
        if contract_rows != result.rows_clean:
            problems.append(f"clean file has {contract_rows} rows, expected {result.rows_clean}")
        if quarantine_rows != result.rows_quarantined:
            problems.append(f"quarantine file has {quarantine_rows} rows, expected {result.rows_quarantined}")
        registered = source.get("row_count")
        if registered is not None and registered != result.rows_in:
            problems.append(f"registry says {registered} raw rows, engine read {result.rows_in}")
        if problems:
            raise ReconciliationError("; ".join(problems))

    def _build_report(
        self,
        year: int,
        month: int,
        source: dict,
        result: EngineResult,
        started: datetime,
        finished: datetime,
    ) -> dict:
        """Assemble the cleaning report (JSON-serialisable)."""
        settings = self._settings
        total = result.rows_in

        def pct(part: int) -> float:
            return round(100 * part / total, 3) if total else 0.0

        return {
            "dataset": DATASET,
            "year": year,
            "month": month,
            "status": "ok",
            "rules_version": RULES_VERSION,
            "thresholds": thresholds(settings),
            "source": {
                "bucket": source["bucket"],
                "object_key": source["object_key"],
                "sha256": source["sha256"],
                "file_format": source["file_format"],
                "registry_row_count": source.get("row_count"),
            },
            "counts": {
                "rows_in": total,
                "rows_clean": result.rows_clean,
                "rows_quarantined": result.rows_quarantined,
                "pct_clean": pct(result.rows_clean),
                "pct_quarantined": pct(result.rows_quarantined),
                "reconciled": True,  # we only reach this point if reconciliation passed
            },
            "rule_violations": result.rule_counts,
            "flags_in_clean_data": {
                "has_missing_trip_details": result.clean_rows_with_missing_details,
                "is_zero_passengers": result.clean_rows_zero_passengers,
            },
            "schema": {
                "renamed_columns": result.renamed_columns,
                "columns_filled_with_null": result.columns_filled_with_null,
                "unmapped_source_columns": result.unmapped_columns,
            },
            "outputs": {
                "clean": {
                    "bucket": settings.bucket_clean,
                    "object_key": self.clean_key(year, month),
                    "rows": result.rows_clean,
                },
                "quarantine": {
                    "bucket": settings.bucket_quarantine,
                    "object_key": self.quarantine_key(year, month),
                    "rows": result.rows_quarantined,
                },
            },
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "duration_seconds": round((finished - started).total_seconds(), 1),
        }

    # ---- reading reports -----------------------------------------------------
    def get_report(self, year: int, month: int) -> dict | None:
        """Load the stored cleaning report of a month.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            The report, or None if the month has not been cleaned.
        """
        bucket, key = self._settings.bucket_clean, self.report_key(year, month)
        if not self._storage.object_exists(bucket, key):
            return None
        return json.loads(self._storage.get_bytes(bucket, key))

    def list_reports(self) -> list[dict]:
        """Summarise every stored cleaning report, oldest month first.

        Returns:
            A list of dicts with year, month, row counts and finish time.
        """
        summaries = []
        prefix = f"reports/{DATASET}/"
        for item in self._storage.list_objects(self._settings.bucket_clean, prefix):
            if not item["key"].endswith("cleaning_report.json"):
                continue
            report = json.loads(self._storage.get_bytes(self._settings.bucket_clean, item["key"]))
            summaries.append(
                {
                    "year": report["year"],
                    "month": report["month"],
                    **{
                        key: report["counts"][key]
                        for key in ("rows_in", "rows_clean", "rows_quarantined", "pct_quarantined")
                    },
                    "finished_at": report["finished_at"],
                }
            )
        return sorted(summaries, key=lambda row: (row["year"], row["month"]))
