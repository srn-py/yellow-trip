# shared/config.py
"""Central configuration for all services.

Why this file exists
--------------------
Settings such as passwords, URLs and bucket names must not be hard-coded in
source code: they differ between your laptop and a production server, and
secrets must never be committed to Git. Instead we read them from
*environment variables* (which Docker Compose fills from the `.env` file).

`pydantic-settings` does the reading and also validates types, so a typo such
as DROPZONE_POLL_SECONDS=abc fails immediately with a clear error.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration values, with safe development defaults.

    Each attribute maps to an environment variable with the same name in
    upper case (`log_level` <- `LOG_LEVEL`). If the variable is missing, the
    default written here is used.
    """

    # Read a local `.env` file if present (handy when running outside Docker).
    # Real environment variables always take priority over the file.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------
    environment: str = "dev"
    log_level: str = "INFO"

    # --- Object storage (S3-compatible data lake) ----------------------------
    s3_endpoint_url: str = "http://objectstore:9000"
    s3_access_key: str = "platform_admin"
    s3_secret_key: str = "change-me-please-123"
    s3_region: str = "us-east-1"

    # Buckets are the top-level "folders" of the lake (medallion layers).
    bucket_raw: str = "raw"  # Bronze: files exactly as received
    bucket_clean: str = "clean"  # Silver: validated, typed data
    bucket_quarantine: str = "quarantine"  # Rows rejected during cleaning

    # --- Data sources and ingestion --------------------------------------------
    tlc_base_url: str = "https://d37ci6vzurychx.cloudfront.net/trip-data"
    tlc_zone_lookup_url: str = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
    download_max_retries: int = 3
    dropzone_dir: str = "/data/dropzone"
    dropzone_poll_seconds: int = 10
    registry_db_path: str = "/data/registry/registry.db"

    # --- Cleaning service (Milestone 3) ------------------------------------------
    # Where the cleaning service finds the file registry (via the ingestion API).
    ingestion_url: str = "http://ingestion:8000"
    # Memory DuckDB may use while working on one month; it spills to disk beyond this.
    duckdb_memory_limit: str = "2GB"
    # Validation thresholds. A trip beyond any of these is treated as a data error.
    max_trip_distance_miles: float = 100.0
    max_trip_hours: float = 24.0
    max_speed_mph: float = 100.0
    max_passengers: int = 6

    # --- Warehouse and ETL service (Milestone 4) ---------------------------------
    postgres_host: str = "warehouse"
    postgres_port: int = 5432
    postgres_db: str = "taxi_dw"
    postgres_user: str = "taxi"
    postgres_password: str = "change-me-too-456"
    # Where the ETL service finds cleaning reports.
    cleaning_url: str = "http://cleaning:8000"
    etl_url: str = "http://etl:8000"  # where the quality service finds the ETL service
    # Folder of the dbt project inside the ETL container, and a safety time limit for dbt runs.
    dbt_project_dir: str = "/app/dbt"
    dbt_timeout_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, created once and then reused.

    `lru_cache` makes this function remember its first result, so the
    environment is read a single time per process.

    Returns:
        The shared `Settings` instance.
    """
    return Settings()
