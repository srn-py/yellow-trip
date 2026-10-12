# services/etl/etl_service/clients.py
"""Small HTTP clients for the services the ETL service depends on.

As before, services only talk to each other through APIs, never through each other's files
or databases.
"""

import httpx


class CleaningClient:
    """Calls the cleaning service."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def get_report(self, year: int, month: int) -> dict | None:
        """Fetch the cleaning report of a month.

        Args:
            year: Four-digit year.
            month: Month 1 to 12.

        Returns:
            The report, or None if the month has not been cleaned.
        """
        response = httpx.get(f"{self._base_url}/reports/trips/{year}/{month}", timeout=self._timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def is_reachable(self) -> bool:
        """Check that the cleaning service answers.

        Returns:
            True if its health endpoint responds.
        """
        try:
            httpx.get(f"{self._base_url}/health", timeout=5.0).raise_for_status()
            return True
        except httpx.HTTPError:
            return False


class IngestionClient:
    """Calls the ingestion service."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def get_zone_lookup_file(self) -> dict | None:
        """Find the registry record of the ingested zone lookup file.

        Returns:
            The registry record, or None if it was never ingested.
        """
        response = httpx.get(
            f"{self._base_url}/files",
            params={"dataset": "taxi_zone_lookup", "limit": 1},
            timeout=self._timeout,
        )
        response.raise_for_status()
        files = response.json()["files"]
        return files[0] if files else None

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
