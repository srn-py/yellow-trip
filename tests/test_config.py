# tests/test_config.py
from shared.config import Settings


def test_defaults_are_sensible():
    # _env_file=None ignores any local .env so the test is reproducible.
    settings = Settings(_env_file=None)
    assert settings.bucket_raw == "raw"
    assert settings.download_max_retries == 3


def test_environment_variable_overrides_default(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert Settings(_env_file=None).log_level == "DEBUG"
