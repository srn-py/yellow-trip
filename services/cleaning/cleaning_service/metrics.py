# services/cleaning/cleaning_service/metrics.py
"""Pipeline metrics of the cleaning service.

Counters only ever go up (Prometheus handles restarts); gauges hold the latest value.
"""

from prometheus_client import Counter, Gauge, Histogram

CLEAN_RUNS = Counter("taxi_cleaning_runs_total", "Cleaning requests by outcome", ["status"])
CLEAN_ROWS = Counter("taxi_cleaning_rows_total", "Rows processed by cleaning", ["kind"])
RULE_VIOLATIONS = Counter("taxi_cleaning_rule_violations_total", "Rows breaking each cleaning rule", ["rule"])
CLEAN_DURATION = Histogram(
    "taxi_cleaning_duration_seconds",
    "Time to clean one month",
    buckets=(5, 15, 30, 60, 120, 300, 600, 1200, 3600),
)
LAST_QUARANTINE_PCT = Gauge(
    "taxi_cleaning_last_quarantine_pct", "Quarantined share of the last cleaned month, in percent"
)
LAST_SUCCESS = Gauge("taxi_cleaning_last_success_timestamp_seconds", "Unix time of the last successful cleaning")


def record_outcome(status: str, report: dict | None = None) -> None:
    """Record the outcome of one cleaning request.

    Args:
        status: cleaned, skipped, not_ingested, rejected or failed.
        report: The cleaning report (needed for "cleaned" to count rows and timings).
    """
    CLEAN_RUNS.labels(status).inc()
    if status != "cleaned" or not report:
        return
    counts = report["counts"]
    CLEAN_ROWS.labels("in").inc(counts["rows_in"])
    CLEAN_ROWS.labels("clean").inc(counts["rows_clean"])
    CLEAN_ROWS.labels("quarantined").inc(counts["rows_quarantined"])
    for rule, rows in report.get("rule_violations", {}).items():
        if rows:
            RULE_VIOLATIONS.labels(rule).inc(rows)
    CLEAN_DURATION.observe(report.get("duration_seconds") or 0)
    LAST_QUARANTINE_PCT.set(counts["pct_quarantined"])
    LAST_SUCCESS.set_to_current_time()
