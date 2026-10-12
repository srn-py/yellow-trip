# tests/conftest.py
"""Fixtures (reusable test building blocks) shared by all tests."""

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cleaning_service.cleaner import CleaningService
from ingestion_service.ingest import IngestionService
from ingestion_service.registry import FileRegistry

from shared.config import Settings

RAW_TRIP_KEY = "yellow_tripdata/year=2024/month=01/yellow_tripdata_2024-01.parquet"


class FakeStorage:
    """In-memory replacement for ObjectStorage so tests need no running server."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, bucket, key, local_path, content_type=None, metadata=None):
        self.objects[(bucket, key)] = Path(local_path).read_bytes()

    def download_file(self, bucket, key, local_path):
        Path(local_path).write_bytes(self.objects[(bucket, key)])

    def put_bytes(self, bucket, key, data, content_type=None):
        self.objects[(bucket, key)] = data

    def get_bytes(self, bucket, key):
        return self.objects[(bucket, key)]

    def object_exists(self, bucket, key):
        return (bucket, key) in self.objects

    def list_objects(self, bucket, prefix=""):
        return [
            {"key": key, "size_bytes": len(data), "last_modified": ""}
            for (obj_bucket, key), data in sorted(self.objects.items())
            if obj_bucket == bucket and key.startswith(prefix)
        ]


class FakeIngestionClient:
    """Stand-in for the ingestion API client: returns registry records from a dict."""

    def __init__(self, records=None):
        self.records = records or {}

    def get_trip_file(self, year, month):
        return self.records.get((year, month))

    def is_reachable(self):
        return True


@pytest.fixture
def fake_storage():
    return FakeStorage()


@pytest.fixture
def settings():
    return Settings(_env_file=None)  # defaults only; ignores any local .env


@pytest.fixture
def registry(tmp_path):
    return FileRegistry(str(tmp_path / "registry.db"))


@pytest.fixture
def service(fake_storage, registry, settings):
    return IngestionService(fake_storage, registry, settings)


@pytest.fixture
def sample_parquet(tmp_path) -> Path:
    """A tiny Parquet file (3 rows) named like an official TLC file."""
    path = tmp_path / "yellow_tripdata_2024-01.parquet"
    pq.write_table(pa.table({"fare_amount": [10.0, 12.5, 7.0]}), path)
    return path


# ---------------------------------------------------------------------------
# Cleaning-service fixtures
# ---------------------------------------------------------------------------

_TRIP_SCHEMA = pa.schema(
    [
        ("VendorID", pa.int32()),
        ("tpep_pickup_datetime", pa.timestamp("us")),
        ("tpep_dropoff_datetime", pa.timestamp("us")),
        ("passenger_count", pa.int64()),
        ("trip_distance", pa.float64()),
        ("RatecodeID", pa.int64()),
        ("store_and_fwd_flag", pa.string()),
        ("PULocationID", pa.int32()),
        ("DOLocationID", pa.int32()),
        ("payment_type", pa.int64()),
        ("fare_amount", pa.float64()),
        ("extra", pa.float64()),
        ("mta_tax", pa.float64()),
        ("tip_amount", pa.float64()),
        ("tolls_amount", pa.float64()),
        ("improvement_surcharge", pa.float64()),
        ("total_amount", pa.float64()),
        ("congestion_surcharge", pa.float64()),
        ("Airport_fee", pa.float64()),
    ]
)


def _trip(**overrides):
    """One good taxi trip in TLC's original column names; override fields to break it."""
    base = {
        "VendorID": 1,
        "tpep_pickup_datetime": datetime(2024, 1, 10, 8, 0),
        "tpep_dropoff_datetime": datetime(2024, 1, 10, 8, 20),
        "passenger_count": 1,
        "trip_distance": 3.0,
        "RatecodeID": 1,
        "store_and_fwd_flag": "N",
        "PULocationID": 100,
        "DOLocationID": 200,
        "payment_type": 1,
        "fare_amount": 15.0,
        "extra": 0.5,
        "mta_tax": 0.5,
        "tip_amount": 3.0,
        "tolls_amount": 0.0,
        "improvement_surcharge": 1.0,
        "total_amount": 20.0,
        "congestion_surcharge": 2.5,
        "Airport_fee": 0.0,
    }
    return {**base, **overrides}


@pytest.fixture
def trip_source_file(tmp_path) -> Path:
    """A raw-style January 2024 file with 10 rows: 4 clean and 6 that must be quarantined.

    Note it has `Airport_fee` (capital A) and no `cbd_congestion_fee` column,
    like the real 2024 files, to exercise renaming and NULL-filling.
    """
    rows = [
        _trip(),  # 1 clean
        _trip(  # 2 clean
            tpep_pickup_datetime=datetime(2024, 1, 10, 9, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 10, 9, 30),
            passenger_count=2,
            trip_distance=5.0,
            payment_type=2,
            total_amount=25.0,
        ),
        _trip(  # 3 clean: flex fare, fields missing (kept and flagged)
            tpep_pickup_datetime=datetime(2024, 1, 11, 10, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 11, 10, 15),
            passenger_count=None,
            RatecodeID=None,
            store_and_fwd_flag=None,
            congestion_surcharge=None,
            Airport_fee=None,
            payment_type=0,
            trip_distance=2.0,
            fare_amount=10.0,
            total_amount=12.0,
        ),
        _trip(  # 4 quarantine: negative fare and total
            tpep_pickup_datetime=datetime(2024, 1, 12, 9, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 12, 9, 20),
            fare_amount=-5.0,
            total_amount=-5.0,
            tip_amount=0.0,
        ),
        _trip(  # 5 quarantine: zero distance
            tpep_pickup_datetime=datetime(2024, 1, 13, 8, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 13, 8, 10),
            trip_distance=0.0,
            total_amount=8.0,
        ),
        _trip(  # 6 quarantine: drop-off before pickup
            tpep_pickup_datetime=datetime(2024, 1, 14, 11, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 14, 10, 30),
        ),
        _trip(  # 7 quarantine: pickup outside the file's month
            tpep_pickup_datetime=datetime(2023, 12, 31, 23, 0),
            tpep_dropoff_datetime=datetime(2023, 12, 31, 23, 30),
        ),
        _trip(),  # 8 quarantine: exact duplicate of row 1
        _trip(  # 9 clean: zero passengers (kept and flagged)
            tpep_pickup_datetime=datetime(2024, 1, 15, 14, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 15, 14, 20),
            passenger_count=0,
            total_amount=18.0,
        ),
        _trip(  # 10 quarantine: 300 mph
            tpep_pickup_datetime=datetime(2024, 1, 16, 12, 0),
            tpep_dropoff_datetime=datetime(2024, 1, 16, 12, 6),
            trip_distance=30.0,
            fare_amount=70.0,
            total_amount=80.0,
        ),
    ]
    path = tmp_path / "source.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=_TRIP_SCHEMA), path)
    return path


@pytest.fixture
def ingestion_client():
    """A fake ingestion client that knows one registered file: January 2024."""
    record = {
        "id": 1,
        "sha256": "abc123",
        "filename": "yellow_tripdata_2024-01.parquet",
        "dataset": "yellow_tripdata",
        "file_format": "parquet",
        "bucket": "raw",
        "object_key": RAW_TRIP_KEY,
        "row_count": 10,
        "year": 2024,
        "month": 1,
    }
    return FakeIngestionClient({(2024, 1): record})


@pytest.fixture
def cleaning_service(fake_storage, ingestion_client, trip_source_file, settings):
    """A CleaningService wired to fakes, with the January source file already 'in the lake'."""
    fake_storage.objects[("raw", RAW_TRIP_KEY)] = trip_source_file.read_bytes()
    return CleaningService(fake_storage, ingestion_client, settings)
