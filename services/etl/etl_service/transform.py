# services/etl/etl_service/transform.py
"""Runs dbt and turns its output into a clear summary.

dbt is a command-line tool, so we run it as a subprocess. Safety: the command is built as a
list of arguments (never passed through a shell), only a short list of dbt commands is
allowed, and the `select` text is checked, so an API caller cannot sneak in extra flags.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from shared.config import Settings

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = ("build", "run", "test", "seed")

# dbt node selectors: names, `+` for dependencies, `tag:x`, `*` wildcards, spaces between several.
# Must not start with `-`, so it can never be read as a flag.
_SELECT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+*:@, ]*$")

_BAD_STATUSES = {"error", "fail", "warn", "runtime error"}


class TransformBusyError(RuntimeError):
    """Another dbt run is already in progress."""


def validate_select(select: str) -> str:
    """Check a dbt node selector.

    Args:
        select: Text such as "fct_trips+" or "tag:marts".

    Returns:
        The selector, unchanged, if it is acceptable.

    Raises:
        ValueError: If it contains characters that could be misread as options.
    """
    if not _SELECT_PATTERN.match(select):
        raise ValueError(f"Invalid selector: {select!r}")
    return select


def build_dbt_args(command: str, project_dir: str, select: str | None = None, full_refresh: bool = False) -> list[str]:
    """Assemble the dbt command line.

    Args:
        command: One of `ALLOWED_COMMANDS`.
        project_dir: Folder holding `dbt_project.yml` and `profiles.yml`.
        select: Optional node selector.
        full_refresh: Rebuild incremental models from scratch (not valid for `test`).

    Returns:
        The argument list.

    Raises:
        ValueError: If the command is not allowed or the selector is invalid.
    """
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"Command must be one of {ALLOWED_COMMANDS}")
    args = [
        "dbt",
        "--no-use-colors",
        command,
        "--project-dir",
        project_dir,
        "--profiles-dir",
        project_dir,
    ]
    if select:
        args += ["--select", *validate_select(select).split()]
    if full_refresh and command != "test":
        args.append("--full-refresh")
    return args


def summarize_run_results(data: dict) -> dict:
    """Condense dbt's `run_results.json` into counts and a list of problems.

    Args:
        data: Parsed content of `target/run_results.json`.

    Returns:
        A dict with `total`, `counts` per status, `problems` and dbt's own `elapsed_seconds`.
    """
    counts: dict[str, int] = {}
    problems = []
    results = data.get("results", [])
    for result in results:
        status = str(result.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        if status in _BAD_STATUSES:
            problems.append(
                {
                    "node": result.get("unique_id"),
                    "status": status,
                    "message": str(result.get("message") or "")[:500],
                    "failures": result.get("failures"),
                }
            )
    return {
        "total": len(results),
        "counts": counts,
        "problems": problems,
        "elapsed_seconds": data.get("elapsed_time"),
    }


class TransformRunner:
    """Runs dbt, one command at a time."""

    def __init__(self, settings: Settings):
        self._project_dir = settings.dbt_project_dir
        self._timeout = settings.dbt_timeout_seconds
        self._lock = threading.Lock()
        self._last_run: dict | None = None

    @property
    def _target_dir(self) -> Path:
        return Path(self._project_dir) / "target"

    def run(self, command: str = "build", select: str | None = None, full_refresh: bool = False) -> dict:
        """Run a dbt command (`build` = seeds, models and tests in dependency order).

        Args:
            command: One of `ALLOWED_COMMANDS`.
            select: Optional node selector.
            full_refresh: Rebuild incremental models from scratch.

        Returns:
            A summary dict (see `_execute_and_summarize`).

        Raises:
            TransformBusyError: Another dbt run is in progress.
            ValueError: Invalid command or selector.
        """
        args = build_dbt_args(command, self._project_dir, select, full_refresh)
        return self._execute_and_summarize(" ".join(args[2:3]), args)

    def generate_docs(self) -> dict:
        """Generate the dbt documentation site (served at `/dbt-docs/`).

        Returns:
            A summary dict.

        Raises:
            TransformBusyError: Another dbt run is in progress.
        """
        args = [
            "dbt", "--no-use-colors", "docs", "generate",
            "--project-dir", self._project_dir, "--profiles-dir", self._project_dir,
        ]  # fmt: skip
        return self._execute_and_summarize("docs generate", args)

    def last_run(self) -> dict | None:
        """Return the summary of the most recent run.

        Returns:
            The summary, or None if nothing has run yet.
        """
        if self._last_run is None:
            path = self._target_dir / "last_run.json"
            if path.exists():
                self._last_run = json.loads(path.read_text())
        return self._last_run

    def _execute(self, args: list[str]) -> tuple[int, str]:
        """Run the command; return (exit code, combined output). Replaced by a fake in tests."""
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=self._project_dir,
                timeout=self._timeout,
                check=False,
                env={**os.environ},
            )
            return completed.returncode, completed.stdout + completed.stderr
        except subprocess.TimeoutExpired:
            return -1, f"dbt did not finish within {self._timeout} seconds and was stopped."

    def _read_run_results(self, not_before: float) -> dict | None:
        """Read dbt's result file, but only if it was written by the run that just finished."""
        path = self._target_dir / "run_results.json"
        if not path.exists() or path.stat().st_mtime < not_before - 1:
            return None
        return json.loads(path.read_text())

    def _execute_and_summarize(self, label: str, args: list[str]) -> dict:
        """Run under the lock and build the summary returned by the API."""
        if not self._lock.acquire(blocking=False):
            raise TransformBusyError("A dbt run is already in progress. Try again when it has finished.")
        try:
            started_wall = time.time()
            started = datetime.now(UTC)
            began = time.monotonic()
            logger.info("Running: %s", " ".join(args))
            returncode, output = self._execute(args)

            results = self._read_run_results(started_wall)
            summary = {
                "command": label,
                "success": returncode == 0,
                "return_code": returncode,
                "started_at": started.isoformat(timespec="seconds"),
                "duration_seconds": round(time.monotonic() - began, 1),
                "results": summarize_run_results(results) if results else None,
                "log_tail": output.strip().splitlines()[-40:],
            }
            self._last_run = summary
            try:
                self._target_dir.mkdir(parents=True, exist_ok=True)
                (self._target_dir / "last_run.json").write_text(json.dumps(summary, indent=2))
            except OSError:
                logger.warning("Could not save last_run.json")
            return summary
        finally:
            self._lock.release()
