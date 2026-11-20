# Filename: test_list_dir.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json
from pathlib import Path

import pytest
from tests.gitrepo import make_repo

from farejador.tools import MAX_DIR_ENTRIES, RepoTools, ToolError


@pytest.fixture
def tools(tmp_path: Path) -> RepoTools:
    root = tmp_path / "repo"
    make_repo(
        root,
        {
            "src/app.py": "x\n",
            "src/util.py": "yy\n",
            "tests/test_app.py": "z\n",
            "README.md": "# hi\n",
            "Makefile": "all:\n",
            "wide/placeholder": "",
        },
    )
    (root / "empty").mkdir()
    for number in range(MAX_DIR_ENTRIES + 5):
        (root / "wide" / f"f{number:03}.txt").write_text("")
    return RepoTools(root)


def test_root_listing_puts_directories_first_and_hides_git(tools: RepoTools) -> None:
    lines = tools.list_dir().splitlines()
    assert lines[:4] == ["empty/", "src/", "tests/", "wide/"]
    assert "Makefile (5 bytes)" in lines
    assert "README.md (5 bytes)" in lines
    assert ".git/" not in lines


def test_subdirectory_listing(tools: RepoTools) -> None:
    assert tools.list_dir("src").splitlines() == ["app.py (2 bytes)", "util.py (3 bytes)"]


def test_empty_directory(tools: RepoTools) -> None:
    assert tools.list_dir("empty") == "(diretório vazio)"


def test_large_directories_are_truncated(tools: RepoTools) -> None:
    lines = tools.list_dir("wide").splitlines()
    assert len(lines) == MAX_DIR_ENTRIES + 1
    assert lines[-1] == "[6 entradas a mais omitidas]"


def test_errors(tools: RepoTools) -> None:
    with pytest.raises(ToolError, match="diretório não encontrado"):
        tools.list_dir("nope")
    with pytest.raises(ToolError, match="não é um diretório"):
        tools.list_dir("README.md")


def test_execute_dispatches_and_validates_arguments(tools: RepoTools) -> None:
    assert tools.execute("list_dir", {"path": "src"}).startswith("app.py")
    assert "src/app.py:1:x" in tools.execute("grep", {"pattern": "x", "path": "src"})
    assert tools.execute("read_file", {"path": "src/app.py"}).splitlines()[1] == "1: x"
    assert json.loads(tools.execute("write_file", {})) == {
        "error": "ferramenta desconhecida: write_file"
    }
    assert "argumento ausente: path" in tools.execute("read_file", {})
    assert "deve ser texto" in tools.execute("list_dir", {"path": 3})
    assert "deve ser um inteiro" in tools.execute("read_file", {"path": "a", "start_line": "1"})
    assert "deve ser um inteiro" in tools.execute("read_file", {"path": "a", "start_line": True})
    assert "arquivo não encontrado" in tools.execute("read_file", {"path": "zzz"})
