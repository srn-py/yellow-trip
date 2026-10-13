# tests/test_cleaning_api.py
import pytest
from cleaning_service.routes import get_cleaning_service, router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(cleaning_service):
    """A test app with the cleaning router, wired to fakes (no real storage or network)."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_cleaning_service] = lambda: cleaning_service
    return TestClient(app)


def test_clean_request_reports_each_month_separately(client):
    response = client.post("/clean/trips", json={"start": "2024-01", "end": "2024-02"})
    assert response.status_code == 200
    results = {item["label"]: item for item in response.json()["results"]}
    assert results["2024-01"]["status"] == "cleaned"
    assert "6 quarantined" in results["2024-01"]["message"]
    assert results["2024-02"]["status"] == "not_ingested"  # one bad month does not stop the rest


def test_second_request_is_skipped(client):
    client.post("/clean/trips", json={"start": "2024-01"})
    again = client.post("/clean/trips", json={"start": "2024-01"})
    assert again.json()["results"][0]["status"] == "skipped"


def test_reports_endpoints(client):
    assert client.get("/reports/trips/2024/1").status_code == 404
    client.post("/clean/trips", json={"start": "2024-01"})
    assert client.get("/reports/trips/2024/1").json()["counts"]["rows_in"] == 10
    assert client.get("/reports/trips").json()["count"] == 1


def test_reversed_range_is_rejected(client):
    response = client.post("/clean/trips", json={"start": "2024-05", "end": "2024-01"})
    assert response.status_code == 422
