# tests/test_etl_landing.py
import pytest
from cleaning_service.sql_builder import OUTPUT_COLUMNS
from etl_service.landing import (
    TRIP_COLUMN_NAMES,
    SchemaContractError,
    build_landing_ddl,
    check_columns,
)


def test_landing_columns_match_the_cleaning_services_output_exactly():
    """The contract between two services: if one changes without the other, this fails."""
    assert TRIP_COLUMN_NAMES == OUTPUT_COLUMNS


def test_ddl_creates_every_table_and_every_column():
    ddl = "\n".join(build_landing_ddl())
    for table in ("landing.trips", "landing.zones", "landing.load_log"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl
    for column in TRIP_COLUMN_NAMES:
        assert column in ddl
    assert "loaded_at timestamptz NOT NULL DEFAULT now()" in ddl


def test_check_columns_accepts_exact_match():
    check_columns(list(TRIP_COLUMN_NAMES))


def test_check_columns_reports_missing_and_unexpected():
    found = [name for name in TRIP_COLUMN_NAMES if name != "fare_amount"] + ["surprise"]
    with pytest.raises(SchemaContractError, match="fare_amount") as error:
        check_columns(found)
    assert "surprise" in str(error.value)
