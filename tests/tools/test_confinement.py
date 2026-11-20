# Filename: test_confinement.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import pytest
from tests.gitrepo import make_repo

from farejador.tools import RepoTools, ToolError


@pytest.fixture
def tools(tmp_path: Path) -> RepoTools:
    root = tmp_path / "repo"
    make_repo(root, {"src/app.py": "print('hi')\n", "README.md": "# readme\n"})
    (tmp_path / "secret.txt").write_text("outside secret")
    (root / "link_file").symlink_to(tmp_path / "secret.txt")
    (root / "link_dir").symlink_to(tmp_path)
    (root / "link_inside").symlink_to(root / "README.md")
    return RepoTools(root)


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "src/../../secret.txt",
        "../../../../etc/passwd",
        "link_file",
        "link_dir/secret.txt",
        "link_dir",
    ],
)
def test_paths_that_leave_the_repository_are_refused(tools: RepoTools, path: str) -> None:
    with pytest.raises(ToolError, match="fora do repositório"):
        tools.resolve(path)


@pytest.mark.parametrize("path", [".git", ".git/config", "src/.git/x", ".git/HEAD"])
def test_git_internals_are_not_available(tools: RepoTools, path: str) -> None:
    with pytest.raises(ToolError, match="indisponível"):
        tools.resolve(path)


def test_nul_bytes_are_rejected(tools: RepoTools) -> None:
    with pytest.raises(ToolError, match="caminho inválido"):
        tools.resolve("src/app.py\x00.txt")


@pytest.mark.parametrize("path", ["src/app.py", "./src/app.py", "/src/app.py", "src\\app.py"])
def test_normal_paths_resolve_inside_the_root(tools: RepoTools, path: str) -> None:
    assert tools.resolve(path).name == "app.py"


def test_empty_and_dot_paths_mean_the_root(tools: RepoTools) -> None:
    assert tools.resolve(None) == tools.resolve(".") == tools.resolve("")


def test_symlinks_that_stay_inside_are_allowed(tools: RepoTools) -> None:
    assert tools.resolve("link_inside").name == "README.md"


def test_execute_reports_confinement_errors_as_text(tools: RepoTools) -> None:
    out = tools.execute("read_file", {"path": "../secret.txt"})
    assert "fora do repositório" in out
    assert "outside secret" not in out


@pytest.mark.parametrize("path", [".env", "config/.env.production", "certs/server.pem", "id_rsa"])
def test_files_that_carry_credentials_are_not_available(tmp_path: Path, path: str) -> None:
    root = tmp_path / "repo2"
    make_repo(root, {"ok.txt": "fine\n", path: "SECRET=value\n"})
    tools = RepoTools(root)
    with pytest.raises(ToolError, match="indisponível"):
        tools.resolve(path)
    assert "indisponível" in tools.execute("read_file", {"path": path})
    assert tools.resolve("ok.txt").name == "ok.txt"


def test_example_env_files_stay_readable(tmp_path: Path) -> None:
    root = tmp_path / "repo3"
    make_repo(root, {".env.example": "TOKEN=changeme\n"})
    assert RepoTools(root).resolve(".env.example").name == ".env.example"
