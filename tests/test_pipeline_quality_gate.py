# tests/test_pipeline_quality_gate.py
import httpx
import pytest
from taxi_pipeline.services import PlatformApi, StepError


def make_api(answer, with_quality=True) -> PlatformApi:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/checks/run"
        return httpx.Response(200, json=answer)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PlatformApi(
        "http://ingestion", "http://cleaning", "http://etl", client=client,
        quality_url="http://quality" if with_quality else None,
    )  # fmt: skip


def check(name, status, message=""):
    return {"name": name, "status": status, "message": message}


def test_gate_passes_and_lists_warnings():
    answer = {"status": "warn", "checks": [check("freshness", "ok"), check("schema_drift", "warn")]}
    assert make_api(answer).run_quality_checks() == {"status": "warn", "warnings": ["schema_drift"]}


def test_gate_fails_and_names_every_failing_check():
    answer = {
        "status": "fail",
        "checks": [
            check("row_counts", "fail", "March is +190%"),
            check("freshness", "ok"),
            check("dbt_last_run", "fail", "dbt failed"),
        ],
    }
    with pytest.raises(StepError) as error:
        make_api(answer).run_quality_checks()
    assert "row_counts: March is +190%" in str(error.value)
    assert "dbt_last_run: dbt failed" in str(error.value)


def test_gate_without_a_configured_quality_service_gives_a_clear_error():
    with pytest.raises(StepError, match="quality service is not configured"):
        make_api({}, with_quality=False).run_quality_checks()
