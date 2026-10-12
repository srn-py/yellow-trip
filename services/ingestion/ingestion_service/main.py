# services/ingestion/ingestion_service/main.py
"""Entry point of the ingestion service.

On startup (see `lifespan`) the service:
1. waits for object storage and creates the buckets,
2. opens the file registry,
3. starts the drop-folder watcher in the background.
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request

from shared.config import get_settings
from shared.logging_config import setup_logging
from shared.observability import setup_observability

from .dropzone import DropzoneWatcher
from .ingest import IngestionService
from .registry import FileRegistry
from .routes import router
from .storage import ObjectStorage

settings = get_settings()
setup_logging("ingestion", settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run start-up code before serving requests and clean-up code at shutdown."""
    storage = ObjectStorage(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_region,
    )
    buckets = [settings.bucket_raw, settings.bucket_clean, settings.bucket_quarantine]
    await asyncio.to_thread(storage.wait_until_ready, buckets)  # blocking call off the event loop

    registry = FileRegistry(settings.registry_db_path)
    service = IngestionService(storage, registry, settings)
    app.state.storage = storage
    app.state.ingestion_service = service

    watcher = DropzoneWatcher(settings.dropzone_dir, service, settings.dropzone_poll_seconds)
    watcher_task = asyncio.create_task(watcher.run_forever())
    logger.info("Ingestion service ready")

    yield  # ---- the application serves requests while we are paused here ----

    watcher_task.cancel()
    with suppress(asyncio.CancelledError):
        await watcher_task


app = FastAPI(
    title="Ingestion Service",
    version="0.2.0",
    description="Brings taxi trip data files into the raw layer of the data lake.",
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
    return {"status": "ok", "service": "ingestion", "environment": settings.environment}


@app.get("/health/ready", tags=["system"])
def ready(request: Request) -> dict:
    """Readiness check: the service can really do its job (storage is reachable).

    Raises:
        HTTPException: 503 if object storage does not answer.
    """
    if not request.app.state.storage.is_reachable():
        raise HTTPException(status_code=503, detail="Object storage is not reachable")
    return {"status": "ready"}
