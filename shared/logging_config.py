# shared/logging_config.py
"""Consistent logging for every service.

Two output formats, chosen with the LOG_FORMAT environment variable:

* ``text`` (default): easy to read while you develop.
* ``json``: one JSON object per line. This is what log tools (Loki, ELK, CloudWatch) can search and
  filter, so it is the format to use on a server.

Every line also carries the ID of the request being handled (see `shared/observability.py`), so all
log lines of one request can be found together. Extra fields passed with `extra={...}` appear in JSON.
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# ID of the request being handled ("-" outside a request). Set by the middleware in observability.py.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Libraries that are very chatty at DEBUG level; keep them quiet.
_NOISY_LIBRARIES = ("boto3", "botocore", "urllib3", "httpx", "httpcore")

# Attributes every LogRecord has. Anything else was added through `extra=` and goes into JSON output.
_STANDARD_ATTRIBUTES = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class _RequestIdFilter(logging.Filter):
    """Stamps every record with the current request ID."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add `request_id` to the record and let it through."""
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Formats each log record as one line of JSON."""

    def __init__(self, service_name: str):
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Turn a record into a JSON string.

        Args:
            record: The log record.

        Returns:
            One line of JSON.
        """
        payload = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRIBUTES and key != "request_id":
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(service_name: str, level: str = "INFO", log_format: str | None = None) -> None:
    """Configure the root logger for a service.

    Args:
        service_name: Short name printed in every log line, e.g. "ingestion".
        level: Minimum severity to show (DEBUG, INFO, WARNING, ERROR).
        log_format: "text" or "json". Defaults to the LOG_FORMAT environment variable, then "text".
    """
    chosen = (log_format or os.environ.get("LOG_FORMAT", "text")).lower()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if chosen == "json":
        handler.setFormatter(JsonFormatter(service_name))
    else:
        handler.setFormatter(
            logging.Formatter(
                f"%(asctime)s | %(levelname)-8s | {service_name} | %(request_id)s | %(name)s | %(message)s"
            )
        )

    root = logging.getLogger()
    root.handlers.clear()  # Avoid duplicated lines if this is called twice.
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
