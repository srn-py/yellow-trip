# services/cleaning/cleaning_service/contract.py
"""The data contract: what every clean file MUST look like, checked with Pandera.

The SQL rules *produce* clean data. This contract independently *verifies* it, as a second
line of defence ("trust, but verify"). If a rule has a bug and bad rows slip through, the
contract fails and the month is NOT published.

The check streams the file in chunks, so memory stays small even for millions of rows.
"""

import logging
from pathlib import Path

import pyarrow.parquet as pq
from pandera.errors import SchemaError, SchemaErrors

try:
    import pandera.pandas as pa  # Pandera 0.24 and newer
except ImportError:  # pragma: no cover - older Pandera
    import pandera as pa

from shared.config import Settings

from .rules import MAX_ZONE_ID

logger = logging.getLogger(__name__)


class ContractViolationError(RuntimeError):
    """Raised when cleaned data breaks the data contract (a bug in our rules)."""


def build_clean_schema(settings: Settings):
    """Describe the guarantees for the clean dataset.

    Leaving out `dtype` on purpose: pandas turns integer columns with NULLs into floats, so
    types are guaranteed by the explicit SQL casts instead. This contract focuses on
    which columns exist, which may be NULL, and which values are allowed.

    Args:
        settings: Application settings (thresholds).

    Returns:
        A Pandera `DataFrameSchema`.
    """
    max_minutes = settings.max_trip_hours * 60
    column = pa.Column
    check = pa.Check

    return pa.DataFrameSchema(
        {
            "vendor_id": column(nullable=True),
            "tpep_pickup_datetime": column(nullable=False),
            "tpep_dropoff_datetime": column(nullable=False),
            "passenger_count": column(checks=check.in_range(0, settings.max_passengers), nullable=True),
            "trip_distance": column(checks=[check.gt(0), check.le(settings.max_trip_distance_miles)], nullable=False),
            "ratecode_id": column(nullable=True),
            "store_and_fwd_flag": column(nullable=True),
            "pu_location_id": column(checks=check.in_range(1, MAX_ZONE_ID), nullable=False),
            "do_location_id": column(checks=check.in_range(1, MAX_ZONE_ID), nullable=False),
            "payment_type": column(checks=check.in_range(0, 6), nullable=False),
            "fare_amount": column(checks=check.ge(0), nullable=False),
            "extra": column(nullable=True),
            "mta_tax": column(nullable=True),
            "tip_amount": column(checks=check.ge(0), nullable=True),
            "tolls_amount": column(nullable=True),
            "improvement_surcharge": column(nullable=True),
            "total_amount": column(checks=check.ge(0), nullable=False),
            "congestion_surcharge": column(nullable=True),
            "airport_fee": column(nullable=True),
            "cbd_congestion_fee": column(nullable=True),
            "trip_duration_minutes": column(checks=[check.gt(0), check.le(max_minutes)], nullable=False),
            "avg_speed_mph": column(checks=check.le(settings.max_speed_mph), nullable=True),
            "has_missing_trip_details": column(nullable=False),
            "is_zero_passengers": column(nullable=False),
            "source_year": column(nullable=False),
            "source_month": column(nullable=False),
            "source_file": column(nullable=False),
            "source_row_number": column(checks=check.ge(0), nullable=False),
        },
        checks=[
            check(
                lambda df: df["tpep_dropoff_datetime"] > df["tpep_pickup_datetime"],
                error="drop-off must be after pickup",
            ),
            check(
                lambda df: (
                    (df["tpep_pickup_datetime"].dt.year == df["source_year"])
                    & (df["tpep_pickup_datetime"].dt.month == df["source_month"])
                ),
                error="pickup must fall in the month of its source file",
            ),
        ],
        strict=True,  # no unexpected columns allowed either
    )


def validate_clean_file(path: Path, schema, batch_size: int = 100_000) -> int:
    """Check a clean Parquet file against the contract, one chunk at a time.

    Args:
        path: The clean Parquet file.
        schema: Schema from `build_clean_schema`.
        batch_size: Rows per chunk.

    Returns:
        The number of rows checked.

    Raises:
        ContractViolationError: If any chunk breaks the contract.
    """
    checked = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        frame = batch.to_pandas()
        try:
            schema.validate(frame)
        except (SchemaError, SchemaErrors) as exc:
            raise ContractViolationError(f"Clean data broke the contract near row {checked}: {exc}") from exc
        checked += len(frame)
    logger.info("Contract satisfied for %d rows", checked)
    return checked
