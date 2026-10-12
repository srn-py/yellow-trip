# tests/test_pipeline_months.py
from datetime import datetime

import pytest
from taxi_pipeline.months import (
    MonthResolutionError,
    month_label,
    normalise_run_type,
    parse_month,
    resolve_target_month,
    shift_month,
)


def resolve(**overrides):
    values = {
        "param_month": None,
        "logical_date": None,
        "data_interval_start": None,
        "run_type": "manual",
        "lag_months": 2,
    }
    return resolve_target_month(**{**values, **overrides})


def test_parse_and_label_round_trip():
    assert parse_month("2024-01") == (2024, 1)
    assert month_label(2024, 1) == "2024-01"


def test_invalid_month_text_is_rejected():
    with pytest.raises(MonthResolutionError):
        parse_month("2024-13")


def test_shift_month_crosses_year_boundaries():
    assert shift_month(2026, 1, -2) == (2025, 11)
    assert shift_month(2025, 11, 3) == (2026, 2)
    assert shift_month(2024, 5, 0) == (2024, 5)


def test_parameter_wins_over_everything():
    assert resolve(param_month="2023-07", logical_date=datetime(2026, 10, 1), run_type="scheduled") == (2023, 7)


def test_backfill_uses_the_logical_date_with_no_lag():
    assert resolve(logical_date=datetime(2024, 3, 1), run_type="backfill") == (2024, 3)


def test_scheduled_run_applies_the_publication_lag():
    assert resolve(logical_date=datetime(2026, 10, 1), run_type="scheduled") == (2026, 8)
    assert resolve(logical_date=datetime(2026, 1, 1), run_type="scheduled") == (2025, 11)


def test_scheduled_run_with_zero_lag_uses_the_logical_month():
    assert resolve(logical_date=datetime(2026, 10, 1), run_type="scheduled", lag_months=0) == (
        2026,
        10,
    )


def test_falls_back_to_the_data_interval_start():
    assert resolve(data_interval_start=datetime(2024, 4, 1)) == (2024, 4)


def test_manual_run_without_any_date_needs_the_parameter():
    with pytest.raises(MonthResolutionError, match="month"):
        resolve()


def test_empty_parameter_is_treated_as_not_given():
    assert resolve(param_month="  ", logical_date=datetime(2024, 2, 1)) == (2024, 2)


def test_run_type_accepts_strings_and_enum_like_values():
    class FakeEnum:
        value = "Scheduled"

    assert normalise_run_type("backfill") == "backfill"
    assert normalise_run_type(FakeEnum()) == "scheduled"
    assert normalise_run_type(None) == ""
