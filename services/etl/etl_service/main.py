# services/etl/etl_service/main.py
"""Entry point of the ETL service.

On startup the service connects to object storage and PostgreSQL (waiting for them if needed),
creates the landing tables, and builds the objects the endpoints use. It also serves the dbt
documentation site, once generated, at `/dbt-docs/`.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from shared.config import get_settings
from shared.logging_config import setup_logging
from shared.observability import setup_observability
from shared.storage import ObjectStorage

from .clients import CleaningClient, IngestionClient
from .loader import LoaderService
from .routes import router
from .transform import TransformRunner
from .warehouse import Warehouse

settings = get_settings()
setup_logging("etl", settings.log_level)
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

    warehouse = Warehouse.from_settings(settings)
    await asyncio.to_thread(warehouse.wait_until_ready)
    await asyncio.to_thread(warehouse.ensure_schema)

    cleaning_client = CleaningClient(settings.cleaning_url)
    ingestion_client = IngestionClient(settings.ingestion_url)
    app.state.storage = storage
    app.state.warehouse = warehouse
    app.state.loader = LoaderService(storage, cleaning_client, ingestion_client, warehouse, settings)
    app.state.transformer = TransformRunner(settings)
    logger.info("ETL service ready")
    yield


app = FastAPI(
    title="ETL Service",
    version="0.1.0",
    description="Loads clean data into the PostgreSQL warehouse and runs dbt transformations.",
    lifespan=lifespan,
)
app.include_router(router)
setup_observability(app)

# dbt writes its documentation site into <project>/target. Serve it as static files.
_docs_dir = Path(settings.dbt_project_dir) / "target"
try:
    _docs_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/dbt-docs", StaticFiles(directory=_docs_dir, html=True), name="dbt-docs")
except OSError:
    logger.warning("dbt docs folder %s is not writable; /dbt-docs is disabled", _docs_dir)


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness check: the process is running.

    Returns:
        A small JSON document describing the service.
    """
    return {"status": "ok", "service": "etl", "environment": settings.environment}


@app.get("/health/ready", tags=["system"])
def ready(request: Request) -> dict:
    """Readiness check: object storage and the warehouse both answer.

    Raises:
        HTTPException: 503 if either dependency does not answer.
    """
    if not request.app.state.storage.is_reachable():
        raise HTTPException(status_code=503, detail="Object storage is not reachable")
    if not request.app.state.warehouse.is_reachable():
        raise HTTPException(status_code=503, detail="Warehouse is not reachable")
    return {"status": "ready"}
