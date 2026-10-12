# tests/test_backup.py
from pathlib import Path

from ingestion_service.registry import FileRegistry
from shared import backup


class FakeLake:
    """An in-memory object store with just what the backup code uses."""

    def __init__(self, buckets=None):
        self.buckets = {name: dict(objects) for name, objects in (buckets or {}).items()}

    def ensure_bucket(self, bucket):
        self.buckets.setdefault(bucket, {})

    def list_objects(self, bucket, prefix=""):
        return [
            {"key": key, "size_bytes": len(data), "last_modified": ""}
            for key, data in sorted(self.buckets.get(bucket, {}).items())
            if key.startswith(prefix)
        ]

    def download_file(self, bucket, key, local_path):
        Path(local_path).write_bytes(self.buckets[bucket][key])

    def upload_file(self, bucket, key, local_path, content_type=None, metadata=None):
        self.buckets.setdefault(bucket, {})[key] = Path(local_path).read_bytes()


LAKE = {
    "raw": {"yellow_tripdata/year=2024/month=01/file.parquet": b"parquet-bytes", "reference/zones.csv": b"a,b"},
    "clean": {"reports/r.json": b"{}"},
}


def test_backup_copies_every_object_into_bucket_folders(tmp_path):
    summary = backup.backup_buckets(FakeLake(LAKE), ["raw", "clean"], tmp_path)
    assert (tmp_path / "raw/yellow_tripdata/year=2024/month=01/file.parquet").read_bytes() == b"parquet-bytes"
    assert (tmp_path / "clean/reports/r.json").read_bytes() == b"{}"
    assert summary["raw"]["downloaded"] == 2
    assert summary["raw"]["bytes"] == len(b"parquet-bytes") + len(b"a,b")


def test_a_second_backup_skips_what_it_already_has_and_fetches_changes(tmp_path):
    lake = FakeLake(LAKE)
    backup.backup_buckets(lake, ["raw"], tmp_path)
    again = backup.backup_buckets(lake, ["raw"], tmp_path)
    assert again["raw"] == {"downloaded": 0, "skipped": 2, "unsafe": 0, "bytes": 0}

    lake.buckets["raw"]["reference/zones.csv"] = b"a,b,c"  # the object changed size
    changed = backup.backup_buckets(lake, ["raw"], tmp_path)
    assert changed["raw"]["downloaded"] == 1
    assert (tmp_path / "raw/reference/zones.csv").read_bytes() == b"a,b,c"


def test_objects_deleted_from_the_lake_stay_in_the_backup(tmp_path):
    lake = FakeLake(LAKE)
    backup.backup_buckets(lake, ["raw"], tmp_path)
    del lake.buckets["raw"]["reference/zones.csv"]
    backup.backup_buckets(lake, ["raw"], tmp_path)
    assert (tmp_path / "raw/reference/zones.csv").exists()


def test_a_key_that_tries_to_escape_the_backup_folder_is_refused(tmp_path):
    lake = FakeLake({"raw": {"../../evil.txt": b"x", "ok.txt": b"y"}})
    folder = tmp_path / "backup"
    summary = backup.backup_buckets(lake, ["raw"], folder)
    assert summary["raw"]["unsafe"] == 1
    assert not (tmp_path / "evil.txt").exists()
    assert (folder / "raw/ok.txt").exists()


def test_restore_rebuilds_an_empty_lake_exactly(tmp_path):
    backup.backup_buckets(FakeLake(LAKE), ["raw", "clean"], tmp_path)
    empty = FakeLake()
    summary = backup.restore_buckets(empty, tmp_path)
    assert empty.buckets == LAKE
    assert summary["raw"]["uploaded"] == 2


def test_restore_leaves_existing_objects_alone_and_creates_missing_buckets(tmp_path):
    backup.backup_buckets(FakeLake(LAKE), ["raw"], tmp_path)
    (tmp_path / "quarantine").mkdir()  # a bucket that was empty when backed up
    partly = FakeLake({"raw": {"reference/zones.csv": b"a,b"}})
    summary = backup.restore_buckets(partly, tmp_path)
    assert summary["raw"] == {"uploaded": 1, "skipped": 1}
    assert "quarantine" in partly.buckets


def test_the_registry_survives_a_backup_and_restore(tmp_path):
    live = tmp_path / "live" / "registry.db"
    registry = FileRegistry(str(live))
    registry.add(
        {
            "sha256": "a" * 64, "filename": "f.parquet", "dataset": "yellow_tripdata", "file_format": "parquet",
            "source": "upload", "bucket": "raw", "object_key": "k", "size_bytes": 10, "row_count": 3,
            "year": 2024, "month": 1,
        }
    )  # fmt: skip

    copy = backup.backup_registry(live, tmp_path / "backups" / "registry.db")
    restored = tmp_path / "new-server" / "registry.db"
    backup.restore_registry(copy, restored)

    assert FileRegistry(str(restored)).find_by_checksum("a" * 64)["filename"] == "f.parquet"


def test_missing_registry_files_give_clear_errors(tmp_path):
    for call in (
        lambda: backup.backup_registry(tmp_path / "nope.db", tmp_path / "x.db"),
        lambda: backup.restore_registry(tmp_path / "nope.db", tmp_path / "x.db"),
    ):
        try:
            call()
        except FileNotFoundError as error:
            assert "nope.db" in str(error)
        else:
            raise AssertionError("expected FileNotFoundError")
