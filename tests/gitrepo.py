# Filename: gitrepo.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Builds small local git repositories for tool and workspace tests."""

import os
import subprocess
from pathlib import Path

_ENV = {
    "PATH": os.environ["PATH"],
    "HOME": "/nonexistent",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=_ENV, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_repo(path: Path, files: dict[str, str | bytes]) -> str:
    """Create a repository at ``path`` with ``files`` committed; return the commit sha."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial")
    return git(path, "rev-parse", "HEAD")
