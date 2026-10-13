# tests/test_cleaning_sql_builder.py
import pytest
from cleaning_service.rules import build_rules
from cleaning_service.sql_builder import (
    OUTPUT_COLUMNS,
    SchemaMismatchError,
    map_columns,
    normalize_name,
    quote_ident,
)

from shared.config import Settings

TLC_2024_COLUMNS = [
    "VendorID", "tpep_pickup_datetime", "tpep_dropoff_datetime", "passenger_count",
    "trip_distance", "RatecodeID", "store_and_fwd_flag", "PULocationID", "DOLocationID",
    "payment_type", "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "total_amount", "congestion_surcharge", "Airport_fee",
]  # fmt: skip


def test_normalize_name_ignores_case_and_underscores():
    assert normalize_name("Airport_fee") == normalize_name("airport_fee")
    assert normalize_name("PULocationID") == normalize_name("pu_location_id")


def test_map_columns_renames_and_fills_missing_optional_columns():
    mapping = map_columns(TLC_2024_COLUMNS)
    assert mapping["vendor_id"] == "VendorID"
    assert mapping["airport_fee"] == "Airport_fee"
    assert mapping["pu_location_id"] == "PULocationID"
    assert mapping["cbd_congestion_fee"] is None  # not in 2024 files


def test_map_columns_rejects_missing_required_column():
    columns = [name for name in TLC_2024_COLUMNS if name != "fare_amount"]
    with pytest.raises(SchemaMismatchError, match="fare_amount"):
        map_columns(columns)


def test_quote_ident_escapes_quotes():
    assert quote_ident('we"ird') == '"we""ird"'


def test_rule_names_are_unique_and_thresholds_come_from_settings():
    rules = build_rules(Settings(_env_file=None, max_speed_mph=50.0))
    names = [rule.name for rule in rules]
    assert len(names) == len(set(names))
    speed = next(rule for rule in rules if rule.name == "excessive_speed")
    assert "50.0" in speed.condition


def test_output_columns_have_no_duplicates():
    assert len(OUTPUT_COLUMNS) == len(set(OUTPUT_COLUMNS))
