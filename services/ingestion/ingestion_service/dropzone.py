# services/ingestion/ingestion_service/dropzone.py
"""Watch a folder and ingest any file that appears in it.

Copy a file into `data/dropzone/` on your machine and, within a few seconds, it
is ingested. Afterwards it is moved to `processed/` (success) or `failed/`
(unsupported or corrupt), so the folder always shows what is still waiting.

We use simple *polling* (look at the folder every N seconds). It is less
fancy than file-system events but works the same on every OS and in Docker.
"""

import asyncio
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from .file_utils import UnreadableFileError, UnsupportedFormatError
from .ingest import SOURCE_DROPZONE, IngestionService

logger = logging.getLogger(__name__)


class DropzoneWatcher:
    """Polls a folder and feeds new files to the ingestion service."""

    def __init__(
        self,
        folder: str,
        service: IngestionService,
        poll_seconds: int = 10,
        settle_seconds: float = 2.0,
    ):
        self._folder = Path(folder)
        self._processed = self._folder / "processed"
        self._failed = self._folder / "failed"
        self._service = service
        self._poll_seconds = poll_seconds
        # A file modified a moment ago may still be mid-copy; wait until it settles.
        self._settle_seconds = settle_seconds

    def scan_once(self) -> int:
        """Look at the folder once and ingest everything ready.

        Returns:
            Number of files handled (moved to processed/ or failed/).
        """
        for folder in (self._folder, self._processed, self._failed):
            folder.mkdir(parents=True, exist_ok=True)

        handled = 0
        for path in sorted(self._folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if time.time() - path.stat().st_mtime < self._settle_seconds:
                continue  # probably still being copied
            try:
                result = self._service.ingest_file(path, path.name, SOURCE_DROPZONE)
                logger.info("Dropzone: %s -> %s", path.name, result.status)
                self._move(path, self._processed)
                handled += 1
            except (UnsupportedFormatError, UnreadableFileError) as exc:
                logger.warning("Dropzone: rejected %s (%s)", path.name, exc)
                self._move(path, self._failed)
                handled += 1
            except Exception:
                # Probably temporary (e.g. storage down). Leave the file; retry next scan.
                logger.exception("Dropzone: error while ingesting %s", path.name)
        return handled

    @staticmethod
    def _move(path: Path, target_folder: Path) -> None:
        """Move a file, prefixing a timestamp so names never collide.

        Args:
            path: File to move.
            target_folder: Destination folder.
        """
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        shutil.move(str(path), str(target_folder / f"{stamp}_{path.name}"))

    async def run_forever(self) -> None:
        """Scan repeatedly until the task is cancelled (at service shutdown)."""
        logger.info("Dropzone watcher started on %s", self._folder)
        while True:
            try:
                # scan_once does blocking work, so run it in a worker thread.
                await asyncio.to_thread(self.scan_once)
            except Exception:
                logger.exception("Dropzone scan failed")
            await asyncio.sleep(self._poll_seconds)
