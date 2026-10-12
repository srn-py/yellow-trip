# airflow/dags/taxi_dbt_rebuild.py
"""## Rebuild the warehouse models.

Runs dbt (through the ETL service) without touching any data files. Start it by hand.
Useful after you edit a dbt model, or with `full_refresh` to rebuild `fct_trips` from scratch.

Careful with `select`: `fct_trips+` builds that model and everything AFTER it, but not
what it depends on. Leave it empty to build everything.
"""

import logging
from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, get_current_context, task
from taxi_pipeline.alerts import notify_failure
from taxi_pipeline.services import PlatformApi

log = logging.getLogger("airflow.task")


@task
def check_services() -> None:
    """Stop early (and clearly) if any service is down."""
    PlatformApi.from_env().wait_ready()


@task(execution_timeout=timedelta(hours=1))
def run_dbt() -> dict:
    """Run the chosen dbt command and fail the task if dbt reports any problem."""
    params = get_current_context()["params"]
    result = PlatformApi.from_env().run_dbt(
        params["command"], params.get("select") or None, bool(params.get("full_refresh"))
    )
    log.info("dbt finished: %s", result)
    return result


@dag(
    dag_id="taxi_dbt_rebuild",
    description="Run dbt on demand (no schedule).",
    schedule=None,
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "on_failure_callback": notify_failure,
    },
    params={
        "command": Param("build", enum=["build", "run", "test", "seed"], description="dbt command."),
        "select": Param(
            "",
            type="string",
            pattern=r"^$|^[A-Za-z0-9_][A-Za-z0-9_.+*:@, ]*$",
            description="Optional dbt selector. Empty builds everything.",
        ),
        "full_refresh": Param(False, type="boolean", description="Rebuild incremental models from scratch."),
    },
    tags=["taxi", "dbt"],
    doc_md=__doc__,
)
def taxi_dbt_rebuild():
    """Check the services, then run dbt."""
    check_services() >> run_dbt()


taxi_dbt_rebuild()
