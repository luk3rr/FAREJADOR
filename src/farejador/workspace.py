# Filename: workspace.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Shallow checkout of a pull request head in a temporary directory (FR-8, ADR-4)."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import signal
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from farejador.tools import RepoTools, git_env

CLONE_TIMEOUT_S = 180


class WorkspaceError(Exception):
    """The repository could not be checked out."""


@dataclass(frozen=True, slots=True)
class Workspace:
    """A checked-out commit and the read-only tools bound to it."""

    path: Path
    sha: str
    tools: RepoTools

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        repo: str,
        sha: str,
        token: str,
        *,
        remote_url: str | None = None,
        git: str = "git",
        timeout_s: float = CLONE_TIMEOUT_S,
    ) -> AsyncIterator[Workspace]:
        """Fetch exactly ``sha`` (depth 1) and always delete the directory afterwards.

        The installation token is passed through the environment as an HTTP header, so it is
        never part of a command line, a remote URL or ``.git/config``.
        """
        url = remote_url or f"https://github.com/{repo}.git"
        directory = Path(tempfile.mkdtemp(prefix="farejador-"))
        try:
            env = git_env() | {
                "GIT_ALLOW_PROTOCOL": "https:file",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": "Authorization: Basic "
                + base64.b64encode(f"x-access-token:{token}".encode()).decode(),
            }
            for step in (
                ["init", "-q"],
                ["remote", "add", "origin", url],
                ["fetch", "-q", "--depth", "1", "--no-tags", "origin", sha],
                ["checkout", "-q", "--detach", "FETCH_HEAD"],
            ):
                await _run(git, step, directory, env, timeout_s, token)
            yield cls(directory, sha, RepoTools(directory, git=git))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


async def _kill_group(process: asyncio.subprocess.Process) -> None:
    """Kill git and the helpers it spawned (such as ``git-remote-https``) together.

    Children that keep the pipes open would otherwise block ``process.wait()``.
    """
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


async def _run(
    git: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_s: float,
    token: str,
) -> None:
    resolved = shutil.which(git) or git
    try:
        process = await asyncio.create_subprocess_exec(
            resolved,
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise WorkspaceError("git is not available") from exc
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        await _kill_group(process)
        raise WorkspaceError(f"git {args[0]} timed out") from None
    except asyncio.CancelledError:
        await _kill_group(process)
        raise
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").replace(token, "[REDACTED]").strip()
        first_line = detail.splitlines()[0] if detail else "unknown error"
        raise WorkspaceError(f"git {args[0]} failed: {first_line}")
