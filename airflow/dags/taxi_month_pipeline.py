# airflow/dags/taxi_month_pipeline.py
"""## Taxi month pipeline.

Takes ONE month of NYC yellow taxi data all the way from the TLC website to the warehouse:

`check_services` -> `resolve_target` -> `ingest_month` -> `clean_month` -> `load_month`
-> `build_warehouse` (dbt) -> `verify_month` -> `quality_gate`, with `ensure_zones` running beside it.

**Which month?** The `month` parameter if you give one. Otherwise the month of the run's
logical date (backfills: Jan, Feb, Mar...). Scheduled runs go back `PIPELINE_MONTH_LAG` months,
because TLC publishes late.

**Safe to repeat.** Every service skips work that is already done, so re-running or retrying
a task never creates duplicates. A month TLC has not published yet is *skipped*, not failed.
"""

import logging
import os
from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, get_current_context, task

try:  # the exception's location differs between Airflow 3 releases
    from airflow.sdk.exceptions import AirflowSkipException
except ImportError:  # pragma: no cover
    from airflow.exceptions import AirflowSkipException

from taxi_pipeline.alerts import notify_failure
from taxi_pipeline.months import (
    MonthResolutionError,
    month_label,
    normalise_run_type,
    resolve_target_month,
)
from taxi_pipeline.services import MonthNotAvailableError, PlatformApi

log = logging.getLogger("airflow.task")

DEFAULT_ARGS = {
    "owner": "data-platform",
    "retries": 2,  # try a failing task up to 3 times in total...
    "retry_delay": timedelta(minutes=2),  # ...waiting 2 minutes in between
    "on_failure_callback": notify_failure,
}

MONTH_PATTERN = r"^$|^\d{4}-(0[1-9]|1[0-2])$"


def _context_value(context, key):
    """Read a value from the Airflow context, returning None if it is missing."""
    try:
        return context.get(key)
    except (AttributeError, KeyError):
        return None


@task
def check_services() -> None:
    """Stop early (and clearly) if any service is down."""
    PlatformApi.from_env().wait_ready()
    log.info("Ingestion, cleaning and ETL services are all ready.")


@task
def ensure_zones() -> dict:
    """Make sure the zone lookup table is in the warehouse (dbt needs it)."""
    result = PlatformApi.from_env().ensure_zones()
    log.info("Zones: %s", result)
    return result


@task
def resolve_target() -> dict:
    """Decide which month this run processes, and pass the run settings on."""
    context = get_current_context()
    params = _context_value(context, "params") or {}
    try:
        year, month = resolve_target_month(
            param_month=params.get("month"),
            logical_date=_context_value(context, "logical_date"),
            data_interval_start=_context_value(context, "data_interval_start"),
            run_type=normalise_run_type(getattr(_context_value(context, "dag_run"), "run_type", "")),
            lag_months=int(os.environ.get("PIPELINE_MONTH_LAG", "0")),
        )
    except MonthResolutionError as exc:
        raise ValueError(str(exc)) from exc

    target = {
        "year": year,
        "month": month,
        "label": month_label(year, month),
        "force": bool(params.get("force")),
        "full_refresh": bool(params.get("full_refresh")),
    }
    log.info("This run processes %s (force=%s)", target["label"], target["force"])
    return target


@task(execution_timeout=timedelta(minutes=30))
def ingest_month(target: dict) -> dict:
    """Download the month from TLC into the raw bucket (skip if TLC has not published it)."""
    try:
        item = PlatformApi.from_env().ingest_month(target["year"], target["month"])
    except MonthNotAvailableError as exc:
        # Not an error: the data does not exist yet. Everything after this task is skipped.
        raise AirflowSkipException(f"{target['label']} is not published by TLC yet. {exc}") from exc
    return {"status": item["status"], "rows": (item.get("file") or {}).get("row_count")}


@task(execution_timeout=timedelta(hours=1))
def clean_month(target: dict) -> dict:
    """Validate and standardise the month (raw to clean + quarantine)."""
    item = PlatformApi.from_env().clean_month(target["year"], target["month"], target["force"])
    counts = (item.get("report") or {}).get("counts", {})
    log.info("Cleaning %s: %s", target["label"], item.get("message"))
    return {
        "status": item["status"],
        **{k: counts.get(k) for k in ("rows_in", "rows_clean", "rows_quarantined")},
    }


@task(execution_timeout=timedelta(hours=1))
def load_month(target: dict) -> dict:
    """Load the cleaned month into the warehouse's landing table."""
    item = PlatformApi.from_env().load_month(target["year"], target["month"], target["force"])
    log.info("Loading %s: %s", target["label"], item.get("message"))
    return {"status": item["status"], "rows_loaded": (item.get("load") or {}).get("rows_loaded")}


@task(retries=1, execution_timeout=timedelta(hours=1))
def build_warehouse(target: dict) -> dict:
    """Run dbt (seeds, models and tests) to rebuild the star schema."""
    result = PlatformApi.from_env().run_dbt("build", full_refresh=target["full_refresh"])
    log.info("dbt build finished: %s", result)
    return result


@task
def verify_month(target: dict) -> dict:
    """Check that cleaning and the warehouse agree on the number of rows."""
    result = PlatformApi.from_env().verify_month(target["year"], target["month"])
    log.info("Verified: %s", result)
    return result


@task(retries=0)  # re-running a failed data check would only repeat the same answer
def quality_gate() -> dict:
    """Run the data-quality checks and fail the run if any check fails."""
    result = PlatformApi.from_env().run_quality_checks()
    log.info("Quality gate: %s", result)
    return result


@dag(
    dag_id="taxi_month_pipeline",
    description="Ingest, clean, load and model one month of NYC yellow taxi data.",
    schedule="@monthly",
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,  # unpausing does not trigger every missed month; use a backfill for that
    max_active_runs=1,  # one month at a time: the heavy services process one job at a time anyway
    default_args=DEFAULT_ARGS,
    params={
        "month": Param(
            "",
            type="string",
            pattern=MONTH_PATTERN,
            description="YYYY-MM to process. Leave empty to use the run's logical date.",
        ),
        "force": Param(False, type="boolean", description="Clean and load again even if already done."),
        "full_refresh": Param(False, type="boolean", description="Rebuild the dbt incremental model from scratch."),
    },
    tags=["taxi", "pipeline"],
    doc_md=__doc__,
)
def taxi_month_pipeline():
    """Describe the order of the tasks (the actual work is in the functions above)."""
    ready = check_services()
    zones = ensure_zones()
    target = resolve_target()
    ingested = ingest_month(target)
    cleaned = clean_month(target)
    loaded = load_month(target)
    built = build_warehouse(target)
    verified = verify_month(target)
    quality = quality_gate()

    ready >> [zones, target]
    target >> ingested >> cleaned >> loaded
    [zones, loaded] >> built >> verified >> quality


taxi_month_pipeline()
