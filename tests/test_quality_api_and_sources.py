# tests/test_quality_api_and_sources.py
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quality_service.routes import get_monitor, router
from quality_service.sources import PlatformSources


class FakeMonitor:
    def __init__(self):
        self.report = None

    def run_checks(self):
        self.report = {"status": "ok", "ran_at": "now", "checks": []}
        return self.report

    def latest(self):
        return self.report


@pytest.fixture
def monitor():
    return FakeMonitor()


@pytest.fixture
def client(monitor):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_monitor] = lambda: monitor
    return TestClient(app)


def test_latest_is_404_until_a_run_has_finished(client):
    assert client.get("/checks/latest").status_code == 404
    assert client.post("/checks/run").json()["status"] == "ok"
    assert client.get("/checks/latest").json()["status"] == "ok"


def make_sources(handler) -> PlatformSources:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PlatformSources(warehouse=None, cleaning_url="http://cleaning", etl_url="http://etl", client=client)


def test_cleaning_reports_are_fetched_one_by_one_from_the_summary_list():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/reports/trips":
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "reports": [{"year": 2024, "month": 1}, {"year": 2024, "month": 2}],
                },
            )
        return httpx.Response(200, json={"year": 2024, "month": int(request.url.path.rsplit("/", 1)[-1])})

    reports = make_sources(handler).cleaning_reports()
    assert [report["month"] for report in reports] == [1, 2]
    assert seen == ["/reports/trips", "/reports/trips/2024/1", "/reports/trips/2024/2"]


def test_dbt_last_run_is_none_when_dbt_has_not_run():
    sources = make_sources(lambda request: httpx.Response(404, json={"detail": "dbt has not run yet"}))
    assert sources.dbt_last_run() is None


def test_dbt_last_run_returns_the_summary():
    sources = make_sources(lambda request: httpx.Response(200, json={"success": True}))
    assert sources.dbt_last_run() == {"success": True}
