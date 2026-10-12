# services/ingestion/ingestion_service/file_utils.py
"""Helpers for inspecting files before they enter the data lake.

We never modify incoming files. We only *look* at them: detect the format,
compute a checksum (fingerprint), and count rows. Counting rows doubles as a
cheap check that the file is really readable and not corrupt.
"""

import hashlib
import json
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

# File extension -> logical format name. ".json" is treated as newline-delimited
# JSON (one JSON object per line), the usual layout for large JSON data files.
SUPPORTED_EXTENSIONS = {
    ".parquet": "parquet",
    ".csv": "csv",
    ".json": "ndjson",
    ".ndjson": "ndjson",
    ".jsonl": "ndjson",
}

CONTENT_TYPES = {
    "parquet": "application/vnd.apache.parquet",
    "csv": "text/csv",
    "ndjson": "application/x-ndjson",
}

# Official TLC file names look like: yellow_tripdata_2024-01.parquet
TRIP_FILENAME_PATTERN = re.compile(r"^yellow_tripdata_(\d{4})-(0[1-9]|1[0-2])\.(parquet|csv)$", re.IGNORECASE)


class UnsupportedFormatError(ValueError):
    """Raised when a file's extension is not one we accept."""


class UnreadableFileError(ValueError):
    """Raised when a file has a supported extension but cannot be read (corrupt/invalid)."""


def detect_format(filename: str) -> str:
    """Work out the logical format of a file from its extension.

    Args:
        filename: File name, e.g. "yellow_tripdata_2024-01.parquet".

    Returns:
        One of "parquet", "csv" or "ndjson".

    Raises:
        UnsupportedFormatError: If the extension is not supported.
    """
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedFormatError(f"Unsupported file type '{extension}'. Allowed: {allowed}")
    return SUPPORTED_EXTENSIONS[extension]


def safe_filename(filename: str) -> str:
    """Make a file name safe to use inside an object key.

    Strips any directory part (blocks tricks like "../../x") and replaces unusual
    characters with underscores.

    Args:
        filename: The name supplied by the user or the source system.

    Returns:
        A sanitised file name.
    """
    name = Path(filename).name
    return re.sub(r"[^A-Za-z0-9._=-]", "_", name) or "unnamed"


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 checksum of a file.

    The file is read in chunks so even very large files use little memory.

    Args:
        path: File to fingerprint.
        chunk_size: Bytes to read per step.

    Returns:
        The checksum as a 64-character hexadecimal string.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_trip_filename(filename: str) -> tuple[int, int] | None:
    """Extract (year, month) from an official TLC trip file name.

    Args:
        filename: e.g. "yellow_tripdata_2024-01.parquet".

    Returns:
        (2024, 1) if the name matches the TLC pattern, otherwise None.
    """
    match = TRIP_FILENAME_PATTERN.match(filename)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def count_rows(path: Path, file_format: str) -> int:
    """Count data rows in a file, proving on the way that it is readable.

    Parquet stores the row count in its footer (instant). CSV is streamed in
    batches. NDJSON is counted line by line. None of them load the whole file
    into memory.

    Args:
        path: File to inspect.
        file_format: "parquet", "csv" or "ndjson".

    Returns:
        Number of data rows.

    Raises:
        UnreadableFileError: If the file is corrupt or not valid for its format.
    """
    try:
        if file_format == "parquet":
            return pq.ParquetFile(path).metadata.num_rows
        if file_format == "csv":
            return sum(batch.num_rows for batch in pacsv.open_csv(path))
        if file_format == "ndjson":
            return _count_ndjson_rows(path)
    except (pa.ArrowException, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise UnreadableFileError(f"File could not be read as {file_format}: {exc}") from exc
    raise UnsupportedFormatError(f"Unknown format '{file_format}'")


def _count_ndjson_rows(path: Path) -> int:
    """Count non-empty lines of a newline-delimited JSON file.

    The first non-empty line is parsed as JSON as a quick sanity check.

    Args:
        path: NDJSON file.

    Returns:
        Number of non-empty lines.
    """
    rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            if rows == 0:
                json.loads(line)  # raises JSONDecodeError if not JSON
            rows += 1
    return rows
