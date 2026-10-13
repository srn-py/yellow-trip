# tests/integration/test_pipeline_end_to_end.py
"""End-to-end test: a small sample month travels through the REAL services.

upload -> clean -> load -> dbt build -> analytics API -> quality checks

It needs the throw-away stack from docker-compose.integration.yml (`make integration` starts it,
runs this file and removes it). Without that stack, every test here is skipped.
The sample has 5 trips: 3 good (one of them a "flex fare" without passenger count) and 2 bad
(a negative fare and a zero distance), so we know exactly what each stage must report.
"""

import io
import os
from datetime import datetime

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytestmark = pytest.mark.integration

URLS = {
    "ingestion": os.environ.get("IT_INGESTION_URL", "http://localhost:18000"),
    "cleaning": os.environ.get("IT_CLEANING_URL", "http://localhost:18100"),
    "etl": os.environ.get("IT_ETL_URL", "http://localhost:18200"),
    "analytics": os.environ.get("IT_ANALYTICS_URL", "http://localhost:18300"),
    "quality": os.environ.get("IT_QUALITY_URL", "http://localhost:18400"),
}

SCHEMA = pa.schema(
    [
        ("VendorID", pa.int32()),
        ("tpep_pickup_datetime", pa.timestamp("us")),
        ("tpep_dropoff_datetime", pa.timestamp("us")),
        ("passenger_count", pa.int64()),
        ("trip_distance", pa.float64()),
        ("RatecodeID", pa.int64()),
        ("store_and_fwd_flag", pa.string()),
        ("PULocationID", pa.int32()),
        ("DOLocationID", pa.int32()),
        ("payment_type", pa.int64()),
        ("fare_amount", pa.float64()),
        ("extra", pa.float64()),
        ("mta_tax", pa.float64()),
        ("tip_amount", pa.float64()),
        ("tolls_amount", pa.float64()),
        ("improvement_surcharge", pa.float64()),
        ("total_amount", pa.float64()),
        ("congestion_surcharge", pa.float64()),
        ("Airport_fee", pa.float64()),
    ]
)


def _trip(**overrides) -> dict:
    base = {
        "VendorID": 1,
        "tpep_pickup_datetime": datetime(2024, 1, 10, 8, 0),
        "tpep_dropoff_datetime": datetime(2024, 1, 10, 8, 20),
        "passenger_count": 1,
        "trip_distance": 3.0,
        "RatecodeID": 1,
        "store_and_fwd_flag": "N",
        "PULocationID": 100,
        "DOLocationID": 200,
        "payment_type": 1,
        "fare_amount": 15.0,
        "extra": 0.5,
        "mta_tax": 0.5,
        "tip_amount": 3.0,
        "tolls_amount": 0.0,
        "improvement_surcharge": 1.0,
        "total_amount": 20.0,
        "congestion_surcharge": 2.5,
        "Airport_fee": 0.0,
    }
    return {**base, **overrides}


def _trip_file() -> bytes:
    rows = [
        _trip(),
        _trip(
            tpep_pickup_datetime=datetime(2024, 1, 11, 9, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 11, 9, 30),
            payment_type=2,
            trip_distance=5.0,
            total_amount=25.0,
        ),
        _trip(  # flex fare: kept, with missing fields
            tpep_pickup_datetime=datetime(2024, 1, 12, 10, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 12, 10, 15),
            passenger_count=None,
            RatecodeID=None,
            store_and_fwd_flag=None,
            congestion_surcharge=None,
            Airport_fee=None,
            payment_type=0,
            trip_distance=2.0,
            fare_amount=10.0,
            total_amount=12.0,
        ),
        _trip(  # quarantined: negative fare
            tpep_pickup_datetime=datetime(2024, 1, 13, 9, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 13, 9, 20),
            fare_amount=-5.0,
            total_amount=-5.0,
            tip_amount=0.0,
        ),
        _trip(  # quarantined: zero distance
            tpep_pickup_datetime=datetime(2024, 1, 14, 8, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 14, 8, 10),
            trip_distance=0.0,
            total_amount=8.0,
        ),
    ]
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), buffer)
    return buffer.getvalue()


def _zones_file() -> bytes:
    lines = ["LocationID,Borough,Zone,service_zone", "1,EWR,Newark Airport,EWR"]
    lines += [f"{zone},Manhattan,Zone {zone},Yellow Zone" for zone in range(2, 266)]
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=900.0) as client:
        yield client


@pytest.fixture(scope="module")
def stack(http):
    """Skip everything unless the integration stack answers."""
    for name, url in URLS.items():
        try:
            http.get(f"{url}/health", timeout=5.0).raise_for_status()
        except httpx.HTTPError:
            pytest.skip(f"Integration stack is not running ({name} at {url}). Start it with `make integration`.")


@pytest.fixture(scope="module")
def pipeline(http, stack) -> dict:
    """Run the whole sample month through every stage once and keep each stage's answer."""
    result = {}
    result["zones_upload"] = http.post(
        f"{URLS['ingestion']}/ingest/upload",
        files={"file": ("taxi_zone_lookup.csv", _zones_file(), "text/csv")},
    ).json()
    result["trips_upload"] = http.post(
        f"{URLS['ingestion']}/ingest/upload",
        files={"file": ("yellow_tripdata_2024-01.parquet", _trip_file(), "application/octet-stream")},
    ).json()
    result["clean"] = http.post(f"{URLS['cleaning']}/clean/trips", json={"start": "2024-01"}).json()["results"][0]
    result["load_zones"] = http.post(f"{URLS['etl']}/load/zones").json()
    result["load"] = http.post(f"{URLS['etl']}/load/trips", json={"start": "2024-01"}).json()["results"][0]
    result["dbt"] = http.post(
        f"{URLS['etl']}/transform/run",
        json={"command": "build", "select": None, "full_refresh": False},
    ).json()
    result["kpis"] = http.get(f"{URLS['analytics']}/kpis").json()
    result["payments"] = http.get(f"{URLS['analytics']}/breakdown/payment-type").json()
    result["quality"] = http.post(f"{URLS['quality']}/checks/run").json()
    return result


def test_ingestion_stores_both_files(pipeline):
    assert pipeline["zones_upload"]["status"] in {"ingested", "duplicate"}
    assert pipeline["trips_upload"]["status"] in {"ingested", "duplicate"}
    assert pipeline["trips_upload"]["file"]["row_count"] == 5


def test_cleaning_keeps_three_and_quarantines_two(pipeline):
    assert pipeline["clean"]["status"] in {"cleaned", "skipped"}
    counts = pipeline["clean"]["report"]["counts"]
    assert (counts["rows_in"], counts["rows_clean"], counts["rows_quarantined"]) == (5, 3, 2)
    violations = pipeline["clean"]["report"]["rule_violations"]
    assert violations["negative_fare"] == 1
    assert violations["zero_or_negative_distance"] == 1


def test_loading_puts_three_rows_in_the_warehouse(pipeline):
    assert pipeline["load_zones"]["rows_loaded"] == 265
    assert pipeline["load"]["status"] in {"loaded", "skipped"}
    assert pipeline["load"]["load"]["rows_loaded"] == 3


def test_dbt_builds_every_model_and_every_test_passes(pipeline):
    assert pipeline["dbt"]["success"] is True, pipeline["dbt"]["log_tail"]


def test_analytics_api_serves_the_modelled_data(pipeline):
    assert pipeline["kpis"]["trips"] == 3
    assert pipeline["kpis"]["total_revenue"] == 57.0  # 20 + 25 + 12
    flex = [row for row in pipeline["payments"] if row["payment_type_id"] == 0]
    assert flex and flex[0]["trips"] == 1


def test_quality_checks_flag_the_dirty_sample_and_nothing_else(pipeline):
    quality = pipeline["quality"]
    by_name = {check["name"]: check for check in quality["checks"]}
    failing = [name for name, check in by_name.items() if check["status"] == "fail"]

    # 2 of the 5 sample trips are rejected (40%), far above the 10% limit: the check must catch that.
    assert failing == ["quarantine_rate"], quality["checks"]
    assert quality["status"] == "fail"
    assert by_name["quarantine_rate"]["value"] == 40.0

    # Everything else about this sample is healthy.
    assert by_name["row_reconciliation"]["status"] == "ok"
    assert by_name["schema_drift"]["status"] == "ok"
    assert by_name["dbt_last_run"]["status"] == "ok"


def test_a_corrupt_file_is_rejected_with_a_clear_error(http, stack):
    response = http.post(
        f"{URLS['ingestion']}/ingest/upload",
        files={
            "file": (
                "yellow_tripdata_2024-02.parquet",
                b"this is not parquet",
                "application/octet-stream",
            )
        },
    )
    assert response.status_code == 422
