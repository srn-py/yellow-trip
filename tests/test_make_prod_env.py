# tests/test_make_prod_env.py

import importlib.util
import itertools
from pathlib import Path

import pytest
from compose_helpers import env_keys, required_variables

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "make_prod_env",
    ROOT / "scripts" / "make_prod_env.py",
)
make_prod_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_prod_env)


def fake_hash(password: str) -> str:
    return "$2a$14$FAKEHASHFORTESTS"


def values(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


def build(**overrides) -> str:
    counter = itertools.count()

    arguments = {
        "domain": "taxi.example.com",
        "email": "me@example.com",
        "owner": "someone",
        "tag": "1.0.0",
        "local": False,
        "ops_user": "ops",
        "ops_password": "secret",
        "hash_password": fake_hash,
        # Generate distinct values of at least 64 characters for
        # the JWT secret, while keeping the other secrets unique.
        "rand": lambda: f"random{next(counter):04d}" + "x" * 64,
    }

    return make_prod_env.build_env_text(**{**arguments, **overrides})


def test_the_generated_file_sets_every_variable_the_stack_requires():
    compose_text = (
        ROOT / "docker-compose.prod.yml"
    ).read_text(encoding="utf-8")

    assert required_variables(compose_text) - env_keys(build()) == set()


def test_every_secret_is_long_and_different():
    data = values(build())

    secrets_ = [
        data[key]
        for key in (
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "POSTGRES_PASSWORD",
            "AIRFLOW_DB_PASSWORD",
            "GRAFANA_ADMIN_PASSWORD",
        )
    ]

    assert all(len(secret) >= 16 for secret in secrets_)
    assert len(set(secrets_)) == len(secrets_)
    assert len(data["AIRFLOW_JWT_SECRET"]) >= 64


def test_the_login_is_stored_as_a_single_quoted_hash_and_the_password_is_not_stored():
    text = build(ops_password="my-very-secret-password")

    assert "OPS_PASSWORD_HASH='$2a$14$FAKEHASHFORTESTS'" in text
    assert "my-very-secret-password" not in text


def test_production_mode_uses_the_real_domain_standard_ports_and_the_public_caddyfile():
    data = values(build())

    assert (
        data["SITE_DOMAIN"],
        data["CADDYFILE"],
        data["HTTP_PORT"],
        data["HTTPS_PORT"],
    ) == ("taxi.example.com", "Caddyfile", "80", "443")

    assert (
        data["GRAFANA_ROOT_URL"]
        == "https://grafana.taxi.example.com"
    )
    assert data["IMAGE_TAG"] == "1.0.0"


def test_local_mode_uses_localhost_high_ports_and_local_images():
    data = values(
        build(
            local=True,
            domain="localhost",
            email="",
            owner="local",
            tag="local",
        )
    )

    assert (
        data["CADDYFILE"],
        data["HTTP_PORT"],
        data["HTTPS_PORT"],
    ) == ("Caddyfile.local", "8088", "8443")

    assert (
        data["GRAFANA_ROOT_URL"]
        == "https://grafana.localhost:8443"
    )
    assert (data["GHCR_OWNER"], data["IMAGE_TAG"]) == ("local", "local")


def test_main_writes_the_file_readable_only_by_its_owner_and_will_not_overwrite(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(make_prod_env, "hash_with_caddy", fake_hash)
    target = tmp_path / ".env.prod"

    assert make_prod_env.main(["--local", "--output", str(target)]) == 0
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert "Login for the dashboard" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        make_prod_env.main(["--local", "--output", str(target)])

    assert (
        make_prod_env.main(
            ["--local", "--force", "--output", str(target)]
        )
        == 0
    )


def test_main_requires_the_deployment_details_unless_local(tmp_path):
    with pytest.raises(SystemExit):
        make_prod_env.main(["--output", str(tmp_path / "x")])

