# services/quality/quality_service/checks.py
"""The data-quality checks, as pure functions.

Each check receives plain data (numbers, dictionaries, dates), never a database or an HTTP client,
and returns a `CheckResult`. That makes them trivial to test: pass a situation in, look at the verdict.

Verdicts: ``ok``, ``warn`` (look at it soon) and ``fail`` (something is wrong now).
Months are written "YYYY-MM" everywhere.
"""

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

OK, WARN, FAIL = "ok", "warn", "fail"

# Numeric form used by the Prometheus gauge, ordered so that LOWER means WORSE.
STATUS_CODE = {FAIL: 0, WARN: 1, OK: 2}


@dataclass(frozen=True)
class CheckResult:
    """The verdict of one check.

    Attributes:
        name: Short identifier, for example "freshness".
        status: ok, warn or fail.
        message: One sentence explaining the verdict.
        value: The measured number behind the verdict, when there is one.
        details: Extra structured information (for example a number per month).
    """

    name: str
    status: str
    message: str
    value: float | None = None
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Convert to a plain dict for JSON.

        Returns:
            The result as a dictionary.
        """
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "value": self.value,
            "details": self.details,
        }


def overall_status(results: list[CheckResult]) -> str:
    """Combine several verdicts into one: the worst one wins.

    Args:
        results: Verdicts of all checks.

    Returns:
        "fail" if any check fails, else "warn" if any warns, else "ok".
    """
    statuses = {result.status for result in results}
    if FAIL in statuses:
        return FAIL
    return WARN if WARN in statuses else OK


def check_freshness(last_loaded_at: datetime | None, now: datetime, max_age_days: int) -> CheckResult:
    """Is the warehouse being updated?

    Args:
        last_loaded_at: When data was last loaded (timezone-aware), or None if never.
        now: The current time (timezone-aware).
        max_age_days: How old the last load may be.

    Returns:
        The verdict.
    """
    name = "freshness"
    if last_loaded_at is None:
        return CheckResult(name, WARN, "Nothing has been loaded into the warehouse yet.")
    age_days = (now - last_loaded_at).total_seconds() / 86400
    if age_days > max_age_days:
        return CheckResult(
            name,
            FAIL,
            f"The last load was {age_days:.1f} days ago (limit {max_age_days}).",
            round(age_days, 2),
        )
    return CheckResult(name, OK, f"The last load was {age_days:.1f} days ago.", round(age_days, 2))


def check_row_counts(rows_by_month: dict[str, int], tolerance_pct: float, min_months: int = 3) -> CheckResult:
    """Does any month look much bigger or smaller than the others?

    Each month is compared with the median of all the OTHER months, so one odd month cannot hide itself.
    Warns beyond the tolerance and fails beyond twice the tolerance.

    Args:
        rows_by_month: Rows loaded per month.
        tolerance_pct: Allowed deviation in percent.
        min_months: Fewer months than this cannot be compared.

    Returns:
        The verdict. `value` is the largest absolute deviation in percent.
    """
    name = "row_counts"
    if len(rows_by_month) < min_months:
        return CheckResult(
            name,
            OK,
            f"Only {len(rows_by_month)} month(s) loaded; at least {min_months} are needed to compare.",
        )
    deviations = {}
    for month, rows in rows_by_month.items():
        baseline = median(value for other, value in rows_by_month.items() if other != month)
        if baseline > 0:
            deviations[month] = round(100 * (rows - baseline) / baseline, 1)
    if not deviations:
        return CheckResult(name, OK, "Nothing to compare.")

    worst_month, worst = max(deviations.items(), key=lambda item: abs(item[1]))
    message = (
        f"Largest deviation from the median of the other months: {worst_month} {worst:+.1f}% "
        f"(tolerance +/-{tolerance_pct:g}%)."
    )
    details = {"deviation_pct_by_month": deviations}
    if abs(worst) > 2 * tolerance_pct:
        return CheckResult(name, FAIL, message, abs(worst), details)
    if abs(worst) > tolerance_pct:
        return CheckResult(name, WARN, message, abs(worst), details)
    return CheckResult(name, OK, message, abs(worst), details)


def check_quarantine_rate(summaries: list[dict], max_pct: float) -> CheckResult:
    """Is the cleaning service rejecting more rows than usual?

    Args:
        summaries: One dict per cleaned month with `year`, `month` and `pct_quarantined`.
        max_pct: The highest acceptable share of quarantined rows, in percent.

    Returns:
        The verdict. `value` is the highest quarantine percentage seen.
    """
    name = "quarantine_rate"
    if not summaries:
        return CheckResult(name, OK, "No cleaned months yet.")
    rates = {f"{item['year']}-{item['month']:02d}": float(item["pct_quarantined"]) for item in summaries}
    worst_month, worst = max(rates.items(), key=lambda item: item[1])
    message = f"Highest quarantine rate: {worst:.2f}% in {worst_month} (limit {max_pct:g}%)."
    details = {"pct_by_month": rates}
    if worst > max_pct:
        return CheckResult(name, FAIL, message, worst, details)
    if worst > 0.8 * max_pct:
        return CheckResult(name, WARN, message, worst, details)
    return CheckResult(name, OK, message, worst, details)


def check_schema_drift(reports: list[dict]) -> CheckResult:
    """Did a raw file arrive with columns we do not know?

    The cleaning service silently ignores unknown columns, so a new column from TLC would never show up
    anywhere. Its report lists them under `schema.unmapped_source_columns`; older reports lack that key
    and are skipped.

    Args:
        reports: Full cleaning reports, one per month.

    Returns:
        The verdict. `value` is the number of unknown columns.
    """
    name = "schema_drift"
    unknown = {}
    for report in reports:
        columns = (report.get("schema") or {}).get("unmapped_source_columns") or []
        if columns:
            unknown[f"{report['year']}-{report['month']:02d}"] = columns
    if unknown:
        listing = "; ".join(f"{month}: {', '.join(columns)}" for month, columns in unknown.items())
        return CheckResult(
            name,
            WARN,
            f"Raw files contain columns the pipeline ignores: {listing}. Decide whether to add them.",
            float(sum(len(columns) for columns in unknown.values())),
            {"unmapped_columns": unknown},
        )
    return CheckResult(name, OK, "Every column of the raw files is known to the pipeline.", 0.0)


def check_row_reconciliation(
    cleaned_rows: dict[str, int], loaded_rows: dict[str, int], fact_rows: dict[str, int]
) -> CheckResult:
    """Do the stages agree on how many rows each month has?

    cleaning report (rows published) = landing table (rows loaded) = fct_trips (rows modelled).

    Args:
        cleaned_rows: Clean rows per month according to the cleaning reports.
        loaded_rows: Rows per month in `landing.trips`.
        fact_rows: Rows per month in `analytics.fct_trips` (empty if dbt has not built it).

    Returns:
        The verdict. `value` is the number of disagreements.
    """
    name = "row_reconciliation"
    problems = []
    for month in sorted(loaded_rows):
        loaded = loaded_rows[month]
        cleaned = cleaned_rows.get(month)
        if cleaned is None:
            problems.append(f"{month}: loaded but there is no cleaning report")
        elif cleaned != loaded:
            problems.append(f"{month}: cleaning published {cleaned:,} rows but the warehouse loaded {loaded:,}")
        modelled = fact_rows.get(month, 0)
        if modelled != loaded:
            problems.append(f"{month}: landing has {loaded:,} rows but fct_trips has {modelled:,} (run dbt?)")
    if problems:
        return CheckResult(name, FAIL, "; ".join(problems), float(len(problems)), {"problems": problems})
    return CheckResult(name, OK, f"All {len(loaded_rows)} loaded month(s) reconcile across stages.", 0.0)


def check_dbt_last_run(last_run: dict | None, now: datetime, max_age_days: int) -> CheckResult:
    """Did the latest dbt run succeed, and is it recent?

    Args:
        last_run: The ETL service's summary of the latest dbt run, or None if dbt never ran.
        now: The current time (timezone-aware).
        max_age_days: How old the last run may be before we warn.

    Returns:
        The verdict. `value` is the age of the run in days.
    """
    name = "dbt_last_run"
    if last_run is None:
        return CheckResult(name, WARN, "dbt has not run yet.")
    if not last_run.get("success"):
        problems = ((last_run.get("results") or {}).get("problems")) or []
        return CheckResult(name, FAIL, f"The last dbt run failed ({len(problems)} problem(s) reported).")
    started = datetime.fromisoformat(last_run["started_at"])
    age_days = (now - started).total_seconds() / 86400
    if age_days > max_age_days:
        return CheckResult(
            name,
            WARN,
            f"The last successful dbt run was {age_days:.1f} days ago.",
            round(age_days, 2),
        )
    return CheckResult(name, OK, f"The last dbt run succeeded {age_days:.1f} days ago.", round(age_days, 2))
