# tests/test_quality_monitor.py
from datetime import UTC, datetime, timedelta

from prometheus_client import REGISTRY
from quality_service.monitor import QualityMonitor
from quality_service.settings import QualitySettings

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


class FakeSources:
    """A healthy platform by default; override pieces to create problems."""

    def __init__(self, **overrides):
        self.values = {
            "load_log": [
                {
                    "year": 2024,
                    "month": 1,
                    "rows_loaded": 100,
                    "loaded_at": NOW - timedelta(days=2),
                },
                {
                    "year": 2024,
                    "month": 2,
                    "rows_loaded": 105,
                    "loaded_at": NOW - timedelta(days=2),
                },
                {"year": 2024, "month": 3, "rows_loaded": 95, "loaded_at": NOW - timedelta(days=2)},
            ],
            "fact": {"2024-01": 100, "2024-02": 105, "2024-03": 95},
            "summaries": [
                {
                    "year": 2024,
                    "month": m,
                    "rows_in": 110,
                    "rows_clean": rows,
                    "rows_quarantined": 5,
                    "pct_quarantined": 5.0,
                }
                for m, rows in ((1, 100), (2, 105), (3, 95))
            ],
            "reports": [{"year": 2024, "month": 1, "schema": {"unmapped_source_columns": []}}],
            "dbt": {"success": True, "started_at": (NOW - timedelta(days=1)).isoformat()},
        }
        self.values.update(overrides)

    def _get(self, key):
        value = self.values[key]
        if isinstance(value, Exception):
            raise value
        return value

    def load_log(self):
        return self._get("load_log")

    def fact_rows_by_month(self):
        return self._get("fact")

    def cleaning_summaries(self):
        return self._get("summaries")

    def cleaning_reports(self):
        return self._get("reports")

    def dbt_last_run(self):
        return self._get("dbt")


def make_monitor(**overrides) -> QualityMonitor:
    return QualityMonitor(FakeSources(**overrides), QualitySettings(_env_file=None), clock=lambda: NOW)


def statuses(report) -> dict:
    return {check["name"]: check["status"] for check in report["checks"]}


def test_a_healthy_platform_passes_every_check():
    report = make_monitor().run_checks()
    assert report["status"] == "ok"
    assert set(statuses(report)) == {
        "freshness",
        "row_counts",
        "quarantine_rate",
        "schema_drift",
        "row_reconciliation",
        "dbt_last_run",
    }
    assert set(statuses(report).values()) == {"ok"}
    assert report["ran_at"] == "2026-10-11T12:00:00+00:00"


def test_the_latest_result_is_remembered():
    monitor = make_monitor()
    assert monitor.latest() is None
    report = monitor.run_checks()
    assert monitor.latest() == report


def test_a_model_that_is_behind_the_load_fails_the_run():
    report = make_monitor(fact={"2024-01": 100, "2024-02": 105}).run_checks()  # March was never modelled
    assert report["status"] == "fail"
    assert statuses(report)["row_reconciliation"] == "fail"


def test_an_unreachable_source_becomes_a_warning_and_the_other_checks_still_run():
    report = make_monitor(summaries=ConnectionError("cleaning is down")).run_checks()
    result = statuses(report)
    assert result["quarantine_rate"] == "warn"
    assert result["row_reconciliation"] == "warn"
    assert result["freshness"] == "ok"
    assert "Could not evaluate" in next(c["message"] for c in report["checks"] if c["name"] == "quarantine_rate")


def test_results_are_published_as_prometheus_gauges():
    make_monitor(fact={"2024-01": 1}).run_checks()
    assert REGISTRY.get_sample_value("taxi_quality_check_status", {"check": "row_reconciliation"}) == 0.0
    assert REGISTRY.get_sample_value("taxi_quality_check_status", {"check": "freshness"}) == 2.0
    assert REGISTRY.get_sample_value("taxi_quality_overall_status") == 0.0
    assert REGISTRY.get_sample_value("taxi_quality_last_run_timestamp_seconds") == NOW.timestamp()
