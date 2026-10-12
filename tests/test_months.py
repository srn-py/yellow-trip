# tests/test_months.py
import pytest

from shared.months import expand_months, parse_month


def test_parse_month():
    assert parse_month("2024-01") == (2024, 1)


def test_parse_month_rejects_bad_text():
    with pytest.raises(ValueError):
        parse_month("2024-13")


def test_expand_single_month():
    assert expand_months("2024-05") == [(2024, 5)]


def test_expand_range_crosses_year_boundary():
    assert expand_months("2024-11", "2025-02") == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]


def test_expand_rejects_reversed_and_too_long_ranges():
    with pytest.raises(ValueError):
        expand_months("2024-05", "2024-01")
    with pytest.raises(ValueError):
        expand_months("2020-01", "2030-01")
