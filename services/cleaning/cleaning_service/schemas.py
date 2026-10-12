# services/cleaning/cleaning_service/schemas.py
"""Request and response shapes of the cleaning API."""

from pydantic import BaseModel, Field, model_validator

from shared.months import MONTH_PATTERN, expand_months


class CleanRequest(BaseModel):
    """Which month(s) to clean."""

    start: str = Field(pattern=MONTH_PATTERN, examples=["2024-01"], description="First month, YYYY-MM.")
    end: str | None = Field(
        default=None,
        pattern=MONTH_PATTERN,
        examples=["2024-03"],
        description="Last month, YYYY-MM. Omit to clean only `start`.",
    )
    force: bool = Field(
        default=False,
        description="Clean again even if the month was already cleaned with the same file and rules.",
    )

    @model_validator(mode="after")
    def check_range(self) -> "CleanRequest":
        """Reject reversed or excessively long ranges."""
        expand_months(self.start, self.end)  # raises ValueError if the range is invalid
        return self

    def months(self) -> list[tuple[int, int]]:
        """Expand the request into (year, month) pairs.

        Returns:
            Every month from `start` to `end` inclusive.
        """
        return expand_months(self.start, self.end)


class MonthResult(BaseModel):
    """Result for one month."""

    label: str = Field(description="The month, e.g. '2024-01'.")
    status: str = Field(description="cleaned | skipped | not_ingested | rejected | failed")
    message: str
    report: dict | None = Field(default=None, description="The full cleaning report, when available.")


class CleanResponse(BaseModel):
    """Results for a (possibly multi-month) cleaning request."""

    results: list[MonthResult]
