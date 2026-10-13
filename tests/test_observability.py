# tests/test_observability.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from shared.observability import setup_observability


def counted(route: str, status: str, method: str = "GET") -> float:
    value = REGISTRY.get_sample_value("taxi_http_requests_total", {"method": method, "route": route, "status": status})
    return value or 0.0


def make_client() -> TestClient:
    app = FastAPI()
    setup_observability(app)

    @app.get("/items/{item_id}")
    def item(item_id: int) -> dict:
        return {"id": item_id}

    @app.get("/boom")
    def boom() -> dict:
        raise RuntimeError("simulated crash")

    return TestClient(app, raise_server_exceptions=False)


def test_requests_are_counted_by_route_template_not_by_url():
    client = make_client()
    before = counted("/items/{item_id}", "200")
    client.get("/items/5")
    client.get("/items/6")
    assert counted("/items/{item_id}", "200") == before + 2


def test_unknown_paths_and_crashes_are_counted_too():
    client = make_client()
    unmatched_before = counted("unmatched", "404")
    crash_before = counted("/boom", "500")
    client.get("/does-not-exist")
    client.get("/boom")
    assert counted("unmatched", "404") == unmatched_before + 1
    assert counted("/boom", "500") == crash_before + 1


def test_metrics_page_lists_the_http_metrics_and_is_not_counted_itself():
    client = make_client()
    before = counted("/metrics", "200")
    page = client.get("/metrics")
    assert page.status_code == 200
    assert "taxi_http_requests_total" in page.text
    assert "taxi_http_request_duration_seconds_bucket" in page.text
    assert counted("/metrics", "200") == before


def test_request_id_is_echoed_or_generated():
    client = make_client()
    assert client.get("/items/1", headers={"X-Request-ID": "trace-me"}).headers["x-request-id"] == "trace-me"
    assert len(client.get("/items/1").headers["x-request-id"]) == 12
