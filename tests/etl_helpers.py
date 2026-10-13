# tests/etl_helpers.py
"""Shared helper for the ETL tests (not a test file itself)."""

from pathlib import Path

import duckdb


def make_clean_parquet(path: Path, rows: int = 3) -> Path:
    """Write a small Parquet file shaped like the cleaning service's clean output.

    Row index 2 is a "flex fare" style row: passenger count, rate code, store-and-forward flag
    are NULL and payment_type is 0.

    Args:
        path: Where to write the file.
        rows: Number of rows.

    Returns:
        The same path.
    """
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CAST(1 AS INTEGER) AS vendor_id,
                TIMESTAMP '2024-01-10 08:00:00' AS tpep_pickup_datetime,
                TIMESTAMP '2024-01-10 08:20:00' AS tpep_dropoff_datetime,
                CAST(CASE WHEN i = 2 THEN NULL ELSE 1 END AS INTEGER) AS passenger_count,
                CAST(3.5 AS DOUBLE) AS trip_distance,
                CAST(CASE WHEN i = 2 THEN NULL ELSE 1 END AS INTEGER) AS ratecode_id,
                CASE WHEN i = 2 THEN NULL ELSE 'N' END AS store_and_fwd_flag,
                CAST(100 AS INTEGER) AS pu_location_id,
                CAST(200 AS INTEGER) AS do_location_id,
                CAST(CASE WHEN i = 2 THEN 0 ELSE 1 END AS INTEGER) AS payment_type,
                CAST(15.0 AS DOUBLE) AS fare_amount,
                CAST(0.5 AS DOUBLE) AS extra,
                CAST(0.5 AS DOUBLE) AS mta_tax,
                CAST(3.0 AS DOUBLE) AS tip_amount,
                CAST(0.0 AS DOUBLE) AS tolls_amount,
                CAST(1.0 AS DOUBLE) AS improvement_surcharge,
                CAST(20.0 AS DOUBLE) AS total_amount,
                CAST(NULL AS DOUBLE) AS congestion_surcharge,
                CAST(0.0 AS DOUBLE) AS airport_fee,
                CAST(NULL AS DOUBLE) AS cbd_congestion_fee,
                CAST(20.0 AS DOUBLE) AS trip_duration_minutes,
                CAST(10.5 AS DOUBLE) AS avg_speed_mph,
                (i = 2) AS has_missing_trip_details,
                false AS is_zero_passengers,
                CAST(2024 AS INTEGER) AS source_year,
                CAST(1 AS INTEGER) AS source_month,
                'raw/test.parquet' AS source_file,
                CAST(i AS BIGINT) AS source_row_number
            FROM range({rows}) AS t(i)
        ) TO '{path.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()
    return path
