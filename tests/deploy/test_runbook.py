# Filename: test_runbook.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The runbook agrees with the code it describes (FR-13, FR-14, FR-17, NFR-3.1, NFR-3.3, NFR-8)."""

import re
from pathlib import Path

import pytest
from tests.workflows import ROOT

from farejador.config import Settings

DOCS = ROOT / "docs" / "deploy"

# The runbook is kept out of the public repository on purpose (see .gitignore); these checks run
# wherever it exists, which is on the maintainer machine.
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="runbook is kept local, not in git")
GUIDES = sorted(path for path in DOCS.glob("*.md"))
STEP_GUIDES = [path for path in GUIDES if path.name != "README.md"]


def _all_text() -> str:
    return "\n".join(path.read_text() for path in GUIDES)


def test_all_the_expected_guides_exist() -> None:
    assert {path.name for path in GUIDES} == {
        "README.md",
        "01-aws.md",
        "02-cloudflare.md",
        "03-github.md",
        "04-primeiro-deploy.md",
        "05-operacao.md",
        "06-recuperacao.md",
    }


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_each_guide_records_when_its_screens_were_last_checked(path: Path) -> None:
    assert re.search(r"^Conferido em: \d{4}-\d{2}-\d{2}", path.read_text(), re.M)


@pytest.mark.parametrize("path", STEP_GUIDES, ids=lambda p: p.name)
def test_each_step_section_says_what_to_expect(path: Path) -> None:
    text = path.read_text()
    sections = re.split(r"^## ", text, flags=re.M)[1:]
    steps = [s for s in sections if re.match(r"\d+\.\d+ ", s)]
    for section in steps:
        title = section.splitlines()[0]
        assert "Resultado esperado" in section, f"{path.name}: '{title}' has no expected result"


def test_there_is_a_procedure_for_every_secret_and_for_recovery() -> None:
    text = (DOCS / "06-recuperacao.md").read_text()
    for secret in (
        "Segredo do webhook",
        "Chave da OpenRouter",
        "Chave privada do GitHub App",
        "Token do túnel",
        "Chave SSH",
    ):
        assert secret in text, secret
    for heading in ("snapshot", "Refazer do zero", "Desligar tudo"):
        assert heading in text, heading
    assert "Tempo" in text or "tempo" in text


def test_the_post_deploy_checklist_covers_the_required_checks() -> None:
    text = (DOCS / "04-primeiro-deploy.md").read_text()
    for needle in (
        "verify_deploy.sh external",
        "ping",
        "200",
        "Pull request de teste",
        "luk3rr.com",
    ):
        assert needle in text, needle
    assert "verify_deploy.sh server" in text


def test_every_repository_path_the_runbook_names_exists() -> None:
    missing = []
    pattern = re.compile(
        r"(?<![\w/])((?:deploy|scripts|docs)/[\w./-]+\.(?:sh|md|service|timer|yml|example))"
    )
    for match in pattern.finditer(_all_text()):
        if not (ROOT / match.group(1)).exists():
            missing.append(match.group(1))
    assert missing == []


def test_the_server_paths_match_the_ones_the_scripts_and_compose_use() -> None:
    text = _all_text()
    compose = (ROOT / "docker-compose.server.yml").read_text()
    update = (ROOT / "deploy" / "update.sh").read_text()
    for path in (
        "/opt/farejador/secrets/farejador.env",
        "/opt/farejador/secrets/cloudflared.env",
        "/opt/farejador/secrets/github_app.pem",
    ):
        assert path in compose, path
    for path in ("/opt/farejador/image.env", "/var/lib/farejador-update"):
        assert path in text, path
    assert 'STATE_DIR="${FAREJADOR_UPDATE_STATE_DIR:-/var/lib/farejador-update}"' in update
    assert "/opt/farejador/repo/deploy/update.sh" in text
    assert "/opt/farejador/repo/docker-compose.server.yml" in text


def test_every_variable_the_runbook_names_is_a_real_setting() -> None:
    settings_fields = {f"FAREJADOR_{name.upper()}" for name in Settings.model_fields}
    named = set(re.findall(r"\bFAREJADOR_[A-Z_]+\b", _all_text()))
    runbook_only = {"FAREJADOR_IMAGE"}
    assert named - settings_fields - runbook_only == set()
    example = (ROOT / "deploy" / "farejador.env.example").read_text()
    for variable in named & settings_fields:
        assert variable in example, f"{variable} is in the runbook but not in the env example"


def test_the_runbook_names_the_values_the_cloudflare_rules_need() -> None:
    text = (DOCS / "02-cloudflare.md").read_text()
    for needle in (
        "hooks.luk3rr.com",
        "^/webhook$",
        "farejador:8080",
        "http_status:404",
        'http.request.uri.path eq "/webhook"',
        "api.github.com/meta",
        "30 requisições",
    ):
        assert needle in text, needle
    compose = (ROOT / "docker-compose.server.yml").read_text()
    assert "container_name: farejador" in compose
    assert 'FAREJADOR_PORT: "8080"' in compose


def test_the_github_steps_match_the_release_workflow() -> None:
    text = (DOCS / "03-github.md").read_text()
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "environment: production" in release
    for needle in ("`production`", "Required reviewers", "v*", "Restrict deletions"):
        assert needle in text, needle
    assert "https://hooks.luk3rr.com/webhook" in text
    for allowed in ("astral-sh/setup-uv", "sigstore/cosign-installer", "docker/*"):
        assert allowed in text, allowed


def test_the_apex_domain_is_never_modified_by_any_step() -> None:
    text = (DOCS / "02-cloudflare.md").read_text()
    assert "luk3rr.com` (a página estática) **não é tocado**" in text
    for line in text.splitlines():
        assert not re.search(
            r"(?i)\b(apague|edite|altere|remova)\b.*registro.*(luk3rr\.com)\b", line
        )


def test_the_port_22_is_always_closed_again() -> None:
    for name in ("04-primeiro-deploy.md", "05-operacao.md"):
        text = (DOCS / name).read_text()
        assert "porta 22" in text or "SSH" in text
    assert "Fechar a porta 22" in (DOCS / "04-primeiro-deploy.md").read_text()
    assert "Nunca** deixe a porta 22 aberta" in (DOCS / "README.md").read_text()


def test_no_secret_value_or_dangerous_install_pattern_is_in_the_runbook() -> None:
    text = _all_text()
    assert not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", text)
    assert not re.search(r"\beyJ[A-Za-z0-9_-]{30,}", text)
    assert not re.search(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b", text)
    assert "0.0.0.0/0" not in text


def test_the_commands_in_code_blocks_use_the_scripts_with_valid_arguments() -> None:
    text = _all_text()
    for usage in re.findall(r"verify_deploy\.sh (\w+)", text):
        assert usage in {"external", "server"}, usage
    assert "update.sh --check" in text
    assert "sudo bash deploy/bootstrap.sh" in text


def test_the_readme_links_to_every_guide() -> None:
    readme = (DOCS / "README.md").read_text()
    for path in STEP_GUIDES:
        assert f"({path.name}" in readme, path.name
