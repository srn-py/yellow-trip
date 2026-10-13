# tests/test_etl_loader.py
from pathlib import Path

import pytest
from etl_helpers import make_clean_parquet
from etl_service.loader import LoaderService, NotCleanedError, ZoneFileNotFoundError
from etl_service.warehouse import LoadMismatchError

CLEAN_KEY = "yellow_tripdata/year=2024/month=01/yellow_tripdata_2024-01_clean.parquet"


class FakeWarehouse:
    """Records what the loader asks the database to do."""

    def __init__(self):
        self.logs = {}
        self.replaced = []
        self.zone_lines = None

    def get_month_log(self, year, month):
        return self.logs.get((year, month))

    def replace_month(self, year, month, csv_path, expected_rows, cleaned_at, clean_object_key, duration_seconds):
        record = {
            "year": year,
            "month": month,
            "rows_loaded": expected_rows,
            "cleaned_at": cleaned_at,
            "clean_object_key": clean_object_key,
            "duration_seconds": duration_seconds,
        }
        self.logs[(year, month)] = record
        self.replaced.append((year, month, Path(csv_path).read_text()))
        return record

    def replace_zones(self, csv_path):
        self.zone_lines = Path(csv_path).read_text().splitlines()
        return len(self.zone_lines)


class FakeCleaningClient:
    def __init__(self, reports=None):
        self.reports = reports or {}

    def get_report(self, year, month):
        return self.reports.get((year, month))


class FakeIngestionClient:
    def __init__(self, zone_record=None):
        self.zone_record = zone_record

    def get_zone_lookup_file(self):
        return self.zone_record


def _report(rows=3, finished_at="2026-01-01T10:00:00+00:00"):
    return {
        "finished_at": finished_at,
        "counts": {"rows_clean": rows},
        "outputs": {"clean": {"bucket": "clean", "object_key": CLEAN_KEY, "rows": rows}},
    }


@pytest.fixture
def warehouse():
    return FakeWarehouse()


@pytest.fixture
def cleaning():
    return FakeCleaningClient({(2024, 1): _report()})


@pytest.fixture
def loader(fake_storage, cleaning, warehouse, settings, tmp_path):
    parquet = make_clean_parquet(tmp_path / "clean.parquet", rows=3)
    fake_storage.objects[("clean", CLEAN_KEY)] = parquet.read_bytes()
    return LoaderService(fake_storage, cleaning, FakeIngestionClient(), warehouse, settings)


def test_month_is_loaded(loader, warehouse):
    outcome = loader.load_month(2024, 1)
    assert outcome.status == "loaded"
    assert outcome.record["rows_loaded"] == 3
    assert len(warehouse.replaced) == 1
    assert len(warehouse.replaced[0][2].splitlines()) == 3


def test_same_cleaning_run_is_skipped_and_force_reloads(loader, warehouse):
    assert loader.load_month(2024, 1).status == "loaded"
    assert loader.load_month(2024, 1).status == "skipped"
    assert len(warehouse.replaced) == 1
    assert loader.load_month(2024, 1, force=True).status == "loaded"
    assert len(warehouse.replaced) == 2


def test_a_newer_cleaning_run_triggers_a_reload(loader, cleaning, warehouse):
    loader.load_month(2024, 1)
    cleaning.reports[(2024, 1)] = _report(finished_at="2026-02-02T10:00:00+00:00")
    assert loader.load_month(2024, 1).status == "loaded"
    assert len(warehouse.replaced) == 2


def test_uncleaned_month_is_reported(loader):
    with pytest.raises(NotCleanedError):
        loader.load_month(2030, 5)


def test_row_count_mismatch_loads_nothing(loader, cleaning, warehouse):
    cleaning.reports[(2024, 1)] = _report(rows=5)  # the report claims 5, the file has 3
    with pytest.raises(LoadMismatchError):
        loader.load_month(2024, 1)
    assert warehouse.replaced == []


def test_zones_are_loaded(fake_storage, cleaning, warehouse, settings):
    fake_storage.objects[("raw", "reference/taxi_zone_lookup.csv")] = (
        b"LocationID,Borough,Zone,service_zone\n1,EWR,Newark Airport,EWR\n2,Queens,Jamaica Bay,Boro Zone\n"
    )
    record = {"bucket": "raw", "object_key": "reference/taxi_zone_lookup.csv"}
    loader = LoaderService(fake_storage, cleaning, FakeIngestionClient(record), warehouse, settings)

    outcome = loader.load_zones()

    assert outcome.status == "loaded"
    assert outcome.record["rows_loaded"] == 2
    assert warehouse.zone_lines[0].startswith("1,EWR")


def test_zones_not_ingested(fake_storage, cleaning, warehouse, settings):
    loader = LoaderService(fake_storage, cleaning, FakeIngestionClient(None), warehouse, settings)
    with pytest.raises(ZoneFileNotFoundError):
        loader.load_zones()
