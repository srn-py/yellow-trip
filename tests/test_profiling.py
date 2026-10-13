# tests/test_profiling.py
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from shared.profiling import (
    column_profile,
    count_duplicates,
    find_schema_drift,
    histogram,
    quality_report,
    row_counts_by_month,
    schema_by_file,
)


@pytest.fixture
def con():
    """An in-memory DuckDB with a tiny `trips_raw` table containing known problems."""
    connection = duckdb.connect()
    trips = pd.DataFrame(
        {
            "year": [2024] * 8,
            "month": [1] * 8,
            "tpep_pickup_datetime": pd.to_datetime(
                [
                    "2024-01-10 08:00",  # 1 good
                    "2024-01-10 09:00",  # 2 negative fare and total
                    "2024-01-10 10:00",  # 3 drop-off before pickup
                    "2024-01-10 11:00",  # 4 zero distance
                    "2024-01-10 08:00",  # 5 exact duplicate of row 1
                    "2023-12-31 23:00",  # 6 pickup outside the file's month
                    "2024-01-10 12:00",  # 7 invalid pickup zone
                    "2024-01-10 13:00",  # 8 missing passenger count
                ]
            ),
            "tpep_dropoff_datetime": pd.to_datetime(
                [
                    "2024-01-10 08:20",
                    "2024-01-10 09:20",
                    "2024-01-10 09:00",
                    "2024-01-10 11:20",
                    "2024-01-10 08:20",
                    "2023-12-31 23:20",
                    "2024-01-10 12:20",
                    "2024-01-10 13:20",
                ]
            ),
            "passenger_count": pd.array([1, 1, 1, 1, 1, 1, 1, None], dtype="Int64"),
            "trip_distance": [3.0, 3.0, 3.0, 0.0, 3.0, 3.0, 3.0, 3.0],
            "fare_amount": [15.0, -5.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0],
            "total_amount": [20.0, -5.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0],
            "tip_amount": [3.0] * 8,
            "PULocationID": [100, 100, 100, 100, 100, 100, 999, 100],
            "DOLocationID": [200] * 8,
            "payment_type": [1] * 8,
        }
    )
    connection.register("trips_df", trips)
    connection.execute("CREATE TABLE trips_raw AS SELECT * FROM trips_df")
    return connection


def test_row_counts_by_month(con):
    counts = row_counts_by_month(con)
    assert len(counts) == 1
    assert counts.loc[0, "trips"] == 8


def test_quality_report_finds_each_planted_problem(con):
    report = quality_report(con).set_index("check")["bad_rows"]
    assert report["negative_fare"] == 1
    assert report["negative_total_amount"] == 1
    assert report["zero_or_negative_distance"] == 1
    assert report["dropoff_not_after_pickup"] == 1
    assert report["pickup_outside_file_month"] == 1
    assert report["invalid_pickup_zone"] == 1
    assert report["null_passenger_count"] == 1
    assert report["negative_tip"] == 0
    assert report["speed_over_100_mph"] == 0


def test_count_duplicates(con):
    result = count_duplicates(con)
    assert result["total_rows"] == 8
    assert result["duplicate_rows"] == 1


def test_histogram_buckets(con):
    hist = histogram(con, "trip_distance", low=0, high=10, bins=10)
    assert hist.set_index("bin_start")["trips"].to_dict() == {0.0: 1, 3.0: 7}


def test_column_profile_has_one_row_per_column(con):
    profile = column_profile(con)
    assert "passenger_count" in set(profile["column_name"])
    nulls = profile.set_index("column_name")["null_percentage"]
    assert nulls["passenger_count"] == pytest.approx(12.5)


def test_histogram_rejects_unsafe_column_name(con):
    with pytest.raises(ValueError):
        histogram(con, "trip_distance; DROP TABLE trips_raw", 0, 10)


def test_schema_drift_detection(tmp_path: Path):
    """Two fake monthly files: 'a' changes type, 'b' disappears, 'c' appears, 'd' is stable."""
    connection = duckdb.connect()
    for month, select in (
        ("01", "1::BIGINT AS a, 2.0::DOUBLE AS b, 5::BIGINT AS d"),
        ("02", "1.5::DOUBLE AS a, 7::BIGINT AS c, 5::BIGINT AS d"),
    ):
        folder = tmp_path / "year=2024" / f"month={month}"
        folder.mkdir(parents=True)
        target = (folder / "data.parquet").as_posix()
        connection.execute(f"COPY (SELECT {select}) TO '{target}' (FORMAT PARQUET)")

    schema = schema_by_file(connection, (tmp_path / "year=*" / "month=*" / "*.parquet").as_posix())
    assert list(schema.columns) == ["2024-01", "2024-02"]

    drift = find_schema_drift(schema)
    assert set(drift.index) == {"a", "b", "c"}
