# tests/test_ingestion_api.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ingestion_service.routes import get_ingestion_service, router


@pytest.fixture
def client(service):
    """A test app with our router, wired to the in-memory fakes (no real storage)."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_ingestion_service] = lambda: service
    return TestClient(app)


def _csv_upload(content: bytes = b"a,b\n1,2\n"):
    return {"file": ("rides.csv", content, "text/csv")}


def test_upload_csv_is_ingested_then_detected_as_duplicate(client):
    first = client.post("/ingest/upload", files=_csv_upload())
    assert first.status_code == 200
    assert first.json()["status"] == "ingested"
    assert first.json()["file"]["row_count"] == 1

    second = client.post("/ingest/upload", files=_csv_upload())
    assert second.json()["status"] == "duplicate"


def test_upload_unsupported_type_returns_415(client):
    response = client.post("/ingest/upload", files={"file": ("a.xlsx", b"x", "application/x")})
    assert response.status_code == 415


def test_files_endpoint_lists_uploaded_files(client):
    client.post("/ingest/upload", files=_csv_upload())
    body = client.get("/files").json()
    assert body["count"] == 1
    assert body["files"][0]["filename"] == "rides.csv"


def test_download_request_rejects_reversed_range(client):
    response = client.post("/ingest/trips/download", json={"start": "2024-05", "end": "2024-01"})
    assert response.status_code == 422
