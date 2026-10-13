# services/quality/quality_service/metrics.py
"""Prometheus gauges for the check results. Grafana draws them and alert rules watch them."""

from prometheus_client import Counter, Gauge

from .checks import STATUS_CODE, CheckResult

CHECK_STATUS = Gauge("taxi_quality_check_status", "Check verdict: 0 = fail, 1 = warn, 2 = ok", ["check"])
CHECK_VALUE = Gauge("taxi_quality_check_value", "The number measured by a check", ["check"])
OVERALL_STATUS = Gauge("taxi_quality_overall_status", "Worst verdict of all checks: 0 fail, 1 warn, 2 ok")
LAST_RUN = Gauge("taxi_quality_last_run_timestamp_seconds", "Unix time of the last check run")
RUNS = Counter("taxi_quality_runs_total", "Check runs by overall verdict", ["status"])


def update(results: list[CheckResult], overall: str, timestamp: float) -> None:
    """Publish the results of one check run.

    Args:
        results: Verdicts of all checks.
        overall: The combined verdict.
        timestamp: Unix time of the run.
    """
    for result in results:
        CHECK_STATUS.labels(result.name).set(STATUS_CODE[result.status])
        if result.value is not None:
            CHECK_VALUE.labels(result.name).set(result.value)
    OVERALL_STATUS.set(STATUS_CODE[overall])
    LAST_RUN.set(timestamp)
    RUNS.labels(overall).inc()
