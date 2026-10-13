# tests/test_quality_checks.py
from datetime import UTC, datetime, timedelta

from quality_service import checks
from quality_service.checks import FAIL, OK, WARN, CheckResult

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def test_overall_status_is_the_worst_verdict():
    ok, warn, fail = (
        CheckResult("a", OK, ""),
        CheckResult("b", WARN, ""),
        CheckResult("c", FAIL, ""),
    )
    assert checks.overall_status([ok, ok]) == OK
    assert checks.overall_status([ok, warn]) == WARN
    assert checks.overall_status([ok, warn, fail]) == FAIL
    assert checks.overall_status([]) == OK


def test_freshness():
    assert checks.check_freshness(None, NOW, 45).status == WARN
    assert checks.check_freshness(NOW - timedelta(days=2), NOW, 45).status == OK
    stale = checks.check_freshness(NOW - timedelta(days=60), NOW, 45)
    assert stale.status == FAIL
    assert stale.value == 60.0


def test_row_counts_need_enough_months_to_compare():
    result = checks.check_row_counts({"2024-01": 100, "2024-02": 5000}, 40)
    assert result.status == OK
    assert result.value is None


def test_row_counts_accept_normal_variation():
    result = checks.check_row_counts({"2024-01": 100, "2024-02": 105, "2024-03": 95}, 40)
    assert result.status == OK
    assert result.value < 40


def test_row_counts_warn_then_fail_as_a_month_drifts_away():
    warn = checks.check_row_counts({"2024-01": 100, "2024-02": 100, "2024-03": 160}, 40)
    fail = checks.check_row_counts({"2024-01": 100, "2024-02": 105, "2024-03": 300}, 40)
    assert warn.status == WARN
    assert fail.status == FAIL
    assert "2024-03" in fail.message
    assert fail.details["deviation_pct_by_month"]["2024-03"] > 80


def test_quarantine_rate():
    summaries = [
        {"year": 2024, "month": 1, "pct_quarantined": 5.0},
        {"year": 2024, "month": 2, "pct_quarantined": 4.0},
    ]
    assert checks.check_quarantine_rate([], 10).status == OK
    assert checks.check_quarantine_rate(summaries, 10).status == OK
    assert checks.check_quarantine_rate(summaries, 6).status == WARN  # 5.0 is above 80% of 6
    assert checks.check_quarantine_rate(summaries, 4.5).status == FAIL
    assert checks.check_quarantine_rate(summaries, 4.5).value == 5.0


def test_schema_drift_names_the_unknown_columns_and_ignores_old_reports():
    clean = {"year": 2024, "month": 1, "schema": {"unmapped_source_columns": []}}
    old = {"year": 2024, "month": 2}  # report written before this key existed
    drifted = {"year": 2025, "month": 1, "schema": {"unmapped_source_columns": ["new_fee"]}}
    assert checks.check_schema_drift([clean, old]).status == OK
    result = checks.check_schema_drift([clean, old, drifted])
    assert result.status == WARN
    assert "new_fee" in result.message
    assert result.value == 1.0


def test_reconciliation_passes_when_all_stages_agree():
    stages = {"2024-01": 100, "2024-02": 200}
    assert checks.check_row_reconciliation(stages, stages, stages).status == OK


def test_reconciliation_reports_every_disagreement():
    cleaned = {"2024-01": 100, "2024-02": 200}
    loaded = {"2024-01": 100, "2024-02": 190, "2024-03": 50}
    fact = {"2024-01": 100, "2024-02": 190}
    result = checks.check_row_reconciliation(cleaned, loaded, fact)
    assert result.status == FAIL
    assert "2024-02: cleaning published 200 rows but the warehouse loaded 190" in result.message
    assert "2024-03: loaded but there is no cleaning report" in result.message
    assert "2024-03: landing has 50 rows but fct_trips has 0" in result.message


def test_dbt_last_run():
    recent = {"success": True, "started_at": (NOW - timedelta(days=1)).isoformat()}
    old = {"success": True, "started_at": (NOW - timedelta(days=90)).isoformat()}
    failed = {"success": False, "results": {"problems": [{"node": "x"}]}}
    assert checks.check_dbt_last_run(None, NOW, 45).status == WARN
    assert checks.check_dbt_last_run(recent, NOW, 45).status == OK
    assert checks.check_dbt_last_run(old, NOW, 45).status == WARN
    assert checks.check_dbt_last_run(failed, NOW, 45).status == FAIL
