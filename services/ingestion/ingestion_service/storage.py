# services/ingestion/ingestion_service/storage.py
"""Compatibility shim: the S3 client now lives in `shared/storage.py`.

More than one service needs object storage, and code used by several services
belongs in `shared/`. This re-export keeps `from .storage import ObjectStorage` working.
"""

from shared.storage import ObjectStorage

__all__ = ["ObjectStorage"]
