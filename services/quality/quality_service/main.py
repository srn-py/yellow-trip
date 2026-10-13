# services/quality/quality_service/main.py
"""Entry point of the data-quality service.

After start-up it waits a short while (the other services may still be starting), then runs all
checks every `QUALITY_INTERVAL_SECONDS` in a background task. Results appear at `/checks/latest`
and as Prometheus metrics.
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from shared.config import get_settings
from shared.logging_config import setup_logging
from shared.observability import setup_observability

from .monitor import QualityMonitor
from .routes import router
from .settings import get_quality_settings
from .sources import PlatformSources, Warehouse

settings = get_settings()
setup_logging("quality", settings.log_level)
logger = logging.getLogger(__name__)


async def monitor_loop(monitor: QualityMonitor, delay_seconds: int, interval_seconds: int) -> None:
    """Run the checks forever, a failed run never stops the loop.

    Args:
        monitor: The monitor to run.
        delay_seconds: Wait before the first run.
        interval_seconds: Wait between runs.
    """
    await asyncio.sleep(delay_seconds)
    while True:
        try:
            await asyncio.to_thread(monitor.run_checks)
        except Exception:
            logger.exception("A quality check run failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the monitor and start its background loop."""
    quality = get_quality_settings()
    sources = PlatformSources(Warehouse.from_settings(settings), settings.cleaning_url, settings.etl_url)
    monitor = QualityMonitor(sources, quality)
    app.state.monitor = monitor
    task = asyncio.create_task(
        monitor_loop(monitor, quality.quality_startup_delay_seconds, quality.quality_interval_seconds)
    )
    logger.info("Quality service ready")
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="Data Quality Service",
    version="0.1.0",
    description="Continuously checks that the platform's data is fresh, complete and consistent.",
    lifespan=lifespan,
)
app.include_router(router)
setup_observability(app)


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness check: the process is running.

    Returns:
        A small JSON document describing the service.
    """
    return {"status": "ok", "service": "quality", "environment": settings.environment}


@app.get("/health/ready", tags=["system"])
def ready() -> dict:
    """Readiness check. The service has no hard dependencies, so it is ready once it runs.

    Returns:
        A small JSON document.
    """
    return {"status": "ready"}
