# tests/test_cleaning_contract.py
import pyarrow.parquet as pq
import pytest
from cleaning_service.contract import (
    ContractViolationError,
    build_clean_schema,
    validate_clean_file,
)
from cleaning_service.engine import run_cleaning


@pytest.fixture
def clean_path(trip_source_file, tmp_path, settings):
    result = run_cleaning(trip_source_file, tmp_path / "work", 2024, 1, "raw/test.parquet", settings)
    return result.clean_path


def test_clean_output_satisfies_the_contract(clean_path, settings):
    assert validate_clean_file(clean_path, build_clean_schema(settings)) == 4


def test_contract_catches_a_row_that_slipped_through(clean_path, tmp_path, settings):
    frame = pq.read_table(clean_path).to_pandas()
    frame.loc[0, "fare_amount"] = -1.0  # simulate a bug: a negative fare in the clean file
    tampered = tmp_path / "tampered.parquet"
    frame.to_parquet(tampered)
    with pytest.raises(ContractViolationError):
        validate_clean_file(tampered, build_clean_schema(settings))


def test_contract_rejects_unexpected_extra_column(clean_path, tmp_path, settings):
    frame = pq.read_table(clean_path).to_pandas()
    frame["surprise"] = 1
    tampered = tmp_path / "extra.parquet"
    frame.to_parquet(tampered)
    with pytest.raises(ContractViolationError):
        validate_clean_file(tampered, build_clean_schema(settings))
