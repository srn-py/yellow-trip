# services/cleaning/cleaning_service/main.py
"""Entry point of the cleaning service.

On startup the service connects to object storage (creating the buckets if needed)
and builds the `CleaningService` used by the endpoints.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from shared.config import get_settings
from shared.logging_config import setup_logging
from shared.observability import setup_observability
from shared.storage import ObjectStorage

from .cleaner import CleaningService
from .ingestion_client import IngestionClient
from .routes import router

settings = get_settings()
setup_logging("cleaning", settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run start-up code before serving requests."""
    storage = ObjectStorage(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_region,
    )
    buckets = [settings.bucket_raw, settings.bucket_clean, settings.bucket_quarantine]
    await asyncio.to_thread(storage.wait_until_ready, buckets)

    ingestion_client = IngestionClient(settings.ingestion_url)
    app.state.storage = storage
    app.state.ingestion_client = ingestion_client
    app.state.cleaning_service = CleaningService(storage, ingestion_client, settings)
    logger.info("Cleaning service ready")
    yield


app = FastAPI(
    title="Cleaning Service",
    version="0.1.0",
    description="Validates and standardises raw trip data into clean and quarantine layers.",
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
    return {"status": "ok", "service": "cleaning", "environment": settings.environment}


@app.get("/health/ready", tags=["system"])
def ready(request: Request) -> dict:
    """Readiness check: storage and the ingestion service are both reachable.

    Raises:
        HTTPException: 503 if either dependency does not answer.
    """
    if not request.app.state.storage.is_reachable():
        raise HTTPException(status_code=503, detail="Object storage is not reachable")
    if not request.app.state.ingestion_client.is_reachable():
        raise HTTPException(status_code=503, detail="Ingestion service is not reachable")
    return {"status": "ready"}
