# shared/observability.py
"""What every API service reports about itself: request metrics, request IDs and `/metrics`.

`setup_observability(app)` adds, to any FastAPI app:
* a middleware that counts requests and times them (by route *template*, so `/items/5` and
  `/items/6` are the same series: this keeps the number of series small and Prometheus happy),
* a request ID per request (taken from the `X-Request-ID` header, or generated), put into the
  logs and echoed back in the response header,
* a `/metrics` page that Prometheus reads.

Service-specific numbers (rows cleaned, files ingested...) live in each service's own `metrics.py`.
"""

import time
import uuid

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from shared.logging_config import request_id_var

HTTP_REQUESTS = Counter("taxi_http_requests_total", "HTTP requests handled", ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "taxi_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800),
)


def setup_observability(app: FastAPI) -> None:
    """Add metrics, request IDs and the `/metrics` endpoint to an app.

    Args:
        app: The FastAPI application.
    """

    @app.middleware("http")
    async def observe(request: Request, call_next):
        token = request_id_var.set(request.headers.get("x-request-id") or uuid.uuid4().hex[:12])
        started = time.perf_counter()
        status = 500  # what we record if the handler crashes
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id_var.get()
            return response
        finally:
            # The router stores the matched route in the scope; unknown paths have none.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route != "/metrics":
                HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
                HTTP_DURATION.labels(route).observe(time.perf_counter() - started)
            request_id_var.reset(token)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        """Prometheus reads this page every few seconds."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
