# tests/test_service_metrics.py
from cleaning_service import metrics as cleaning_metrics
from etl_service import metrics as etl_metrics
from ingestion_service import metrics as ingestion_metrics
from prometheus_client import REGISTRY


def sample(name: str, labels: dict | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_ingest_counts_files_rows_and_bytes_only_for_new_files():
    files_before = sample("taxi_ingest_files_total", {"status": "ingested", "source": "upload"})
    rows_before = sample("taxi_ingest_rows_total")
    ingestion_metrics.record_ingest("ingested", "upload", rows=100, size_bytes=2048)
    ingestion_metrics.record_ingest("duplicate", "upload")
    assert sample("taxi_ingest_files_total", {"status": "ingested", "source": "upload"}) == files_before + 1
    assert sample("taxi_ingest_rows_total") == rows_before + 100


REPORT = {
    "counts": {"rows_in": 10, "rows_clean": 8, "rows_quarantined": 2, "pct_quarantined": 20.0},
    "rule_violations": {"negative_fare": 2, "excessive_speed": 0},
    "duration_seconds": 12.5,
}


def test_a_cleaned_month_updates_rows_rules_duration_and_gauges():
    rows_before = sample("taxi_cleaning_rows_total", {"kind": "quarantined"})
    rule_before = sample("taxi_cleaning_rule_violations_total", {"rule": "negative_fare"})
    cleaning_metrics.record_outcome("cleaned", REPORT)
    assert sample("taxi_cleaning_rows_total", {"kind": "quarantined"}) == rows_before + 2
    assert sample("taxi_cleaning_rule_violations_total", {"rule": "negative_fare"}) == rule_before + 2
    assert sample("taxi_cleaning_last_quarantine_pct") == 20.0
    assert sample("taxi_cleaning_last_success_timestamp_seconds") > 0


def test_skipped_and_failed_cleanings_only_count_the_request():
    rows_before = sample("taxi_cleaning_rows_total", {"kind": "in"})
    failed_before = sample("taxi_cleaning_runs_total", {"status": "failed"})
    cleaning_metrics.record_outcome("skipped", REPORT)
    cleaning_metrics.record_outcome("failed")
    assert sample("taxi_cleaning_rows_total", {"kind": "in"}) == rows_before
    assert sample("taxi_cleaning_runs_total", {"status": "failed"}) == failed_before + 1


def test_loads_count_rows_only_when_loaded():
    before = sample("taxi_etl_rows_loaded_total")
    etl_metrics.record_load("loaded", {"rows_loaded": 50, "duration_seconds": 3.0})
    etl_metrics.record_load("skipped", {"rows_loaded": 50, "duration_seconds": 3.0})
    assert sample("taxi_etl_rows_loaded_total") == before + 50


def test_dbt_runs_set_the_last_success_gauge():
    etl_metrics.record_dbt({"success": True, "duration_seconds": 20.0})
    assert sample("taxi_etl_dbt_last_run_success") == 1.0
    failures_before = sample("taxi_etl_dbt_runs_total", {"result": "failure"})
    etl_metrics.record_dbt({"success": False, "duration_seconds": 5.0})
    assert sample("taxi_etl_dbt_last_run_success") == 0.0
    assert sample("taxi_etl_dbt_runs_total", {"result": "failure"}) == failures_before + 1
