# tests/test_etl_api.py
import pytest
from etl_service.landing import SchemaContractError
from etl_service.loader import LoadOutcome, NotCleanedError
from etl_service.routes import get_loader, get_transformer, get_warehouse, router
from etl_service.transform import TransformBusyError
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeLoader:
    def load_month(self, year, month, force=False):
        if month == 2:
            raise NotCleanedError("not cleaned")
        if month == 3:
            raise SchemaContractError("bad columns")
        record = {"year": year, "month": month, "rows_loaded": 3, "duration_seconds": 1.0}
        return LoadOutcome("loaded", record)

    def load_zones(self):
        return LoadOutcome("loaded", {"rows_loaded": 265, "source": "reference/zones.csv"})


class FakeTransformer:
    def __init__(self):
        self.busy = False
        self.last = None

    def run(self, command, select, full_refresh):
        if self.busy:
            raise TransformBusyError("busy")
        if select == "bad selector":
            raise ValueError("Invalid selector")
        self.last = {"command": command, "success": True}
        return self.last

    def generate_docs(self):
        return {"command": "docs generate", "success": True}

    def last_run(self):
        return self.last


class FakeWarehouse:
    def list_load_log(self):
        return [{"year": 2024, "month": 1, "rows_loaded": 3}]


@pytest.fixture
def transformer():
    return FakeTransformer()


@pytest.fixture
def client(transformer):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_loader] = lambda: FakeLoader()
    app.dependency_overrides[get_transformer] = lambda: transformer
    app.dependency_overrides[get_warehouse] = lambda: FakeWarehouse()
    return TestClient(app)


def test_each_month_reports_its_own_status(client):
    response = client.post("/load/trips", json={"start": "2024-01", "end": "2024-03"})
    assert response.status_code == 200
    statuses = {item["label"]: item["status"] for item in response.json()["results"]}
    assert statuses == {"2024-01": "loaded", "2024-02": "not_cleaned", "2024-03": "rejected"}


def test_zones_and_status_endpoints(client):
    assert client.post("/load/zones").json()["rows_loaded"] == 265
    assert client.get("/load/status").json()["count"] == 1


def test_transform_run_and_last_run(client):
    assert client.get("/transform/last-run").status_code == 404
    assert client.post("/transform/run", json={"command": "build"}).json()["success"] is True
    assert client.get("/transform/last-run").json()["command"] == "build"


def test_busy_runner_gives_409_and_bad_selector_gives_422(client, transformer):
    transformer.busy = True
    assert client.post("/transform/run", json={"command": "build"}).status_code == 409
    transformer.busy = False
    # Rejected by the request model before it reaches dbt.
    assert client.post("/transform/run", json={"command": "build", "select": "--target prod"}).status_code == 422


def test_unknown_dbt_command_is_rejected(client):
    assert client.post("/transform/run", json={"command": "run-operation"}).status_code == 422


def test_docs_endpoint(client):
    assert client.post("/transform/docs").json()["command"] == "docs generate"
