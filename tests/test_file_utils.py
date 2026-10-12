# tests/test_file_utils.py
import pytest
from ingestion_service.file_utils import (
    UnreadableFileError,
    UnsupportedFormatError,
    count_rows,
    detect_format,
    parse_trip_filename,
    safe_filename,
    sha256_of_file,
)


def test_detect_format_known_extensions():
    assert detect_format("a.PARQUET") == "parquet"
    assert detect_format("a.csv") == "csv"
    assert detect_format("a.jsonl") == "ndjson"


def test_detect_format_rejects_unknown():
    with pytest.raises(UnsupportedFormatError):
        detect_format("report.xlsx")


def test_count_rows_parquet(sample_parquet):
    assert count_rows(sample_parquet, "parquet") == 3


def test_count_rows_csv(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("a,b\n1,2\n3,4\n")
    assert count_rows(path, "csv") == 2


def test_count_rows_ndjson(tmp_path):
    path = tmp_path / "a.ndjson"
    path.write_text('{"a": 1}\n{"a": 2}\n\n')
    assert count_rows(path, "ndjson") == 2


def test_corrupt_parquet_is_rejected(tmp_path):
    path = tmp_path / "bad.parquet"
    path.write_bytes(b"this is not parquet")
    with pytest.raises(UnreadableFileError):
        count_rows(path, "parquet")


def test_parse_trip_filename():
    assert parse_trip_filename("yellow_tripdata_2024-01.parquet") == (2024, 1)
    assert parse_trip_filename("something_else.parquet") is None


def test_safe_filename_blocks_path_tricks():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("my file (1).csv") == "my_file__1_.csv"


def test_checksum_is_stable_and_content_based(tmp_path):
    first = tmp_path / "x.csv"
    second = tmp_path / "y.csv"
    first.write_text("same")
    second.write_text("same")
    assert sha256_of_file(first) == sha256_of_file(second)
