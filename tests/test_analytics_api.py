# tests/test_analytics_api.py
from datetime import date

import pytest
from analytics_service.database import ModelsNotBuiltError
from analytics_service.routes import get_database, register_error_handlers, router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeDatabase:
    """Records every query and answers from a table keyed by the `-- q:name` tag in the SQL."""

    def __init__(self, responses=None, error=None):
        self.responses = responses or {}
        self.error = error
        self.calls = []

    def query(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        if self.error:
            raise self.error
        for tag, rows in self.responses.items():
            if f"-- q:{tag}\n" in sql or sql.endswith(f"-- q:{tag}"):
                return rows
        return []


def make_client(database):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_database] = lambda: database
    return TestClient(app)


KPI_ROW = {
    "trips": 100,
    "total_revenue": 2000.0,
    "fare_revenue": 1500.0,
    "tip_revenue": 300.0,
    "total_distance_miles": 350.0,
    "total_duration_minutes": 1800.0,
    "airport_trips": 10,
}


def test_kpis_turns_sums_into_averages_and_passes_filters():
    database = FakeDatabase({"kpis": [KPI_ROW]})
    response = make_client(database).get("/kpis", params={"start": "2024-01-01", "borough": ["Queens", "Bronx"]})

    assert response.status_code == 200
    body = response.json()
    assert body["avg_fare"] == 15.0
    assert body["avg_distance_miles"] == 3.5
    assert body["avg_duration_minutes"] == 18.0
    assert body["airport_share_pct"] == 10.0
    assert database.calls[0][1] == [date(2024, 1, 1), ["Queens", "Bronx"]]


def test_kpis_with_no_trips_gives_none_instead_of_dividing_by_zero():
    empty = {**KPI_ROW, **{key: 0 for key in KPI_ROW}}
    body = make_client(FakeDatabase({"kpis": [empty]})).get("/kpis").json()
    assert body["trips"] == 0
    assert body["avg_fare"] is None
    assert body["airport_share_pct"] is None


def test_start_after_end_is_rejected():
    response = make_client(FakeDatabase()).get("/trips/daily", params={"start": "2024-02-01", "end": "2024-01-01"})
    assert response.status_code == 422


def test_daily_series_shape():
    rows = [{"date": date(2024, 1, 1), "trips": 10, "total_revenue": 200.0, "avg_fare": 15.5}]
    body = make_client(FakeDatabase({"daily": rows})).get("/trips/daily").json()
    assert body == [{"date": "2024-01-01", "trips": 10, "total_revenue": 200.0, "avg_fare": 15.5}]


def test_heatmap_and_breakdown_endpoints_return_rows():
    database = FakeDatabase(
        {
            "heatmap": [{"day_of_week": 1, "hour_of_day": 8, "trips": 50}],
            "payment": [
                {
                    "payment_type_id": 1,
                    "payment_type": "Credit card",
                    "trips": 90,
                    "total_revenue": 1800.0,
                    "avg_fare": 15.0,
                    "tip_pct_of_fare": 20.0,
                    "pct_trips_with_tip": 85.0,
                }
            ],
        }
    )
    client = make_client(database)
    assert client.get("/demand/heatmap").json()[0]["hour_of_day"] == 8
    assert client.get("/breakdown/payment-type").json()[0]["tip_pct_of_fare"] == 20.0


def test_zones_top_validates_by_and_limit_and_passes_the_limit_last():
    database = FakeDatabase(
        {"top_zones": [{"zone": "JFK Airport", "borough": "Queens", "trips": 5, "total_revenue": 400.0}]}
    )
    client = make_client(database)

    ok = client.get("/zones/top", params={"by": "dropoff", "limit": 5, "start": "2024-02-10"})
    assert ok.status_code == 200
    assert database.calls[-1][1] == [202402, 5]

    assert client.get("/zones/top", params={"by": "sideways"}).status_code == 422
    assert client.get("/zones/top", params={"limit": 0}).status_code == 422
    assert client.get("/zones/top", params={"limit": 101}).status_code == 422


def test_zone_hourly_requires_a_valid_zone_id():
    database = FakeDatabase({"zone_hourly": [{"day_of_week": 2, "hour_of_day": 9, "trips": 7}]})
    client = make_client(database)
    assert client.get("/demand/zone-hourly", params={"zone_id": 132}).status_code == 200
    assert database.calls[-1][1] == [132]
    assert client.get("/demand/zone-hourly", params={"zone_id": 999}).status_code == 422
    assert client.get("/demand/zone-hourly").status_code == 422


def test_meta_filters_combines_several_queries():
    database = FakeDatabase(
        {
            "meta_dates": [{"date_min": date(2024, 1, 1), "date_max": date(2025, 1, 31)}],
            "meta_months": [{"month": "2024-01"}, {"month": "2025-01"}],
            "meta_boroughs": [{"borough": "Manhattan"}, {"borough": "Queens"}],
            "meta_payments": [{"id": 1, "name": "Credit card"}],
        }
    )
    body = make_client(database).get("/meta/filters").json()
    assert body["date_min"] == "2024-01-01"
    assert body["months"] == ["2024-01", "2025-01"]
    assert body["boroughs"] == ["Manhattan", "Queens"]
    assert body["payment_types"] == [{"id": 1, "name": "Credit card"}]


def test_models_not_built_gives_a_clear_503():
    database = FakeDatabase(error=ModelsNotBuiltError("The warehouse tables are not built yet. Run dbt first."))
    response = make_client(database).get("/kpis")
    assert response.status_code == 503
    assert "Run dbt" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/airports", "/airports/daily", "/breakdown/borough", "/routes/top", "/zones"])
def test_remaining_endpoints_answer_even_with_no_rows(path):
    assert make_client(FakeDatabase()).get(path).json() == []
