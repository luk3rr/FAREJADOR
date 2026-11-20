# Filename: test_docker_files.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Static checks of the packaging files: Docker is not required to run them (design A38)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from farejador.config import ENV_PREFIX, Settings

ROOT = Path(__file__).resolve().parent.parent


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return loaded


def test_both_profiles_use_the_same_image_and_differ_only_in_mode_and_port() -> None:
    services = _compose()["services"]
    assert set(services) == {"polling", "webhook"}
    assert services["polling"]["profiles"] == ["polling"]
    assert services["webhook"]["profiles"] == ["webhook"]
    assert services["polling"]["image"] == services["webhook"]["image"] == "farejador:local"
    assert services["polling"]["environment"]["FAREJADOR_MODE"] == "polling"
    assert services["webhook"]["environment"]["FAREJADOR_MODE"] == "webhook"
    assert "ports" not in services["polling"]
    assert services["webhook"]["ports"] == ["${FAREJADOR_HOST_PORT:-8080}:8080"]


@pytest.mark.parametrize("name", ["polling", "webhook"])
def test_services_follow_least_privilege(name: str) -> None:
    service = _compose()["services"][name]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["mem_limit"] == "1g"
    assert service["restart"] == "unless-stopped"
    assert any(item.startswith("/tmp:") and "size=" in item for item in service["tmpfs"])


@pytest.mark.parametrize("name", ["polling", "webhook"])
def test_state_lives_in_a_named_volume_and_the_key_is_mounted_read_only(name: str) -> None:
    compose = _compose()
    volumes = compose["services"][name]["volumes"]
    assert "farejador-data:/data" in volumes
    key_mounts = [v for v in volumes if v.endswith(":/run/secrets/github_app.pem:ro")]
    assert len(key_mounts) == 1
    assert "farejador-data" in compose["volumes"]


def test_secrets_come_from_an_env_file_not_from_the_compose_file() -> None:
    text = (ROOT / "docker-compose.yml").read_text()
    assert "env_file: ${FAREJADOR_ENV_FILE:-.env}" in text
    for secret_variable in ("OPENROUTER_API_KEY", "WEBHOOK_SECRET"):
        assert secret_variable not in text


def test_only_the_webhook_service_has_a_healthcheck() -> None:
    services = _compose()["services"]
    assert services["webhook"]["healthcheck"]["test"] == ["CMD", "farejador", "healthcheck"]
    assert "healthcheck" not in services["polling"]


def test_the_dockerfile_builds_in_two_stages_and_runs_as_non_root() -> None:
    text = (ROOT / "Dockerfile").read_text()
    assert len(re.findall(r"^FROM python:3\.13-slim", text, re.M)) == 2
    assert "AS build" in text
    assert "--frozen" in text
    assert "--no-dev" in text
    assert "apt-get install -y --no-install-recommends git ca-certificates" in text
    assert re.search(r"^USER farejador$", text, re.M)
    assert "useradd --system --uid 10001" in text
    assert 'ENTRYPOINT ["farejador"]' in text
    assert 'CMD ["run"]' in text
    assert "HEALTHCHECK" in text
    assert "FAREJADOR_STATE_PATH=/data/farejador.db" in text
    assert "FAREJADOR_HOST=0.0.0.0" in text  # the container must listen on all interfaces
    assert "EXPOSE 8080" in text


def test_the_dockerfile_never_copies_secrets_or_local_state() -> None:
    copies = re.findall(r"^COPY (?!--from).*$", (ROOT / "Dockerfile").read_text(), re.M)
    assert copies == ["COPY pyproject.toml uv.lock ./", "COPY src ./src"]


def test_dockerignore_keeps_secrets_and_noise_out_of_the_build_context() -> None:
    entries = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    for expected in (".git", ".aidlc", ".venv", "secrets", ".env", "*.pem", "*.key", "tests"):
        assert expected in entries
    assert "!.env.example" in entries


def test_the_env_example_documents_every_setting() -> None:
    text = (ROOT / ".env.example").read_text()
    documented = set(re.findall(rf"^#?\s*({ENV_PREFIX}[A-Z0-9_]+)=", text, re.M))
    expected = {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}
    assert expected <= documented
    assert not {line for line in text.splitlines() if re.match(r"^[A-Z_]+=\S", line)} - {
        "FAREJADOR_MODE=polling",
        "FAREJADOR_GITHUB_PRIVATE_KEY_PATH=/run/secrets/github_app.pem",
    }, "the example file must not contain real values"


def test_local_secrets_are_git_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text()
    for pattern in ("secrets/", ".env", "*.pem", "/data/"):
        assert pattern in ignored


def test_the_smoke_script_is_executable_and_has_the_standard_header() -> None:
    script = ROOT / "scripts" / "smoke_compose.sh"
    assert script.stat().st_mode & 0o111
    lines = script.read_text().splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1] == "# Filename: smoke_compose.sh"
    assert lines[3] == "# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>"
    assert "set -euo pipefail" in lines


def test_the_readme_documents_the_variables_the_settings_define() -> None:
    readme = (ROOT / "README.md").read_text()
    for name in Settings.model_fields:
        assert f"FAREJADOR_{name.upper()}" in readme, name
