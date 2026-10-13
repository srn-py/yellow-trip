# airflow/dags/taxi_retry_demo.py
"""## Retry and failure demo.

A harmless practice DAG that shows what Airflow does when a task fails.

* `flaky_step` fails on its first two attempts, then succeeds. Watch it go yellow
  ("up for retry") twice and then green.
* `maybe_break` fails for good if you start the run with `permanent_failure` ticked.
  Watch it use its retries, turn red, and trigger the failure alert (look for
  `PIPELINE ALERT` in the task log). The tasks after it then show as "upstream failed".
"""

import logging
from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, get_current_context, task
from taxi_pipeline.alerts import notify_failure

log = logging.getLogger("airflow.task")


@task(retries=3, retry_delay=timedelta(seconds=15))
def flaky_step() -> str:
    """Fail twice, then succeed (simulates a temporary problem such as a network blip)."""
    attempt = get_current_context()["ti"].try_number
    if attempt < 3:
        raise RuntimeError(f"Simulated temporary failure on attempt {attempt}")
    log.info("Succeeded on attempt %s", attempt)
    return f"ok after {attempt} attempts"


@task(retries=1, retry_delay=timedelta(seconds=10))
def maybe_break() -> None:
    """Fail every time if `permanent_failure` is ticked."""
    if get_current_context()["params"].get("permanent_failure"):
        raise RuntimeError("Simulated permanent failure")
    log.info("Nothing broke.")


@task
def finish() -> None:
    """Runs only if everything before it succeeded."""
    log.info("All steps succeeded.")


@dag(
    dag_id="taxi_retry_demo",
    description="Practice DAG: retries, failures and alerts.",
    schedule=None,
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    default_args={"owner": "data-platform", "on_failure_callback": notify_failure},
    params={"permanent_failure": Param(False, type="boolean", description="Make `maybe_break` fail for good.")},
    tags=["demo"],
    doc_md=__doc__,
)
def taxi_retry_demo():
    """Three tasks in a row."""
    flaky_step() >> maybe_break() >> finish()


taxi_retry_demo()
