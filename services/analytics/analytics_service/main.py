# services/analytics/analytics_service/main.py
"""Entry point of the analytics API.

On startup it waits for the warehouse to accept connections. It does NOT require the dbt models
to exist yet: until they do, the data endpoints answer with a clear 503 message.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from shared.config import get_settings
from shared.logging_config import setup_logging
from shared.observability import setup_observability

from .database import Database
from .routes import register_error_handlers, router

settings = get_settings()
setup_logging("analytics", settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run start-up code before serving requests and clean-up code at shutdown."""
    database = Database.from_settings(settings)
    await asyncio.to_thread(database.wait_until_ready)
    app.state.db = database
    logger.info("Analytics service ready")
    yield
    database.close()


app = FastAPI(
    title="Analytics API",
    version="0.1.0",
    description="Read-only analytical questions over the warehouse's aggregate tables.",
    lifespan=lifespan,
)
register_error_handlers(app)
app.include_router(router)
setup_observability(app)


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness check: the process is running.

    Returns:
        A small JSON document describing the service.
    """
    return {"status": "ok", "service": "analytics", "environment": settings.environment}


@app.get("/health/ready", tags=["system"])
def ready(request: Request) -> dict:
    """Readiness check: the warehouse answers.

    Raises:
        HTTPException: 503 if the warehouse is not reachable.
    """
    if not request.app.state.db.is_reachable():
        raise HTTPException(status_code=503, detail="Warehouse is not reachable")
    return {"status": "ready"}
