# services/cleaning/cleaning_service/ingestion_client.py
"""A small client for the ingestion service's HTTP API.

Services never open each other's databases. The cleaning service asks the ingestion
service (`GET /files`) which raw file belongs to a month. That keeps the services
independent: ingestion could change how it stores its registry and nothing here breaks.
"""

import httpx

DATASET_TRIPS = "yellow_tripdata"


class IngestionClient:
    """Calls the ingestion service over HTTP."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def get_trip_file(self, year: int, month: int) -> dict | None:
        """Find the registry record of the raw trip file for a month.

        If several files exist for the month, Parquet is preferred and then the newest.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            The registry record (a dict), or None if that month was never ingested.
        """
        response = httpx.get(
            f"{self._base_url}/files",
            params={"dataset": DATASET_TRIPS, "limit": 1000},
            timeout=self._timeout,
        )
        response.raise_for_status()
        matches = [
            record for record in response.json()["files"] if record.get("year") == year and record.get("month") == month
        ]
        parquet = [record for record in matches if record["file_format"] == "parquet"]
        candidates = parquet or matches
        return max(candidates, key=lambda record: record["id"]) if candidates else None

    def is_reachable(self) -> bool:
        """Check that the ingestion service answers.

        Returns:
            True if its health endpoint responds.
        """
        try:
            httpx.get(f"{self._base_url}/health", timeout=5.0).raise_for_status()
            return True
        except httpx.HTTPError:
            return False
