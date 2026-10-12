# tests/test_cleaning_unmapped_columns.py
import pyarrow.parquet as pq
from cleaning_service.engine import run_cleaning


def test_known_columns_leave_nothing_unmapped(trip_source_file, tmp_path, settings):
    result = run_cleaning(trip_source_file, tmp_path / "work", 2024, 1, "raw/test.parquet", settings)
    assert result.unmapped_columns == []


def test_a_new_source_column_is_reported_instead_of_silently_ignored(trip_source_file, tmp_path, settings):
    table = pq.read_table(trip_source_file)
    table = table.append_column("brand_new_fee", table["fare_amount"])
    drifted = tmp_path / "drifted.parquet"
    pq.write_table(table, drifted)

    result = run_cleaning(drifted, tmp_path / "work", 2024, 1, "raw/test.parquet", settings)

    assert result.unmapped_columns == ["brand_new_fee"]
    assert result.rows_in == 10  # cleaning itself is unaffected
