# services/cleaning/cleaning_service/routes.py
"""HTTP endpoints of the cleaning service."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from .cleaner import (
    CleaningService,
    SourceNotFoundError,
    UnsupportedSourceError,
)
from .metrics import record_outcome
from .schemas import CleanRequest, CleanResponse, MonthResult
from .sql_builder import SchemaMismatchError

logger = logging.getLogger(__name__)
router = APIRouter()


def get_cleaning_service(request: Request) -> CleaningService:
    """Dependency that hands each endpoint the shared CleaningService (set up in main.py)."""
    return request.app.state.cleaning_service


ServiceDep = Annotated[CleaningService, Depends(get_cleaning_service)]


@router.post(
    "/clean/trips",
    response_model=CleanResponse,
    tags=["cleaning"],
    summary="Clean one or more months of raw trip data",
)
def clean_trips(body: CleanRequest, service: ServiceDep) -> CleanResponse:
    """Validate and standardise raw months into the clean and quarantine buckets.

    Each month reports its own status; one failing month never stops the others.
    A month already cleaned with the same source file and rules is skipped unless `force` is true.
    """
    results = []
    for year, month in body.months():
        label = f"{year}-{month:02d}"
        try:
            outcome = service.clean_month(year, month, force=body.force)
            record_outcome(outcome.status, outcome.report)
            counts = outcome.report["counts"]
            if outcome.status == "cleaned":
                message = (
                    f"Cleaned {counts['rows_in']:,} rows: {counts['rows_clean']:,} kept, "
                    f"{counts['rows_quarantined']:,} quarantined ({counts['pct_quarantined']}%)."
                )
            else:
                message = "Already cleaned with the same source file and rules. Use force=true to redo."
            results.append(MonthResult(label=label, status=outcome.status, message=message, report=outcome.report))
        except SourceNotFoundError as exc:
            record_outcome("not_ingested")
            results.append(MonthResult(label=label, status="not_ingested", message=str(exc)))
        except (UnsupportedSourceError, SchemaMismatchError) as exc:
            record_outcome("rejected")
            results.append(MonthResult(label=label, status="rejected", message=str(exc)))
        except Exception as exc:  # Keep going with the other months; log the details.
            logger.exception("Cleaning %s failed", label)
            record_outcome("failed")
            results.append(MonthResult(label=label, status="failed", message=f"{type(exc).__name__}: {exc}"))
    return CleanResponse(results=results)


@router.get("/reports/trips", tags=["reports"], summary="Summaries of all cleaning reports")
def list_reports(service: ServiceDep) -> dict:
    """List one summary line per cleaned month."""
    reports = service.list_reports()
    return {"count": len(reports), "reports": reports}


@router.get("/reports/trips/{year}/{month}", tags=["reports"], summary="Full cleaning report of one month")
def get_report(year: int, month: int, service: ServiceDep) -> dict:
    """Return the full cleaning report of a month.

    Raises:
        HTTPException: 404 if the month has not been cleaned.
    """
    report = service.get_report(year, month)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No cleaning report for {year}-{month:02d}")
    return report
