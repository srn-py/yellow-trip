# services/cleaning/cleaning_service/engine.py
"""Runs the cleaning rules on ONE local Parquet file using DuckDB.

No network and no S3 here: the file is already on local disk, which makes this module
easy to test. DuckDB works in a file-backed database inside the job's work folder, so
big months spill to disk instead of exhausting memory.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from shared.config import Settings

from .rules import build_rules
from .sql_builder import (
    build_copy_sql,
    build_counts_sql,
    build_flagged_table_sql,
    map_columns,
    sql_literal,
)

logger = logging.getLogger(__name__)


@dataclass
class EngineResult:
    """Everything the engine learned and produced for one file."""

    rows_in: int
    rows_clean: int
    rows_quarantined: int
    clean_rows_with_missing_details: int
    clean_rows_zero_passengers: int
    rule_counts: dict[str, int]  # rows breaking each rule (a row can break several)
    renamed_columns: dict[str, str]  # source name -> clean name (only where they differ)
    columns_filled_with_null: list[str]  # standard columns the source did not have
    clean_path: Path
    quarantine_path: Path
    unmapped_columns: list[str] = field(default_factory=list)  # source columns we do not use


def run_cleaning(
    source_path: Path,
    work_dir: Path,
    year: int,
    month: int,
    source_file: str,
    settings: Settings,
) -> EngineResult:
    """Clean one month of raw trips.

    Args:
        source_path: Local raw Parquet file.
        work_dir: Folder for the output files and DuckDB's working files.
        year: Year of the file.
        month: Month of the file.
        source_file: Raw object key, written into every row for lineage.
        settings: Application settings (thresholds, memory limit).

    Returns:
        An `EngineResult` with counts and output paths.

    Raises:
        SchemaMismatchError: If a required column is missing from the source.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    spill_dir = work_dir / "spill"
    spill_dir.mkdir(exist_ok=True)
    clean_path = work_dir / "clean.parquet"
    quarantine_path = work_dir / "quarantine.parquet"
    rules = build_rules(settings)

    con = duckdb.connect(
        str(work_dir / "work.duckdb"),
        config={"memory_limit": settings.duckdb_memory_limit, "temp_directory": str(spill_dir)},
    )
    counts = None
    try:
        described = con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_literal(str(source_path))})").fetchall()
        source_names = [row[0] for row in described]
        mapping = map_columns(source_names)
        used = {actual for actual in mapping.values() if actual}
        unmapped = [name for name in source_names if name not in used]

        logger.info("Flagging rows for %d-%02d ...", year, month)
        con.execute(build_flagged_table_sql(str(source_path), mapping, year, month, source_file, rules))

        counts = con.execute(build_counts_sql(rules)).fetchone()

        logger.info("Writing clean and quarantine files ...")
        con.execute(build_copy_sql("flagged", str(clean_path), quarantined=False))
        con.execute(build_copy_sql("flagged", str(quarantine_path), quarantined=True))
    finally:
        con.close()

    if counts is None:
        raise RuntimeError("counts query returned no rows — the flagged table may be empty")

    return EngineResult(
        rows_in=int(counts[0]),
        rows_clean=int(counts[1]),
        rows_quarantined=int(counts[2]),
        clean_rows_with_missing_details=int(counts[3]),
        clean_rows_zero_passengers=int(counts[4]),
        rule_counts={rule.name: int(count) for rule, count in zip(rules, counts[5:], strict=True)},
        renamed_columns={actual: clean for clean, actual in mapping.items() if actual and actual != clean},
        columns_filled_with_null=[clean for clean, actual in mapping.items() if actual is None],
        clean_path=clean_path,
        quarantine_path=quarantine_path,
        unmapped_columns=unmapped,
    )
