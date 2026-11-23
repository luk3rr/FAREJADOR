# Filename: test_workspace.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import sys
from pathlib import Path

import pytest
from tests.gitrepo import git, make_repo

from farejador.workspace import Workspace, WorkspaceError

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the workspace uses POSIX process groups"
)

TOKEN = "ghs_supersecrettokenvalue1234567890"


@pytest.fixture
def remote(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "remote"
    sha = make_repo(root, {"src/app.py": "print('hello')\n", "README.md": "# demo\n"})
    return root, sha


async def test_opens_the_requested_commit_and_exposes_tools(remote: tuple[Path, str]) -> None:
    root, sha = remote
    async with Workspace.open("o/r", sha, TOKEN, remote_url=str(root)) as workspace:
        assert (workspace.path / "src" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
        assert workspace.sha == sha
        assert "1: print('hello')" in workspace.tools.read_file("src/app.py")
        assert "src/app.py:1:print" in workspace.tools.grep("hello")
        assert git(workspace.path, "rev-parse", "HEAD") == sha


async def test_checks_out_an_older_commit_not_the_tip(remote: tuple[Path, str]) -> None:
    root, first = remote
    (root / "src" / "app.py").write_text("print('changed')\n")
    git(root, "commit", "-aqm", "second")
    async with Workspace.open("o/r", first, TOKEN, remote_url=str(root)) as workspace:
        assert (workspace.path / "src" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"


async def test_the_token_is_never_written_to_the_checkout(remote: tuple[Path, str]) -> None:
    root, sha = remote
    async with Workspace.open("o/r", sha, TOKEN, remote_url=str(root)) as workspace:
        config = (workspace.path / ".git" / "config").read_text(encoding="utf-8")
        assert TOKEN not in config
        assert "extraheader" not in config.lower()
        assert "x-access-token" not in config


async def test_directory_is_deleted_after_a_normal_exit(remote: tuple[Path, str]) -> None:
    root, sha = remote
    async with Workspace.open("o/r", sha, TOKEN, remote_url=str(root)) as workspace:
        path = workspace.path
        assert path.exists()
    assert not path.exists()


async def test_directory_is_deleted_when_the_body_raises(remote: tuple[Path, str]) -> None:
    root, sha = remote
    captured: list[Path] = []
    with pytest.raises(RuntimeError, match="boom"):
        async with Workspace.open("o/r", sha, TOKEN, remote_url=str(root)) as workspace:
            captured.append(workspace.path)
            raise RuntimeError("boom")
    assert not captured[0].exists()


async def test_unknown_commit_fails_cleanly_without_leaking_the_token(
    remote: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = remote
    created: list[Path] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
        created.append(Path(path))
        return str(path)

    monkeypatch.setattr("farejador.workspace.tempfile.mkdtemp", tracking_mkdtemp)
    with pytest.raises(WorkspaceError, match="git fetch failed") as info:
        async with Workspace.open("o/r", "0" * 40, TOKEN, remote_url=str(root)):
            pass
    assert TOKEN not in str(info.value)
    assert created
    assert not created[0].exists()


async def test_missing_remote_is_a_workspace_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="git fetch failed"):
        async with Workspace.open("o/r", "a" * 40, TOKEN, remote_url=str(tmp_path / "nowhere")):
            pass


async def test_missing_git_binary_is_reported(remote: tuple[Path, str]) -> None:
    root, sha = remote
    with pytest.raises(WorkspaceError, match="git is not available"):
        async with Workspace.open(
            "o/r", sha, TOKEN, remote_url=str(root), git="/nonexistent/git-binary"
        ):
            pass


async def test_a_slow_git_command_times_out(remote: tuple[Path, str]) -> None:
    root, sha = remote
    with pytest.raises(WorkspaceError, match="timed out"):
        async with Workspace.open("o/r", sha, TOKEN, remote_url=str(root), timeout_s=0.0):
            pass


async def test_cancellation_kills_git_and_still_removes_the_directory(
    remote: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import tempfile

    root, sha = remote
    slow_git = tmp_path / "slow-git"
    slow_git.write_text("#!/bin/sh\nsleep 30\n")
    slow_git.chmod(0o755)

    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
        created.append(Path(path))
        return str(path)

    monkeypatch.setattr("farejador.workspace.tempfile.mkdtemp", tracking_mkdtemp)

    async def run() -> None:
        async with Workspace.open("o/r", sha, TOKEN, remote_url=str(root), git=str(slow_git)):
            pass

    task = asyncio.create_task(run())
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert created
    assert not created[0].exists()
