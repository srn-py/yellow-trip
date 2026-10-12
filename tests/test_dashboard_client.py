# tests/test_dashboard_client.py
import httpx
import pytest
from dashboard_app.api_client import AnalyticsApiError, AnalyticsClient, FilterSelection


def make_client(handler):
    return AnalyticsClient("http://analytics", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_selection_params_leave_out_empty_filters():
    assert FilterSelection().to_params() == {}
    selection = FilterSelection("2024-01-01", "2024-01-31", ("Queens", "Bronx"), (1, 2))
    assert selection.to_params() == {
        "start": "2024-01-01",
        "end": "2024-01-31",
        "borough": ["Queens", "Bronx"],
        "payment_type": [1, 2],
    }


def test_get_sends_filters_as_repeated_query_parameters():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"trips": 1})

    client = make_client(handler)
    result = client.get("/kpis", FilterSelection("2024-01-01", None, ("Queens", "Bronx"), ()), {"limit": 5})

    assert result == {"trips": 1}
    assert "borough=Queens" in seen["url"]
    assert "borough=Bronx" in seen["url"]
    assert "limit=5" in seen["url"]
    assert "start=2024-01-01" in seen["url"]


def test_error_status_becomes_a_readable_error_with_the_detail():
    client = make_client(
        lambda request: httpx.Response(503, json={"detail": "The warehouse tables are not built yet."})
    )
    with pytest.raises(AnalyticsApiError, match="not built yet"):
        client.get("/kpis")


def test_unreachable_api_becomes_a_readable_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(AnalyticsApiError, match="Could not reach"):
        make_client(handler).get("/kpis")
