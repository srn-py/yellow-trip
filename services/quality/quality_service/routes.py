# services/quality/quality_service/routes.py
"""HTTP endpoints of the quality service."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from .monitor import QualityMonitor

router = APIRouter()


def get_monitor(request: Request) -> QualityMonitor:
    """Dependency: the shared QualityMonitor (set up in main.py). Tests replace it with a fake."""
    return request.app.state.monitor


MonitorDep = Annotated[QualityMonitor, Depends(get_monitor)]


@router.post("/checks/run", tags=["checks"], summary="Run all data-quality checks now")
def run_checks(monitor: MonitorDep) -> dict:
    """Run every check and return the verdicts. Used by the Airflow quality gate."""
    return monitor.run_checks()


@router.get("/checks/latest", tags=["checks"], summary="The most recent check result")
def latest_checks(monitor: MonitorDep) -> dict:
    """Return the result of the most recent run.

    Raises:
        HTTPException: 404 if no run has finished yet (the first one starts shortly after start-up).
    """
    result = monitor.latest()
    if result is None:
        raise HTTPException(status_code=404, detail="No quality check has run yet.")
    return result
