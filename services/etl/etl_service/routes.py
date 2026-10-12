# services/etl/etl_service/routes.py
"""HTTP endpoints of the ETL service."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from .landing import SchemaContractError
from .loader import LoaderService, NotCleanedError, ZoneFileNotFoundError
from .metrics import record_dbt, record_load
from .schemas import LoadRequest, LoadResponse, LoadResult, TransformRequest
from .transform import TransformBusyError, TransformRunner
from .warehouse import Warehouse

logger = logging.getLogger(__name__)
router = APIRouter()


def get_loader(request: Request) -> LoaderService:
    """Dependency: the shared LoaderService (set up in main.py)."""
    return request.app.state.loader


def get_transformer(request: Request) -> TransformRunner:
    """Dependency: the shared TransformRunner (set up in main.py)."""
    return request.app.state.transformer


def get_warehouse(request: Request) -> Warehouse:
    """Dependency: the shared Warehouse (set up in main.py)."""
    return request.app.state.warehouse


LoaderDep = Annotated[LoaderService, Depends(get_loader)]
TransformerDep = Annotated[TransformRunner, Depends(get_transformer)]
WarehouseDep = Annotated[Warehouse, Depends(get_warehouse)]


@router.post(
    "/load/trips",
    response_model=LoadResponse,
    tags=["load"],
    summary="Load cleaned months into the warehouse (landing.trips)",
)
def load_trips(body: LoadRequest, loader: LoaderDep) -> LoadResponse:
    """Bulk-load cleaned months into PostgreSQL.

    Each month is replaced in one transaction (all or nothing). A month already loaded from the same
    cleaning run is skipped unless `force` is true. One failing month never stops the others.
    """
    results = []
    for year, month in body.months():
        label = f"{year}-{month:02d}"
        try:
            outcome = loader.load_month(year, month, force=body.force)
            record = outcome.record
            record_load(outcome.status, record)
            if outcome.status == "loaded":
                message = f"Loaded {record['rows_loaded']:,} rows into landing.trips in {record['duration_seconds']}s."
            else:
                message = "Already loaded from the same cleaning run. Use force=true to reload."
            results.append(LoadResult(label=label, status=outcome.status, message=message, load=record))
        except NotCleanedError as exc:
            record_load("not_cleaned")
            results.append(LoadResult(label=label, status="not_cleaned", message=str(exc)))
        except SchemaContractError as exc:
            record_load("rejected")
            results.append(LoadResult(label=label, status="rejected", message=str(exc)))
        except Exception as exc:  # keep going with the other months
            logger.exception("Loading %s failed", label)
            record_load("failed")
            results.append(LoadResult(label=label, status="failed", message=f"{type(exc).__name__}: {exc}"))
    return LoadResponse(results=results)


@router.post("/load/zones", tags=["load"], summary="Load the taxi zone lookup table")
def load_zones(loader: LoaderDep) -> dict:
    """Load zone IDs with borough and zone names into `landing.zones`.

    Raises:
        HTTPException: 404 if the zone file was never ingested.
    """
    try:
        outcome = loader.load_zones()
    except ZoneFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": outcome.status, **outcome.record}


@router.get("/load/status", tags=["load"], summary="Which months are loaded")
def load_status(warehouse: WarehouseDep) -> dict:
    """List one entry per month loaded into the warehouse."""
    months = warehouse.list_load_log()
    return {"count": len(months), "months": months}


@router.post("/transform/run", tags=["transform"], summary="Run dbt (seeds, models and tests)")
def transform_run(body: TransformRequest, runner: TransformerDep) -> dict:
    """Run dbt. The answer has `success`, counts per status, any problems, and the end of the log.

    A failing test or model is reported in the answer (`success: false`), not as an HTTP error.

    Raises:
        HTTPException: 409 if another dbt run is in progress; 422 for an invalid selector.
    """
    try:
        summary = runner.run(body.command, body.select, body.full_refresh)
    except TransformBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_dbt(summary)
    return summary


@router.post("/transform/docs", tags=["transform"], summary="Generate the dbt documentation site")
def transform_docs(runner: TransformerDep) -> dict:
    """Generate dbt's documentation (open it at /dbt-docs/).

    Raises:
        HTTPException: 409 if another dbt run is in progress.
    """
    try:
        return runner.generate_docs()
    except TransformBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/transform/last-run", tags=["transform"], summary="Summary of the latest dbt run")
def transform_last_run(runner: TransformerDep) -> dict:
    """Return the summary of the most recent dbt run.

    Raises:
        HTTPException: 404 if dbt has not run yet.
    """
    last = runner.last_run()
    if last is None:
        raise HTTPException(status_code=404, detail="dbt has not run yet")
    return last
