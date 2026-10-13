# shared/backup.py
"""Backup and restore helpers for the data lake and the ingestion file registry.

What needs backing up, and how:

| Data | Where | How |
|---|---|---|
| Warehouse and Airflow databases | PostgreSQL | `pg_dump`/`pg_restore` (see deploy/backup.sh) |
| File registry | a SQLite file | SQLite's online backup, safe while the service runs (here) |
| Data lake | S3 buckets | an incremental copy of every object into a folder (here) |

Run from inside a container that has the S3 settings (the ingestion container):

    python -m shared.backup lake-backup /backups/lake
    python -m shared.backup lake-restore /backups/lake
    python -m shared.backup registry-backup /backups/<stamp>/registry.db
    python -m shared.backup registry-restore /backups/<stamp>/registry.db

The lake backup only ever ADDS files: an object deleted from the lake stays in the backup folder.
That is deliberate: a backup should survive a mistaken deletion.
"""

import argparse
import json
import logging
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from shared.config import get_settings

logger = logging.getLogger(__name__)


def backup_buckets(storage, buckets: Sequence[str], target: Path) -> dict[str, dict[str, int]]:
    """Copy every object of the given buckets into `target/<bucket>/<key>`.

    Objects already present with the same size are skipped, so repeated runs are quick.

    Args:
        storage: Object storage with `list_objects` and `download_file`.
        buckets: Buckets to copy.
        target: Backup folder.

    Returns:
        Per bucket: counts of downloaded, skipped and unsafe objects, and bytes downloaded.
    """
    root = Path(target).resolve()
    summary: dict[str, dict[str, int]] = {}
    for bucket in buckets:
        counts = {"downloaded": 0, "skipped": 0, "unsafe": 0, "bytes": 0}
        for item in storage.list_objects(bucket):
            key = item["key"]
            if key.endswith("/"):  # a folder placeholder, nothing to copy
                counts["skipped"] += 1
                continue
            destination = (root / bucket / key).resolve()
            if root not in destination.parents:  # a key such as "../../x" must never write outside the backup
                logger.warning("Skipping unsafe object key %r in bucket %s", key, bucket)
                counts["unsafe"] += 1
                continue
            if destination.exists() and destination.stat().st_size == item["size_bytes"]:
                counts["skipped"] += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            storage.download_file(bucket, key, destination)
            counts["downloaded"] += 1
            counts["bytes"] += item["size_bytes"]
        summary[bucket] = counts
    return summary


def restore_buckets(storage, source: Path, buckets: Sequence[str] | None = None) -> dict[str, dict[str, int]]:
    """Upload a backup folder back into the lake.

    Objects that already exist with the same size are left alone.

    Args:
        storage: Object storage with `ensure_bucket`, `list_objects` and `upload_file`.
        source: Backup folder created by `backup_buckets`.
        buckets: Buckets to restore (default: every folder found in `source`).

    Returns:
        Per bucket: counts of uploaded and skipped objects.
    """
    root = Path(source)
    names = list(buckets) if buckets else sorted(path.name for path in root.iterdir() if path.is_dir())
    summary: dict[str, dict[str, int]] = {}
    for bucket in names:
        counts = {"uploaded": 0, "skipped": 0}
        storage.ensure_bucket(bucket)
        folder = root / bucket
        if folder.is_dir():
            existing = {item["key"]: item["size_bytes"] for item in storage.list_objects(bucket)}
            for path in sorted(item for item in folder.rglob("*") if item.is_file()):
                key = path.relative_to(folder).as_posix()
                if existing.get(key) == path.stat().st_size:
                    counts["skipped"] += 1
                else:
                    storage.upload_file(bucket, key, path)
                    counts["uploaded"] += 1
        else:
            logger.warning("No backup folder for bucket %s in %s", bucket, root)
        summary[bucket] = counts
    return summary


def backup_registry(db_path: str | Path, target: str | Path) -> Path:
    """Copy the file registry with SQLite's online backup (safe while the service is running).

    Args:
        db_path: The live registry database.
        target: Where to write the copy.

    Returns:
        The path of the copy.

    Raises:
        FileNotFoundError: If the registry does not exist.
    """
    source, destination = Path(db_path), Path(target)
    if not source.exists():
        raise FileNotFoundError(f"No registry at {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
    return destination


def restore_registry(backup_file: str | Path, db_path: str | Path) -> Path:
    """Replace the file registry with a backup. Stop the ingestion service first.

    Args:
        backup_file: A copy made by `backup_registry`.
        db_path: The registry database to replace.

    Returns:
        The path of the restored database.

    Raises:
        FileNotFoundError: If the backup does not exist.
    """
    source, destination = Path(backup_file), Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"No backup at {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
    return destination


def _storage_from_settings():
    """Create the object storage client from the environment (imported here so tests need no boto3)."""
    from shared.storage import ObjectStorage

    settings = get_settings()
    return ObjectStorage(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_region)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Command-line arguments (default: the real ones).

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m shared.backup", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("lake-backup", "lake-restore"):
        sub = commands.add_parser(name)
        sub.add_argument("directory")
        sub.add_argument("--buckets", nargs="*", help="Default: raw, clean and quarantine")
    for name in ("registry-backup", "registry-restore"):
        commands.add_parser(name).add_argument("file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    default_buckets = [settings.bucket_raw, settings.bucket_clean, settings.bucket_quarantine]

    if args.command == "lake-backup":
        result = backup_buckets(_storage_from_settings(), args.buckets or default_buckets, Path(args.directory))
    elif args.command == "lake-restore":
        result = restore_buckets(_storage_from_settings(), Path(args.directory), args.buckets)
    elif args.command == "registry-backup":
        result = {"written": str(backup_registry(settings.registry_db_path, args.file))}
    else:
        result = {"restored": str(restore_registry(args.file, settings.registry_db_path))}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
