# services/ingestion/ingestion_service/downloader.py
"""Downloading files from the web, with retries.

Networks fail. A robust pipeline retries temporary errors (timeouts, 5xx) with
growing waits ("exponential backoff") but gives up at once on "file does not
exist", because retrying cannot fix that.
"""

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# 10 MB steps so a 50 MB file never sits fully in memory.
_CHUNK_SIZE = 1024 * 1024


class DownloadError(Exception):
    """A download failed even after retries."""


class DataNotAvailableError(DownloadError):
    """The server says the file does not exist (TLC has not published it yet)."""


def build_trip_filename(year: int, month: int) -> str:
    """Build the official TLC file name for a month.

    Args:
        year: Four-digit year.
        month: Month 1 to 12.

    Returns:
        e.g. "yellow_tripdata_2024-01.parquet".
    """
    return f"yellow_tripdata_{year}-{month:02d}.parquet"


def build_trip_url(base_url: str, year: int, month: int) -> str:
    """Build the download URL for a month of trip data.

    Args:
        base_url: Base address from settings (TLC_BASE_URL).
        year: Four-digit year.
        month: Month 1 to 12.

    Returns:
        The full URL.
    """
    return f"{base_url.rstrip('/')}/{build_trip_filename(year, month)}"


def download_to_file(url: str, dest: Path, max_retries: int = 3, backoff_seconds: float = 2.0) -> None:
    """Stream a URL to a local file, retrying temporary failures.

    Args:
        url: Address to download.
        dest: Local file to write.
        max_retries: Total attempts before giving up.
        backoff_seconds: Wait before the 2nd attempt; doubles each time.

    Raises:
        DataNotAvailableError: On HTTP 403/404 (file not published). Not retried.
        DownloadError: If every attempt failed.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Downloading %s (attempt %d/%d)", url, attempt, max_retries)
            with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as response:
                # The TLC host answers 403 (not 404) for files that do not exist.
                if response.status_code in (403, 404):
                    raise DataNotAvailableError(
                        f"Not available (HTTP {response.status_code}): {url}. "
                        "TLC publishes data with a delay of a couple of months."
                    )
                response.raise_for_status()
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK_SIZE):
                        handle.write(chunk)
            return
        except DataNotAvailableError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            if attempt < max_retries:
                wait = backoff_seconds * 2 ** (attempt - 1)
                logger.warning("Download failed (%s). Waiting %.0fs before retry.", exc, wait)
                time.sleep(wait)
    raise DownloadError(f"Download failed after {max_retries} attempts: {last_error}")
