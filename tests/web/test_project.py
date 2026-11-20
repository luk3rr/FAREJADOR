# Filename: test_project.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The front-end project keeps a tiny, reproducible supply chain (NFR-5, NFR-11, C-6)."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "web"
PACKAGE = json.loads((WEB / "package.json").read_text())
LOCK = json.loads((WEB / "package-lock.json").read_text())
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def test_the_only_dependency_is_typescript_at_an_exact_version_and_only_for_development() -> None:
    assert PACKAGE["devDependencies"].keys() == {"typescript"}
    assert EXACT_VERSION.fullmatch(PACKAGE["devDependencies"]["typescript"])
    for kind in ("dependencies", "optionalDependencies", "peerDependencies", "bundledDependencies"):
        assert kind not in PACKAGE, kind


def test_the_package_is_private_and_uses_es_modules() -> None:
    assert PACKAGE["private"] is True
    assert PACKAGE["type"] == "module"
    assert "publishConfig" not in PACKAGE


def test_the_scripts_are_the_ones_the_design_and_the_verification_command_use() -> None:
    assert set(PACKAGE["scripts"]) == {"check", "build", "test"}
    assert PACKAGE["scripts"]["check"].startswith("tsc --noEmit")
    for name, command in PACKAGE["scripts"].items():
        assert not re.search(r"\b(curl|wget|npx|sudo)\b|\|\s*(ba)?sh", command), name


def test_no_lifecycle_script_runs_on_install() -> None:
    for hook in ("preinstall", "install", "postinstall", "prepare", "prepublish"):
        assert hook not in PACKAGE.get("scripts", {}), hook


def test_the_lockfile_holds_exactly_one_package_with_integrity_and_no_install_script() -> None:
    assert LOCK["lockfileVersion"] >= 3
    packages = LOCK["packages"]
    assert set(packages) == {"", "node_modules/typescript"}
    typescript = packages["node_modules/typescript"]
    assert typescript["version"] == PACKAGE["devDependencies"]["typescript"]
    assert typescript["integrity"].startswith("sha512-")
    assert typescript["resolved"].startswith("https://registry.npmjs.org/")
    assert "hasInstallScript" not in typescript
    assert "dependencies" not in typescript and "optionalDependencies" not in typescript
    assert packages[""]["devDependencies"] == PACKAGE["devDependencies"]


def test_npm_never_runs_package_scripts_in_this_project() -> None:
    npmrc = dict(
        line.split("=", 1) for line in (WEB / ".npmrc").read_text().splitlines() if "=" in line
    )
    assert npmrc["ignore-scripts"] == "true"
    assert npmrc["save-exact"] == "true"


def test_the_node_version_is_pinned_to_an_exact_release() -> None:
    assert EXACT_VERSION.fullmatch((WEB / ".nvmrc").read_text().strip())
    assert PACKAGE["engines"]["node"].startswith(">=")


@pytest.mark.parametrize(
    "flag",
    [
        "strict",
        "noUncheckedIndexedAccess",
        "exactOptionalPropertyTypes",
        "noImplicitOverride",
        "noUnusedLocals",
        "noUnusedParameters",
        "verbatimModuleSyntax",
    ],
)
def test_the_compiler_runs_in_strict_mode(flag: str) -> None:
    options = json.loads((WEB / "tsconfig.json").read_text())["compilerOptions"]
    assert options[flag] is True
    assert options["types"] == []  # no ambient packages sneak in
    assert options["skipLibCheck"] is False


def test_the_tests_compile_with_the_same_strict_options() -> None:
    config = json.loads((WEB / "tsconfig.test.json").read_text())
    assert config["extends"] == "./tsconfig.json"
    assert "strict" not in config.get("compilerOptions", {})  # nothing is loosened


def test_the_build_output_and_node_modules_are_ignored_by_git_and_docker() -> None:
    gitignore = (ROOT / ".gitignore").read_text()
    for entry in ("web/node_modules/", "web/.test-build/", "src/farejador/web/static/"):
        assert entry in gitignore, entry
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    for entry in ("web/node_modules", "web/.test-build", "src/farejador/web/static"):
        assert entry in dockerignore, entry


def test_the_icon_is_the_project_icon() -> None:
    assert (WEB / "static" / "icon.png").read_bytes() == (
        ROOT / "docs" / "img" / "icon-128.png"
    ).read_bytes()
