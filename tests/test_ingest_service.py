# tests/test_ingest_service.py
import shutil


def test_new_file_is_stored_and_registered(service, fake_storage, sample_parquet, settings):
    result = service.ingest_file(sample_parquet, sample_parquet.name, "upload")

    assert result.status == "ingested"
    assert result.record["row_count"] == 3
    assert result.record["dataset"] == "yellow_tripdata"
    expected_key = "yellow_tripdata/year=2024/month=01/yellow_tripdata_2024-01.parquet"
    assert fake_storage.object_exists(settings.bucket_raw, expected_key)


def test_same_content_twice_is_a_duplicate(service, sample_parquet):
    service.ingest_file(sample_parquet, sample_parquet.name, "upload")
    again = service.ingest_file(sample_parquet, sample_parquet.name, "upload")
    assert again.status == "duplicate"
    assert len(service.list_files()) == 1


def test_trip_month_is_downloaded_once_then_skipped(service, sample_parquet, monkeypatch):
    calls = []

    def fake_download(url, dest, **kwargs):
        calls.append(url)
        shutil.copy(sample_parquet, dest)

    monkeypatch.setattr("ingestion_service.ingest.download_to_file", fake_download)

    first = service.ingest_trip_month(2024, 1)
    second = service.ingest_trip_month(2024, 1)

    assert first.status == "ingested"
    assert second.status == "skipped"
    assert len(calls) == 1  # the second call never touched the network
    assert calls[0].endswith("yellow_tripdata_2024-01.parquet")
