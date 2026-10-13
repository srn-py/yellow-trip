# services/dashboard/dashboard_app/api_client.py
"""A small client for the analytics API.

The dashboard never connects to a database. Everything it shows comes through this client, so the
API is the single, tested place that knows how to ask the warehouse questions.
"""

from dataclasses import dataclass

import httpx


class AnalyticsApiError(RuntimeError):
    """The analytics API could not answer. The message is written for the dashboard user."""


@dataclass(frozen=True)
class FilterSelection:
    """The filters chosen in the sidebar.

    Attributes:
        start: First pickup date as YYYY-MM-DD, or None.
        end: Last pickup date as YYYY-MM-DD, or None.
        boroughs: Pickup boroughs (empty = all).
        payment_types: Payment type IDs (empty = all).
    """

    start: str | None = None
    end: str | None = None
    boroughs: tuple[str, ...] = ()
    payment_types: tuple[int, ...] = ()

    def to_params(self) -> dict:
        """Convert the selection into query-string parameters, leaving out empty filters.

        Returns:
            A dict suitable for an HTTP query string (lists become repeated parameters).
        """
        params: dict = {}
        if self.start:
            params["start"] = self.start
        if self.end:
            params["end"] = self.end
        if self.boroughs:
            params["borough"] = list(self.boroughs)
        if self.payment_types:
            params["payment_type"] = list(self.payment_types)
        return params


class AnalyticsClient:
    """Talks to the analytics API over HTTP."""

    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client()
        self._timeout = timeout

    def get(self, path: str, selection: FilterSelection | None = None, extra: dict | None = None):
        """Call an endpoint and return its JSON answer.

        Args:
            path: Endpoint path such as "/kpis".
            selection: Sidebar filters to send.
            extra: Additional query parameters (for example `{"limit": 10}`).

        Returns:
            The decoded JSON (a dict or a list).

        Raises:
            AnalyticsApiError: If the API is unreachable or answers with an error.
        """
        params = {**(selection.to_params() if selection else {}), **(extra or {})}
        try:
            response = self._client.get(f"{self._base_url}{path}", params=params, timeout=self._timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _detail(exc.response)
            raise AnalyticsApiError(
                f"The analytics API answered {exc.response.status_code} for {path}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AnalyticsApiError(f"Could not reach the analytics API ({path}): {exc!r}") from exc
        return response.json()


def _detail(response: httpx.Response) -> str:
    """Extract the human-readable `detail` message from an error answer."""
    try:
        return str(response.json().get("detail", response.text))[:300]
    except (ValueError, AttributeError):
        return response.text[:300]
