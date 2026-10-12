# tests/test_etl_export.py
import csv

import duckdb
import pytest
from etl_helpers import make_clean_parquet
from etl_service.export import ZoneFileError, parquet_to_csv, zones_to_csv
from etl_service.landing import TRIP_COLUMN_NAMES, SchemaContractError


def test_parquet_to_csv_writes_one_line_per_row_in_landing_order(tmp_path):
    parquet = make_clean_parquet(tmp_path / "clean.parquet", rows=3)
    out = tmp_path / "trips.csv"

    assert parquet_to_csv(parquet, out) == 3

    rows = list(csv.reader(out.read_text().splitlines()))
    assert len(rows) == 3
    assert all(len(row) == len(TRIP_COLUMN_NAMES) for row in rows)


def test_nulls_become_empty_fields_for_postgres_copy(tmp_path):
    parquet = make_clean_parquet(tmp_path / "clean.parquet", rows=3)
    out = tmp_path / "trips.csv"
    parquet_to_csv(parquet, out)

    passenger = TRIP_COLUMN_NAMES.index("passenger_count")
    rows = list(csv.reader(out.read_text().splitlines()))
    assert rows[0][passenger] == "1"
    assert rows[2][passenger] == ""  # flex-fare row: NULL
    assert ",," in out.read_text().splitlines()[2]  # unquoted empty field = NULL for COPY


def test_file_with_wrong_columns_is_rejected(tmp_path):
    wrong = tmp_path / "wrong.parquet"
    duckdb.connect().execute(f"COPY (SELECT 1 AS a) TO '{wrong.as_posix()}' (FORMAT PARQUET)")
    with pytest.raises(SchemaContractError):
        parquet_to_csv(wrong, tmp_path / "out.csv")


def test_zones_to_csv(tmp_path):
    raw = tmp_path / "zones.csv"
    raw.write_text(
        "LocationID,Borough,Zone,service_zone\n"
        "1,EWR,Newark Airport,EWR\n"
        '2,Queens,"Jamaica Bay, Queens",Boro Zone\n'
        "265,Unknown,N/A,N/A\n"
    )
    out = tmp_path / "zones_load.csv"

    assert zones_to_csv(raw, out) == 3

    rows = list(csv.reader(out.read_text().splitlines()))
    assert rows[0] == ["1", "EWR", "Newark Airport", "EWR"]
    assert rows[1][2] == "Jamaica Bay, Queens"  # a comma inside a name survives


def test_zones_file_with_wrong_shape_is_rejected(tmp_path):
    raw = tmp_path / "zones.csv"
    raw.write_text("a,b\n1,2\n")
    with pytest.raises(ZoneFileError):
        zones_to_csv(raw, tmp_path / "out.csv")
