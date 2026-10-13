# tests/test_ingestion_health.py
from fastapi.testclient import TestClient
from ingestion_service.main import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ingestion"
