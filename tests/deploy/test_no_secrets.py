# Filename: test_no_secrets.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""No secret in the repository or the image (NFR-7, FR-8, C-3)."""

import re
import subprocess

import pytest
from tests.workflows import ROOT

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "openrouter key": re.compile(r"\bsk-or-[A-Za-z0-9-]{20,}\b"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jwt-like tunnel token": re.compile(r"\beyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{10,}"),
}


# The application tests hold obviously fake, secret-shaped values on purpose, to test masking and
# redaction (M-003). Everything else, including tests/deploy, is scanned.
FAKE_FIXTURE_DIRS = ("tests/",)
SCANNED_TEST_DIRS = ("tests/deploy/",)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return [name for name in result.stdout.splitlines() if (ROOT / name).is_file()]


def test_no_file_in_the_repository_contains_a_secret_shaped_value() -> None:
    offenders = []
    for name in _tracked_files():
        is_fake_fixture = name.startswith(FAKE_FIXTURE_DIRS) and not name.startswith(
            SCANNED_TEST_DIRS
        )
        if name.startswith((".aidlc/", "uv.lock")) or is_fake_fixture:
            continue
        try:
            text = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                offenders.append(f"{name}: {label}")
    assert offenders == []


def test_secret_files_are_ignored_by_git_and_the_docker_build_context() -> None:
    gitignore = (ROOT / ".gitignore").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text()
    for ignored in (".env", "*.pem"):
        assert ignored in gitignore, ignored
    for ignored in (".env", "*.pem", "secrets"):
        assert ignored in dockerignore, ignored


def test_the_server_example_files_are_the_only_env_templates_for_production() -> None:
    names = {name for name in _tracked_files() if name.startswith("deploy/") and ".env" in name}
    assert names == {"deploy/farejador.env.example", "deploy/cloudflared.env.example"}
