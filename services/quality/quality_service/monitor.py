# services/quality/quality_service/monitor.py
"""Runs all quality checks, remembers the latest result and publishes it as metrics.

A failure to *fetch* data (for example the warehouse is restarting) must not crash the monitor or
be mistaken for bad data: that check reports "could not evaluate" as a warning, and the others still run.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from . import checks, metrics
from .checks import WARN, CheckResult
from .settings import QualitySettings

logger = logging.getLogger(__name__)

# data key -> method of the sources object that fetches it
_FETCHERS = {
    "load_log": "load_log",
    "fact": "fact_rows_by_month",
    "summaries": "cleaning_summaries",
    "reports": "cleaning_reports",
    "dbt": "dbt_last_run",
}


def _month(row: dict) -> str:
    """Format a row's year and month as YYYY-MM."""
    return f"{row['year']}-{row['month']:02d}"


class QualityMonitor:
    """Gathers data, runs the checks, and keeps the latest result."""

    def __init__(self, sources, settings: QualitySettings, clock: Callable[[], datetime] | None = None):
        self._sources = sources
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._latest: dict | None = None

    def latest(self) -> dict | None:
        """The result of the most recent run.

        Returns:
            The result dict, or None if no run has finished yet.
        """
        return self._latest

    def _collect(self) -> tuple[dict, dict]:
        """Fetch every piece of data once; remember which fetches failed."""
        data: dict = {}
        errors: dict = {}
        for key, method in _FETCHERS.items():
            try:
                data[key] = getattr(self._sources, method)()
            except Exception as exc:  # unreachable service, restarting database...
                errors[key] = f"{type(exc).__name__}: {exc}"
                logger.warning("Could not fetch %s for the quality checks: %s", key, errors[key])
        return data, errors

    @staticmethod
    def _evaluate(name: str, needs: tuple, errors: dict, compute: Callable[[], CheckResult]) -> CheckResult:
        """Run one check, or report that its data could not be fetched."""
        broken = [f"{key} ({errors[key]})" for key in needs if key in errors]
        if broken:
            return CheckResult(name, WARN, "Could not evaluate: " + "; ".join(broken))
        try:
            return compute()
        except Exception as exc:
            logger.exception("Quality check %s crashed", name)
            return CheckResult(name, WARN, f"Could not evaluate: {type(exc).__name__}: {exc}")

    def run_checks(self) -> dict:
        """Run all checks now.

        Returns:
            {"status": overall verdict, "ran_at": time, "checks": [one dict per check]}.
        """
        with self._lock:
            now = self._clock()
            settings = self._settings
            data, errors = self._collect()

            def loaded_rows() -> dict[str, int]:
                return {_month(row): int(row["rows_loaded"]) for row in data["load_log"]}

            def last_loaded_at() -> datetime | None:
                times = [row["loaded_at"] for row in data["load_log"] if row.get("loaded_at")]
                return max(times) if times else None

            results = [
                self._evaluate(
                    "freshness",
                    ("load_log",),
                    errors,
                    lambda: checks.check_freshness(last_loaded_at(), now, settings.quality_max_load_age_days),
                ),
                self._evaluate(
                    "row_counts",
                    ("load_log",),
                    errors,
                    lambda: checks.check_row_counts(
                        loaded_rows(),
                        settings.quality_rowcount_tolerance_pct,
                        settings.quality_min_months_for_rowcounts,
                    ),
                ),
                self._evaluate(
                    "quarantine_rate",
                    ("summaries",),
                    errors,
                    lambda: checks.check_quarantine_rate(data["summaries"], settings.quality_max_quarantine_pct),
                ),
                self._evaluate(
                    "schema_drift",
                    ("reports",),
                    errors,
                    lambda: checks.check_schema_drift(data["reports"]),
                ),
                self._evaluate(
                    "row_reconciliation",
                    ("summaries", "load_log", "fact"),
                    errors,
                    lambda: checks.check_row_reconciliation(
                        {_month(item): int(item["rows_clean"]) for item in data["summaries"]},
                        loaded_rows(),
                        data["fact"],
                    ),
                ),
                self._evaluate(
                    "dbt_last_run",
                    ("dbt",),
                    errors,
                    lambda: checks.check_dbt_last_run(data["dbt"], now, settings.quality_max_dbt_age_days),
                ),
            ]

            overall = checks.overall_status(results)
            report = {
                "status": overall,
                "ran_at": now.isoformat(timespec="seconds"),
                "checks": [result.as_dict() for result in results],
            }
            self._latest = report
            metrics.update(results, overall, now.timestamp())
            logger.info(
                "Quality checks finished: %s",
                overall,
                extra={"checks": {result.name: result.status for result in results}},
            )
            return report
