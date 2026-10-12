# tests/test_cleaner.py
import json

import pytest
from cleaning_service.cleaner import (
    ReconciliationError,
    SourceNotFoundError,
    UnsupportedSourceError,
)

CLEAN_KEY = "yellow_tripdata/year=2024/month=01/yellow_tripdata_2024-01_clean.parquet"
QUARANTINE_KEY = "yellow_tripdata/year=2024/month=01/yellow_tripdata_2024-01_quarantine.parquet"
REPORT_KEY = "reports/yellow_tripdata/year=2024/month=01/cleaning_report.json"


def test_clean_month_publishes_outputs_and_report(cleaning_service, fake_storage):
    outcome = cleaning_service.clean_month(2024, 1)

    assert outcome.status == "cleaned"
    counts = outcome.report["counts"]
    assert (counts["rows_in"], counts["rows_clean"], counts["rows_quarantined"]) == (10, 4, 6)
    assert counts["reconciled"] is True
    assert ("clean", CLEAN_KEY) in fake_storage.objects
    assert ("quarantine", QUARANTINE_KEY) in fake_storage.objects

    stored = json.loads(fake_storage.objects[("clean", REPORT_KEY)])
    assert stored["rules_version"] == outcome.report["rules_version"]
    assert stored["rule_violations"]["negative_fare"] == 1


def test_second_run_is_skipped_and_force_redoes_it(cleaning_service):
    assert cleaning_service.clean_month(2024, 1).status == "cleaned"
    assert cleaning_service.clean_month(2024, 1).status == "skipped"
    assert cleaning_service.clean_month(2024, 1, force=True).status == "cleaned"


def test_changed_source_file_triggers_a_new_clean(cleaning_service, ingestion_client):
    cleaning_service.clean_month(2024, 1)
    ingestion_client.records[(2024, 1)]["sha256"] = "a-different-file"
    assert cleaning_service.clean_month(2024, 1).status == "cleaned"


def test_month_that_was_never_ingested_is_reported(cleaning_service):
    with pytest.raises(SourceNotFoundError):
        cleaning_service.clean_month(2030, 5)


def test_non_parquet_source_is_rejected(cleaning_service, ingestion_client):
    ingestion_client.records[(2024, 1)]["file_format"] = "csv"
    with pytest.raises(UnsupportedSourceError):
        cleaning_service.clean_month(2024, 1)


def test_failed_reconciliation_publishes_nothing(cleaning_service, ingestion_client, fake_storage):
    ingestion_client.records[(2024, 1)]["row_count"] = 11  # registry disagrees with the file
    with pytest.raises(ReconciliationError):
        cleaning_service.clean_month(2024, 1)
    assert ("clean", CLEAN_KEY) not in fake_storage.objects
    assert ("clean", REPORT_KEY) not in fake_storage.objects  # no report = month not done


def test_report_listing_and_lookup(cleaning_service):
    assert cleaning_service.get_report(2024, 1) is None
    cleaning_service.clean_month(2024, 1)
    assert cleaning_service.get_report(2024, 1)["counts"]["rows_in"] == 10
    summary = cleaning_service.list_reports()
    assert [(row["year"], row["month"], row["rows_in"]) for row in summary] == [(2024, 1, 10)]
