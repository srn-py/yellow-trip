
"""Security and operations rules for the production stack, written as tests so they cannot erode quietly."""

import re
from pathlib import Path

import pytest
import yaml
from compose_helpers import env_keys, required_variables

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_TEXT = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
SERVICES = COMPOSE["services"]
NAMES = sorted(SERVICES)

APP_SERVICES = [
    "ingestion",
    "cleaning",
    "etl",
    "analytics",
    "dashboard",
    "quality",
    "warehouse",
    "airflow-db",
    "airflow",
]

CADDYFILES = ["deploy/Caddyfile", "deploy/Caddyfile.local"]
LOGIN_PROTECTED = {"dashboard", "airflow", "ingestion"}


def test_only_the_reverse_proxy_publishes_ports():
    assert [name for name in NAMES if "ports" in SERVICES[name]] == ["caddy"]


@pytest.mark.parametrize("name", NAMES)
def test_every_service_restarts_rotates_logs_and_has_a_memory_limit(name):
    service = SERVICES[name]
    assert service.get("restart") in {"unless-stopped", "always"}
    assert service["logging"]["options"]["max-size"]
    assert service["deploy"]["resources"]["limits"]["memory"]


@pytest.mark.parametrize("name", APP_SERVICES)
def test_every_application_service_has_a_healthcheck(name):
    assert SERVICES[name]["healthcheck"]["test"]


def test_secrets_are_passed_per_service_never_through_a_shared_env_file():
    assert [name for name in NAMES if "env_file" in SERVICES[name]] == []


def test_the_dashboard_and_the_proxy_never_receive_the_database_or_storage_secrets():
    for name in ("dashboard", "caddy"):
        environment = SERVICES[name]["environment"]
        assert not {
            "POSTGRES_PASSWORD",
            "S3_SECRET_KEY",
            "S3_ACCESS_KEY",
        } & set(environment)


def test_no_service_sets_a_fixed_container_name_so_it_never_clashes_with_the_development_stack():
    assert [name for name in NAMES if "container_name" in SERVICES[name]] == []


def test_databases_and_the_object_store_are_not_reachable_from_the_proxy_network():
    for name in (
        "warehouse",
        "airflow-db",
        "objectstore",
        "prometheus",
        "alertmanager",
        "cleaning",
        "etl",
        "analytics",
    ):
        assert SERVICES[name]["networks"] == ["backend"], name


def test_the_proxy_is_on_the_edge_network_only():
    assert SERVICES["caddy"]["networks"] == ["edge"]


def test_every_variable_the_stack_cannot_start_without_is_in_the_example_env_file():
    example = env_keys(
        (ROOT / ".env.prod.example").read_text(encoding="utf-8")
    )
    assert required_variables(COMPOSE_TEXT) - example == set()


def test_the_secret_files_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.prod" in ignored
    assert "backups/" in ignored


def test_the_stack_contains_every_part_of_the_development_platform():
    expected = {
        "caddy",
        "objectstore",
        "ingestion",
        "cleaning",
        "warehouse",
        "etl",
        "analytics",
        "dashboard",
        "quality",
        "airflow-db",
        "airflow",
        "prometheus",
        "alertmanager",
        "grafana",
    }
    assert expected <= set(SERVICES)


def caddy_blocks(text: str) -> dict[str, str]:
    """Split a Caddyfile into {site address: block text}."""
    blocks = {}
    current = None

    for line in text.splitlines():
        if (
            line
            and not line[0].isspace()
            and line.rstrip().endswith("{")
            and line[0] not in "({"
        ):
            current = line.rstrip(" {")
            blocks[current] = ""
        elif current is not None:
            blocks[current] += line + "\n"

    return blocks


@pytest.mark.parametrize("path", CADDYFILES)
def test_the_proxy_only_forwards_to_services_that_exist_on_the_edge_network(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    targets = re.findall(r"reverse_proxy\s+([a-z-]+):\d+", text)

    assert sorted(set(targets)) == [
        "airflow",
        "dashboard",
        "grafana",
        "ingestion",
    ]

    for target in targets:
        assert "edge" in SERVICES[target]["networks"], target


@pytest.mark.parametrize("path", CADDYFILES)
def test_everything_except_grafana_sits_behind_the_login(path):
    blocks = caddy_blocks((ROOT / path).read_text(encoding="utf-8"))

    assert len(blocks) == 4

    for address, block in blocks.items():
        match = re.search(r"reverse_proxy\s+([a-z-]+):", block)
        assert match is not None, f"No reverse_proxy target in {address}"

        target = match.group(1)

        if target in LOGIN_PROTECTED:
            assert "import ops_auth" in block, address
        else:
            assert target == "grafana", address


def test_the_production_caddyfile_forces_https_headers():
    text = (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")

    assert "Strict-Transport-Security" in text
    assert "{$ACME_EMAIL}" in text
