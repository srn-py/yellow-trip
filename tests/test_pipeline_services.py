# tests/test_pipeline_services.py
import httpx
import pytest
from taxi_pipeline.services import MonthNotAvailableError, PlatformApi, StepError


def make_api(routes, calls=None):
    """Build a PlatformApi whose HTTP calls are answered from a table (no network)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.host, request.url.path)
        if calls is not None:
            calls.append((key, request.content.decode() if request.content else ""))
        if key not in routes:
            return httpx.Response(404, json={"detail": f"no route for {key}"})
        answer = routes[key]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PlatformApi("http://ingestion", "http://cleaning", "http://etl", client=client)


def result(status, **extra):
    return (200, {"results": [{"label": "2024-01", "status": status, "message": status, **extra}]})


READY = {
    ("GET", "ingestion", "/health/ready"): (200, {"status": "ready"}),
    ("GET", "cleaning", "/health/ready"): (200, {"status": "ready"}),
    ("GET", "etl", "/health/ready"): (200, {"status": "ready"}),
}


def test_wait_ready_passes_when_every_service_answers():
    make_api(READY).wait_ready()


def test_wait_ready_names_the_service_that_is_down():
    routes = {**READY, ("GET", "cleaning", "/health/ready"): (503, {"detail": "down"})}
    with pytest.raises(StepError, match="cleaning"):
        make_api(routes).wait_ready()


def test_ingest_month_sends_the_month_and_accepts_done_statuses():
    calls = []
    routes = {("POST", "ingestion", "/ingest/trips/download"): result("skipped")}
    item = make_api(routes, calls).ingest_month(2024, 1)
    assert item["status"] == "skipped"
    assert '"start":"2024-01"' in calls[0][1].replace(" ", "")


def test_unpublished_month_raises_the_special_error():
    routes = {("POST", "ingestion", "/ingest/trips/download"): result("not_available")}
    with pytest.raises(MonthNotAvailableError):
        make_api(routes).ingest_month(2030, 1)


def test_failed_ingestion_is_a_normal_step_error():
    routes = {("POST", "ingestion", "/ingest/trips/download"): result("failed")}
    with pytest.raises(StepError, match="failed"):
        make_api(routes).ingest_month(2024, 1)


def test_clean_month_returns_the_report_and_passes_force():
    calls = []
    report = {"counts": {"rows_in": 10, "rows_clean": 8, "rows_quarantined": 2}}
    routes = {("POST", "cleaning", "/clean/trips"): result("cleaned", report=report)}
    item = make_api(routes, calls).clean_month(2024, 1, force=True)
    assert item["report"]["counts"]["rows_clean"] == 8
    assert '"force":true' in calls[0][1].replace(" ", "")


def test_clean_month_not_ingested_is_an_error():
    routes = {("POST", "cleaning", "/clean/trips"): result("not_ingested")}
    with pytest.raises(StepError, match="not_ingested"):
        make_api(routes).clean_month(2024, 1)


def test_load_month_accepts_loaded_and_rejects_not_cleaned():
    ok = {("POST", "etl", "/load/trips"): result("loaded", load={"rows_loaded": 8})}
    assert make_api(ok).load_month(2024, 1)["load"]["rows_loaded"] == 8
    bad = {("POST", "etl", "/load/trips"): result("not_cleaned")}
    with pytest.raises(StepError, match="not_cleaned"):
        make_api(bad).load_month(2024, 1)


def test_ensure_zones_calls_both_services():
    routes = {
        ("POST", "ingestion", "/ingest/zones/download"): (200, {"status": "skipped"}),
        ("POST", "etl", "/load/zones"): (200, {"status": "loaded", "rows_loaded": 265}),
    }
    assert make_api(routes).ensure_zones() == {"zone_file_status": "skipped", "zones_loaded": 265}


def test_run_dbt_success_returns_a_short_summary():
    body = {"success": True, "duration_seconds": 12.3, "results": {"counts": {"success": 20}}}
    routes = {("POST", "etl", "/transform/run"): (200, body)}
    assert make_api(routes).run_dbt() == {"counts": {"success": 20}, "duration_seconds": 12.3}


def test_run_dbt_failure_carries_the_problem_into_the_message():
    problem = {
        "node": "test.x.unique_fct_trips_trip_id",
        "status": "fail",
        "message": "Got 3 results",
    }
    body = {
        "success": False,
        "results": {"counts": {"fail": 1}, "problems": [problem]},
        "log_tail": [],
    }
    routes = {("POST", "etl", "/transform/run"): (200, body)}
    with pytest.raises(StepError, match="unique_fct_trips_trip_id"):
        make_api(routes).run_dbt()


def test_connection_problem_becomes_a_step_error():
    routes = {("POST", "etl", "/transform/run"): httpx.ConnectError("boom")}
    with pytest.raises(StepError, match="Could not reach etl"):
        make_api(routes).run_dbt()


def test_http_error_status_becomes_a_step_error_with_the_detail():
    routes = {("POST", "etl", "/transform/run"): (409, {"detail": "A dbt run is already in progress"})}
    with pytest.raises(StepError, match="409"):
        make_api(routes).run_dbt()


def verify_routes(rows_loaded):
    return {
        ("GET", "cleaning", "/reports/trips/2024/1"): (200, {"counts": {"rows_clean": 100}}),
        ("GET", "etl", "/load/status"): (
            200,
            {"months": [{"year": 2024, "month": 1, "rows_loaded": rows_loaded}]},
        ),
    }


def test_verify_month_passes_when_both_services_agree():
    assert make_api(verify_routes(100)).verify_month(2024, 1) == {
        "label": "2024-01",
        "rows_clean": 100,
        "rows_loaded": 100,
    }


def test_verify_month_fails_on_a_row_count_mismatch():
    with pytest.raises(StepError, match="100 rows but the warehouse loaded 99"):
        make_api(verify_routes(99)).verify_month(2024, 1)


def test_verify_month_fails_when_the_month_was_never_loaded():
    routes = {
        ("GET", "cleaning", "/reports/trips/2024/1"): (200, {"counts": {"rows_clean": 100}}),
        ("GET", "etl", "/load/status"): (200, {"months": []}),
    }
    with pytest.raises(StepError, match="not in the warehouse"):
        make_api(routes).verify_month(2024, 1)


def test_from_env_reads_service_urls(monkeypatch):
    monkeypatch.setenv("ETL_URL", "http://example-etl:9999/")
    api = PlatformApi.from_env()
    assert api._urls["etl"] == "http://example-etl:9999"
