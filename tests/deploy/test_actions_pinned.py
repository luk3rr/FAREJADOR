# Filename: test_actions_pinned.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Supply-chain checks for a public repository (FR-15, NFR-1.3, NFR-1.4, NFR-10, M-008)."""

import re

import pytest
from tests.workflows import ROOT, all_workflow_files

ALLOWED_OWNERS = {"actions", "astral-sh", "docker", "sigstore", "SonarSource"}
USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)(?P<rest>.*)$")


def _uses_lines() -> list[tuple[str, str, str]]:
    found = []
    for path in all_workflow_files():
        for line in path.read_text().splitlines():
            match = USES_LINE.match(line)
            if match:
                found.append((path.name, match["ref"], match["rest"]))
    return found


def test_the_workflows_were_found_and_use_actions() -> None:
    assert {path.name for path in all_workflow_files()} >= {"ci.yml", "release.yml"}
    assert len(_uses_lines()) >= 10


@pytest.mark.parametrize(("workflow", "ref", "rest"), _uses_lines())
def test_every_action_is_pinned_to_a_full_commit_sha_with_its_version_in_a_comment(
    workflow: str, ref: str, rest: str
) -> None:
    assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{workflow}: {ref}"
    assert re.fullmatch(r"\s*# v\d+(\.\d+)*\s*", rest), f"{workflow}: {ref} lacks a version comment"


@pytest.mark.parametrize(("workflow", "ref", "rest"), _uses_lines())
def test_actions_come_only_from_the_allowed_owners(workflow: str, ref: str, rest: str) -> None:
    assert ref.split("/")[0] in ALLOWED_OWNERS, f"{workflow}: {ref}"


def test_the_same_action_is_pinned_to_the_same_sha_everywhere() -> None:
    pinned: dict[str, set[str]] = {}
    for _, ref, _ in _uses_lines():
        name, _, sha = ref.partition("@")
        pinned.setdefault(name, set()).add(sha)
    assert {name: shas for name, shas in pinned.items() if len(shas) > 1} == {}


def test_no_workflow_uses_the_dangerous_triggers() -> None:
    for path in all_workflow_files():
        text = path.read_text()
        assert "pull_request_target" not in text, path.name
        assert "workflow_run" not in text, path.name


def test_every_workflow_limits_the_default_token_permissions() -> None:
    for path in all_workflow_files():
        text = path.read_text()
        assert re.search(r"^permissions:", text, re.M), f"{path.name} has no top-level permissions"


def test_the_image_installs_only_from_the_lockfile_and_points_to_the_repository() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert 'org.opencontainers.image.source="https://github.com/luk3rr/FAREJADOR"' in dockerfile
    assert (ROOT / "uv.lock").is_file()
