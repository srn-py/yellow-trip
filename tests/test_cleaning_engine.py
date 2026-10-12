# tests/test_cleaning_engine.py
import pyarrow.parquet as pq
import pytest
from cleaning_service.engine import run_cleaning


@pytest.fixture
def result(trip_source_file, tmp_path, settings):
    return run_cleaning(trip_source_file, tmp_path / "work", 2024, 1, "raw/test.parquet", settings)


def test_counts_reconcile(result):
    assert result.rows_in == 10
    assert result.rows_clean == 4
    assert result.rows_quarantined == 6
    assert result.rows_in == result.rows_clean + result.rows_quarantined


def test_each_planted_problem_is_caught_exactly_once(result):
    expected_once = {
        "negative_fare",
        "negative_total_amount",
        "zero_or_negative_distance",
        "dropoff_not_after_pickup",
        "pickup_outside_file_month",
        "duplicate_row",
        "excessive_speed",
    }
    for name, count in result.rule_counts.items():
        assert count == (1 if name in expected_once else 0), name


def test_clean_file_has_standard_columns_and_derived_values(result):
    clean = pq.read_table(result.clean_path).to_pandas()
    assert "airport_fee" in clean.columns
    assert "Airport_fee" not in clean.columns
    assert clean["cbd_congestion_fee"].isna().all()  # column did not exist in the source
    assert (clean["trip_duration_minutes"] > 0).all()
    assert (clean["source_year"] == 2024).all()
    assert (clean["source_file"] == "raw/test.parquet").all()


def test_flags_mark_flex_fare_and_zero_passenger_rows(result):
    clean = pq.read_table(result.clean_path).to_pandas()
    assert clean["has_missing_trip_details"].sum() == 1
    assert (clean.loc[clean["has_missing_trip_details"], "payment_type"] == 0).all()
    assert clean["is_zero_passengers"].sum() == 1
    assert result.clean_rows_with_missing_details == 1
    assert result.clean_rows_zero_passengers == 1


def test_quarantine_file_carries_reasons(result):
    quarantine = pq.read_table(result.quarantine_path).to_pandas()
    assert len(quarantine) == 6
    assert (quarantine["reject_reasons"] != "").all()
    reasons_of_negative = quarantine.loc[quarantine["fare_amount"] == -5.0, "reject_reasons"].iloc[0]
    assert set(reasons_of_negative.split(";")) == {"negative_fare", "negative_total_amount"}


def test_schema_report_lists_renames_and_null_filled_columns(result):
    assert result.renamed_columns["Airport_fee"] == "airport_fee"
    assert result.columns_filled_with_null == ["cbd_congestion_fee"]
