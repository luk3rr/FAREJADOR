# Filename: test_repo_files.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _ci() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    return loaded


def test_ci_runs_every_quality_gate_on_push_to_main() -> None:
    ci = _ci()
    triggers = ci.get("on", ci.get(True))
    assert triggers["push"]["branches"] == ["main"]
    steps = ci["jobs"]["verify"]["steps"]
    commands = " ".join(step.get("run", "") for step in steps)
    for expected in (
        "ruff check",
        "ruff format --check",
        "mypy src",
        "pytest",
        "--cov-fail-under=80",
    ):
        assert expected in commands
    assert any("sonar" in step.get("uses", "").lower() for step in steps)


def test_ci_uses_least_privilege_and_does_not_fail_without_a_sonar_token() -> None:
    ci = _ci()
    assert ci["permissions"] == {"contents": "read"}
    assert ci["concurrency"]["cancel-in-progress"] is True
    sonar = next(s for s in ci["jobs"]["verify"]["steps"] if "sonar" in s.get("uses", "").lower())
    assert "env.SONAR_TOKEN != ''" in sonar["if"]
    assert ci["jobs"]["verify"]["env"]["SONAR_TOKEN"] == "${{ secrets.SONAR_TOKEN }}"


def test_ci_builds_and_checks_the_image_after_the_quality_gates() -> None:
    image = _ci()["jobs"]["image"]
    assert image["needs"] == "verify"
    commands = " ".join(step.get("run", "") for step in image["steps"])
    assert "docker build" in commands
    assert "--profile polling config" in commands
    assert "--profile webhook config" in commands
    assert "--entrypoint id farejador:ci -u" in commands


def test_sonar_properties_have_required_keys() -> None:
    props = dict(
        line.split("=", 1)
        for line in (ROOT / "sonar-project.properties").read_text().splitlines()
        if "=" in line
    )
    for key in ("sonar.projectKey", "sonar.organization", "sonar.sources", "sonar.tests"):
        assert props.get(key)
    assert props["sonar.python.coverage.reportPaths"] == "coverage.xml"


def test_pyproject_pins_python_and_tooling() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["requires-python"] == ">=3.12"
    assert data["tool"]["mypy"]["strict"] is True
    assert (ROOT / "uv.lock").is_file()


def test_precommit_runs_ruff_and_mypy() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    ids = {hook["id"] for repo in config["repos"] for hook in repo["hooks"]}
    assert {"ruff-check", "ruff-format", "mypy"} <= ids
