# services/quality/quality_service/settings.py
"""Thresholds of the quality checks, read from environment variables (see `.env`)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class QualitySettings(BaseSettings):
    """Thresholds and timing of the quality checks.

    Each attribute maps to the environment variable of the same name in upper case.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    quality_interval_seconds: int = 300
    quality_startup_delay_seconds: int = 45
    quality_max_load_age_days: int = 45
    quality_rowcount_tolerance_pct: float = 40.0
    quality_min_months_for_rowcounts: int = 3
    quality_max_quarantine_pct: float = 10.0
    quality_max_dbt_age_days: int = 45


@lru_cache
def get_quality_settings() -> QualitySettings:
    """Return the quality settings, created once.

    Returns:
        The shared `QualitySettings` instance.
    """
    return QualitySettings()
