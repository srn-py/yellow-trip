# services/etl/etl_service/schemas.py
"""Request and response shapes of the ETL API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.months import MONTH_PATTERN, expand_months


class LoadRequest(BaseModel):
    """Which cleaned month(s) to load into the warehouse."""

    start: str = Field(pattern=MONTH_PATTERN, examples=["2024-01"], description="First month, YYYY-MM.")
    end: str | None = Field(
        default=None,
        pattern=MONTH_PATTERN,
        examples=["2024-03"],
        description="Last month, YYYY-MM. Omit to load only `start`.",
    )
    force: bool = Field(default=False, description="Load again even if this cleaning run is already loaded.")

    @model_validator(mode="after")
    def check_range(self) -> "LoadRequest":
        """Reject reversed or excessively long ranges."""
        expand_months(self.start, self.end)
        return self

    def months(self) -> list[tuple[int, int]]:
        """Expand the request into (year, month) pairs.

        Returns:
            Every month from `start` to `end` inclusive.
        """
        return expand_months(self.start, self.end)


class LoadResult(BaseModel):
    """Result for one month."""

    label: str = Field(description="The month, e.g. '2024-01'.")
    status: str = Field(description="loaded | skipped | not_cleaned | rejected | failed")
    message: str
    load: dict | None = Field(default=None, description="The load log entry, when available.")


class LoadResponse(BaseModel):
    """Results for a (possibly multi-month) load request."""

    results: list[LoadResult]


class TransformRequest(BaseModel):
    """Which dbt command to run."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"command": "build", "select": None, "full_refresh": False}]}
    )

    command: Literal["build", "run", "test", "seed"] = Field(
        default="build",
        description="build = seeds + models + tests in dependency order (recommended).",
    )
    select: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.+*:@, ]*$",
        description=(
            "Optional dbt node selector. Leave null to build everything. "
            "Example: 'fct_trips+' builds that model and everything after it, but NOT what it depends on."
        ),
    )
    full_refresh: bool = Field(default=False, description="Rebuild incremental models (fct_trips) from scratch.")
