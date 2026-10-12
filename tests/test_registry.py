# tests/test_registry.py
def _record(**overrides):
    base = {
        "sha256": "a" * 64,
        "filename": "f.parquet",
        "dataset": "yellow_tripdata",
        "file_format": "parquet",
        "source": "upload",
        "bucket": "raw",
        "object_key": "k",
        "size_bytes": 10,
        "row_count": 3,
        "year": 2024,
        "month": 1,
    }
    return {**base, **overrides}


def test_add_and_find_by_checksum(registry):
    stored = registry.add(_record())
    assert stored["id"] == 1
    assert registry.find_by_checksum("a" * 64)["filename"] == "f.parquet"
    assert registry.find_by_checksum("b" * 64) is None


def test_find_by_period(registry):
    registry.add(_record())
    assert registry.find_by_period("yellow_tripdata", 2024, 1) is not None
    assert registry.find_by_period("yellow_tripdata", 2024, 2) is None


def test_list_files_filters_by_dataset(registry):
    registry.add(_record())
    registry.add(_record(sha256="c" * 64, dataset="uploads", year=None, month=None))
    assert len(registry.list_files()) == 2
    assert len(registry.list_files(dataset="uploads")) == 1
