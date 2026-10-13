# services/ingestion/ingestion_service/schemas.py
"""Request and response shapes of the API (validated automatically by Pydantic)."""

from pydantic import BaseModel, Field, model_validator

# "YYYY-MM" with a valid month
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
MAX_MONTHS_PER_REQUEST = 36


def _to_tuple(value: str) -> tuple[int, int]:
    """Convert "2024-01" into (2024, 1)."""
    year, month = value.split("-")
    return int(year), int(month)


class TripDownloadRequest(BaseModel):
    """Which month(s) of yellow taxi data to download."""

    start: str = Field(pattern=MONTH_PATTERN, examples=["2024-01"], description="First month, YYYY-MM.")
    end: str | None = Field(
        default=None,
        pattern=MONTH_PATTERN,
        examples=["2024-03"],
        description="Last month, YYYY-MM. Omit to download only `start`.",
    )

    @model_validator(mode="after")
    def check_range(self) -> "TripDownloadRequest":
        """Reject reversed or excessively long ranges."""
        if self.end is not None and _to_tuple(self.end) < _to_tuple(self.start):
            raise ValueError("'end' must not be before 'start'")
        if len(self.months()) > MAX_MONTHS_PER_REQUEST:
            raise ValueError(f"At most {MAX_MONTHS_PER_REQUEST} months per request")
        return self

    def months(self) -> list[tuple[int, int]]:
        """Expand the request into a list of (year, month) pairs.

        Returns:
            Every month from `start` to `end` inclusive.
        """
        start = _to_tuple(self.start)
        end = _to_tuple(self.end) if self.end else start
        result = []
        year, month = start
        while (year, month) <= end:
            result.append((year, month))
            month += 1
            if month > 12:
                year, month = year + 1, 1
        return result


class FileRecord(BaseModel):
    """One row of the file registry."""

    id: int
    sha256: str
    filename: str
    dataset: str
    file_format: str
    source: str
    bucket: str
    object_key: str
    size_bytes: int
    row_count: int | None = None
    year: int | None = None
    month: int | None = None
    ingested_at: str


class IngestOutcome(BaseModel):
    """Result for one file or month."""

    label: str = Field(description="What this result refers to, e.g. '2024-01'.")
    status: str = Field(description="ingested | duplicate | skipped | not_available | rejected | failed")
    message: str
    file: FileRecord | None = None


class DownloadResponse(BaseModel):
    """Results for a (possibly multi-month) download request."""

    results: list[IngestOutcome]


class FileListResponse(BaseModel):
    """List of registry records."""

    count: int
    files: list[FileRecord]
