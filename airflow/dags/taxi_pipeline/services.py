# airflow/dags/taxi_pipeline/services.py
"""Talks to the platform's services over HTTP, for use inside Airflow tasks.

Airflow never touches the data lake or the warehouse directly. It asks each service to do its
job through that service's API. This is decision 001 in action: services are independent, and
the orchestrator only decides *order, timing and retries*.

Every step is safe to repeat (the services are idempotent), which is what makes Airflow's
automatic retries and manual re-runs harmless.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# How long we are willing to wait for each kind of call (seconds).
QUICK_TIMEOUT = 60.0
READY_TIMEOUT = 10.0
INGEST_TIMEOUT = 1200.0
CLEAN_TIMEOUT = 3600.0
LOAD_TIMEOUT = 3600.0
DBT_TIMEOUT = 3900.0
QUALITY_TIMEOUT = 300.0

# Service statuses that mean "this step is done" (skipped = there was nothing left to do).
_INGEST_OK = {"ingested", "skipped", "duplicate"}
_CLEAN_OK = {"cleaned", "skipped"}
_LOAD_OK = {"loaded", "skipped"}


class StepError(RuntimeError):
    """A pipeline step failed. The message is written for humans reading the task log."""


class MonthNotAvailableError(StepError):
    """TLC has not published the requested month yet (not a real failure)."""


def _dbt_failure_message(payload: dict) -> str:
    """Build a readable message from a failed dbt run."""
    problems = (payload.get("results") or {}).get("problems") or []
    if problems:
        shown = [
            f"{item.get('node')}: {item.get('status')} {str(item.get('message') or '')[:200]}" for item in problems[:5]
        ]
        return "dbt reported problems: " + " | ".join(shown)
    tail = payload.get("log_tail") or []
    return "dbt failed: " + " / ".join(tail[-5:])


class PlatformApi:
    """One object that knows how to call the ingestion, cleaning and ETL services."""

    def __init__(
        self,
        ingestion_url: str,
        cleaning_url: str,
        etl_url: str,
        client: httpx.Client | None = None,
        quality_url: str | None = None,
    ):
        self._urls = {
            "ingestion": ingestion_url.rstrip("/"),
            "cleaning": cleaning_url.rstrip("/"),
            "etl": etl_url.rstrip("/"),
        }
        # Optional: monitoring being down must never block the data pipeline itself.
        self._optional_urls = {"quality": quality_url.rstrip("/")} if quality_url else {}
        self._client = client or httpx.Client()

    @classmethod
    def from_env(cls) -> "PlatformApi":
        """Create the client from environment variables (set in docker-compose.yml).

        Returns:
            A configured `PlatformApi`.
        """
        return cls(
            os.environ.get("INGESTION_URL", "http://ingestion:8000"),
            os.environ.get("CLEANING_URL", "http://cleaning:8000"),
            os.environ.get("ETL_URL", "http://etl:8000"),
            quality_url=os.environ.get("QUALITY_URL", "http://quality:8000"),
        )

    def _request(
        self,
        method: str,
        service: str,
        path: str,
        *,
        json: dict | None = None,
        timeout: float = QUICK_TIMEOUT,
    ) -> dict:
        """Send one request and return the JSON answer, turning every failure into a StepError."""
        base = self._urls.get(service) or self._optional_urls.get(service)
        if base is None:
            raise StepError(f"The {service} service is not configured.")
        url = f"{base}{path}"
        try:
            response = self._client.request(method, url, json=json, timeout=timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise StepError(
                f"{service} answered HTTP {exc.response.status_code} for {method} {path}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise StepError(f"Could not reach {service} ({method} {path}): {exc!r}") from exc
        return response.json()

    @staticmethod
    def _first_result(payload: dict, what: str) -> dict:
        """Take the single month result out of a service answer."""
        results = payload.get("results") or []
        if not results:
            raise StepError(f"{what}: the service returned no result.")
        return results[0]

    # ---- steps -------------------------------------------------------------------
    def wait_ready(self) -> None:
        """Check that every service reports itself ready.

        Raises:
            StepError: Listing every service that is not ready.
        """
        problems = []
        for name, base in self._urls.items():
            try:
                self._client.get(f"{base}/health/ready", timeout=READY_TIMEOUT).raise_for_status()
            except httpx.HTTPError as exc:
                problems.append(f"{name} ({base}): {exc!r}")
        if problems:
            raise StepError("Services not ready: " + "; ".join(problems))

    def ensure_zones(self) -> dict:
        """Make sure the zone lookup table is ingested and loaded into the warehouse.

        Returns:
            A small summary.
        """
        ingest = self._request("POST", "ingestion", "/ingest/zones/download", timeout=INGEST_TIMEOUT)
        load = self._request("POST", "etl", "/load/zones", timeout=LOAD_TIMEOUT)
        return {"zone_file_status": ingest.get("status"), "zones_loaded": load.get("rows_loaded")}

    def ingest_month(self, year: int, month: int) -> dict:
        """Download one month from TLC into the raw bucket (or confirm it is already there).

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            The service's result item.

        Raises:
            MonthNotAvailableError: TLC has not published the month.
            StepError: Any other failure.
        """
        label = f"{year}-{month:02d}"
        payload = self._request(
            "POST",
            "ingestion",
            "/ingest/trips/download",
            json={"start": label},
            timeout=INGEST_TIMEOUT,
        )
        item = self._first_result(payload, f"Ingesting {label}")
        status = item.get("status")
        if status in _INGEST_OK:
            return item
        if status == "not_available":
            raise MonthNotAvailableError(item.get("message", "not available"))
        raise StepError(f"Ingesting {label} ended with status '{status}': {item.get('message')}")

    def clean_month(self, year: int, month: int, force: bool = False) -> dict:
        """Clean one month (raw to clean and quarantine).

        Args:
            year: Four-digit year.
            month: Month 1 to 12.
            force: Clean again even if already up to date.

        Returns:
            The service's result item (includes the cleaning report).

        Raises:
            StepError: If the month could not be cleaned.
        """
        label = f"{year}-{month:02d}"
        payload = self._request(
            "POST",
            "cleaning",
            "/clean/trips",
            json={"start": label, "force": force},
            timeout=CLEAN_TIMEOUT,
        )
        item = self._first_result(payload, f"Cleaning {label}")
        if item.get("status") in _CLEAN_OK:
            return item
        raise StepError(f"Cleaning {label} ended with status '{item.get('status')}': {item.get('message')}")

    def load_month(self, year: int, month: int, force: bool = False) -> dict:
        """Load one cleaned month into the warehouse's landing table.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.
            force: Load again even if already loaded from the same cleaning run.

        Returns:
            The service's result item (includes the load log entry).

        Raises:
            StepError: If the month could not be loaded.
        """
        label = f"{year}-{month:02d}"
        payload = self._request(
            "POST",
            "etl",
            "/load/trips",
            json={"start": label, "force": force},
            timeout=LOAD_TIMEOUT,
        )
        item = self._first_result(payload, f"Loading {label}")
        if item.get("status") in _LOAD_OK:
            return item
        raise StepError(f"Loading {label} ended with status '{item.get('status')}': {item.get('message')}")

    def run_dbt(self, command: str = "build", select: str | None = None, full_refresh: bool = False) -> dict:
        """Run dbt through the ETL service.

        Args:
            command: One of build, run, test, seed.
            select: Optional dbt node selector.
            full_refresh: Rebuild incremental models from scratch.

        Returns:
            A short summary (counts per status and duration).

        Raises:
            StepError: If dbt reports any error or failing test.
        """
        body = {"command": command, "select": select or None, "full_refresh": full_refresh}
        payload = self._request("POST", "etl", "/transform/run", json=body, timeout=DBT_TIMEOUT)
        if not payload.get("success"):
            raise StepError(_dbt_failure_message(payload))
        results = payload.get("results") or {}
        return {
            "counts": results.get("counts"),
            "duration_seconds": payload.get("duration_seconds"),
        }

    def verify_month(self, year: int, month: int) -> dict:
        """Cross-check two services: rows the cleaning service published = rows the warehouse loaded.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            A dict with both numbers.

        Raises:
            StepError: If the month is missing or the numbers differ.
        """
        label = f"{year}-{month:02d}"
        report = self._request("GET", "cleaning", f"/reports/trips/{year}/{month}")
        status = self._request("GET", "etl", "/load/status")
        entry = next(
            (row for row in status.get("months", []) if row["year"] == year and row["month"] == month),
            None,
        )
        if entry is None:
            raise StepError(f"{label} is not in the warehouse load log.")
        expected = report["counts"]["rows_clean"]
        loaded = entry["rows_loaded"]
        if expected != loaded:
            raise StepError(f"{label}: cleaning published {expected} rows but the warehouse loaded {loaded}.")
        return {"label": label, "rows_clean": expected, "rows_loaded": loaded}

    def run_quality_checks(self) -> dict:
        """Ask the quality service to run all data-quality checks now.

        Returns:
            The overall status and the names of any checks that only warn.

        Raises:
            StepError: If any check fails.
        """
        payload = self._request("POST", "quality", "/checks/run", timeout=QUALITY_TIMEOUT)
        checks = payload.get("checks", [])
        failing = [check for check in checks if check.get("status") == "fail"]
        if failing:
            raise StepError(
                "Data quality checks failed: " + " | ".join(f"{check['name']}: {check['message']}" for check in failing)
            )
        return {
            "status": payload.get("status"),
            "warnings": [check["name"] for check in checks if check.get("status") == "warn"],
        }
