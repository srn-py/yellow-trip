# tests/test_lake.py
from shared.config import Settings
from shared.lake import build_secret_sql, trips_glob


def test_trips_glob_for_all_months():
    settings = Settings(_env_file=None)
    assert trips_glob(settings) == "s3://raw/yellow_tripdata/year=*/month=*/*.parquet"


def test_trips_glob_for_one_month():
    settings = Settings(_env_file=None)
    assert trips_glob(settings, 2024, 1) == "s3://raw/yellow_tripdata/year=2024/month=01/*.parquet"


def test_secret_uses_host_without_scheme_and_no_ssl_for_http():
    sql = build_secret_sql(Settings(_env_file=None))
    assert "'objectstore:9000'" in sql
    assert "USE_SSL false" in sql
    assert "URL_STYLE 'path'" in sql


def test_secret_escapes_single_quotes():
    sql = build_secret_sql(Settings(_env_file=None, s3_secret_key="a'b"))
    assert "'a''b'" in sql
