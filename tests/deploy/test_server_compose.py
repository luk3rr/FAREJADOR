# Filename: test_server_compose.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Static checks of the production compose, env examples and units (FR-5, FR-8, FR-9, FR-16)."""

import re
from configparser import ConfigParser
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.workflows import ROOT

COMPOSE = yaml.safe_load((ROOT / "docker-compose.server.yml").read_text(encoding="utf-8"))
SERVICES: dict[str, Any] = COMPOSE["services"]


def test_there_is_no_published_port_and_no_host_networking() -> None:
    for name, service in SERVICES.items():
        assert "ports" not in service, name
        assert "expose" not in service, name
        assert service.get("network_mode") not in {"host"}, name
        assert service.get("privileged") is not True, name


@pytest.mark.parametrize("name", ["farejador", "cloudflared"])
def test_services_are_hardened_and_log_rotation_is_bounded(name: str) -> None:
    service = SERVICES[name]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "cap_add" not in service
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["restart"] == "unless-stopped"
    assert service["mem_limit"]
    logging = service["logging"]
    assert logging["driver"] == "json-file"
    assert logging["options"] == {"max-size": "10m", "max-file": "5"}


def test_the_farejador_image_comes_only_from_the_updater_env_and_never_has_a_default() -> None:
    image = SERVICES["farejador"]["image"]
    assert image.startswith("${FAREJADOR_IMAGE:?")
    assert ":-" not in image  # no fallback: a missing digest must stop the stack
    assert "build" not in SERVICES["farejador"]


def test_the_tunnel_image_is_pinned_by_version_and_digest() -> None:
    assert re.fullmatch(
        r"cloudflare/cloudflared:\d{4}\.\d+\.\d+@sha256:[0-9a-f]{64}",
        SERVICES["cloudflared"]["image"],
    )


def test_farejador_runs_in_webhook_mode_and_secrets_come_from_files_outside_the_repo() -> None:
    farejador = SERVICES["farejador"]
    assert farejador["environment"]["FAREJADOR_MODE"] == "webhook"
    assert farejador["env_file"] == "/opt/farejador/secrets/farejador.env"
    assert SERVICES["cloudflared"]["env_file"] == "/opt/farejador/secrets/cloudflared.env"
    pem = "/opt/farejador/secrets/github_app.pem:/run/secrets/github_app.pem:ro"
    assert pem in farejador["volumes"]
    assert "farejador-data:/data" in farejador["volumes"]
    assert "environment" not in SERVICES["cloudflared"]


def test_no_secret_value_is_written_in_the_compose_file() -> None:
    text = (ROOT / "docker-compose.server.yml").read_text(encoding="utf-8")
    assert not re.search(
        r"(?i)(token|secret|api_key|password)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{12,}", text
    )


def test_the_tunnel_runs_with_the_token_and_without_self_update() -> None:
    command = SERVICES["cloudflared"]["command"]
    assert command == "tunnel --no-autoupdate run"
    assert SERVICES["cloudflared"]["depends_on"] == ["farejador"]


def test_the_healthcheck_uses_the_cli_that_exists_in_the_image() -> None:
    healthcheck = SERVICES["farejador"]["healthcheck"]
    assert healthcheck["test"] == ["CMD", "farejador", "healthcheck"]
    cli = (ROOT / "src" / "farejador" / "cli.py").read_text(encoding="utf-8")
    assert "healthcheck" in cli


def test_the_stack_has_a_private_network_and_a_named_volume() -> None:
    assert "internal" in COMPOSE["networks"]
    assert "farejador-data" in COMPOSE["volumes"]


def test_env_examples_list_the_variables_the_app_needs_and_hold_no_values() -> None:
    farejador = (ROOT / "deploy" / "farejador.env.example").read_text(encoding="utf-8")
    for variable in (
        "FAREJADOR_GITHUB_APP_ID",
        "FAREJADOR_GITHUB_PRIVATE_KEY_PATH",
        "FAREJADOR_WEBHOOK_SECRET",
        "FAREJADOR_OPENROUTER_API_KEY",
        "FAREJADOR_MODEL",
    ):
        assert re.search(rf"^{variable}=", farejador, re.M), variable
    assert "FAREJADOR_GITHUB_PRIVATE_KEY_PATH=/run/secrets/github_app.pem" in farejador
    assert not re.search(r"^FAREJADOR_MODE=", farejador, re.M)
    tunnel = (ROOT / "deploy" / "cloudflared.env.example").read_text(encoding="utf-8")
    assert re.search(r"^TUNNEL_TOKEN=$", tunnel, re.M)
    for text in (farejador, tunnel):
        for line in text.splitlines():
            if "=" in line and not line.startswith("#"):
                assert line.split("=", 1)[1] in {"", "/run/secrets/github_app.pem"}, line


def _unit(name: str) -> ConfigParser:
    parser = ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string((ROOT / "deploy" / name).read_text(encoding="utf-8"))
    return parser


def test_the_timer_runs_every_five_minutes_with_a_random_delay() -> None:
    timer = _unit("farejador-update.timer")
    assert timer["Timer"]["OnUnitActiveSec"] == "5min"
    assert timer["Timer"]["OnBootSec"] == "2min"
    assert timer["Timer"]["RandomizedDelaySec"] == "30"
    assert timer["Timer"]["Persistent"] == "true"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_the_service_runs_the_updater_once_with_a_time_limit_and_restrictions() -> None:
    service = _unit("farejador-update.service")
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["ExecStart"] == "/opt/farejador/repo/deploy/update.sh"
    assert int(service["Service"]["TimeoutStartSec"]) >= 600
    assert service["Service"]["NoNewPrivileges"] == "true"
    assert "network-online.target" in service["Unit"]["After"]
    assert "docker.service" in service["Unit"]["After"]


def test_the_trace_database_lives_in_the_persistent_data_volume() -> None:
    from farejador.config import Settings

    default = Settings.model_fields["trace_path"].default
    assert Path(str(default)).as_posix().endswith("/data/trace.db")
    assert "farejador-data:/data" in SERVICES["farejador"]["volumes"]
    assert "farejador-data" in COMPOSE["volumes"]
    # the volume is the only writable place besides the size-limited /tmp
    assert SERVICES["farejador"]["read_only"] is True
    # the compose does not move the trace out of the volume
    assert "FAREJADOR_TRACE_PATH" not in str(SERVICES["farejador"].get("environment", {}))


def test_the_server_env_example_documents_the_trace_settings_that_matter() -> None:
    text = (ROOT / "deploy" / "farejador.env.example").read_text(encoding="utf-8")
    for name in ("FAREJADOR_TRACE_ENABLED", "FAREJADOR_TRACE_RETENTION_DAYS"):
        assert re.search(rf"^# {name}=", text, re.M), name
    for line in text.splitlines():
        if line.startswith("# FAREJADOR_TRACE"):
            assert "=" in line  # a commented default, never a value with a secret
