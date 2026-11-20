# Filename: test_grep.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import subprocess
from pathlib import Path

import pytest
from tests.gitrepo import make_repo

from farejador.tools import MAX_GREP_LINE, MAX_GREP_RESULTS, RepoTools, ToolError


@pytest.fixture
def tools(tmp_path: Path) -> RepoTools:
    root = tmp_path / "repo"
    make_repo(
        root,
        {
            "src/a.py": "def hello():\n    return 'hello'\n",
            "src/b.py": "import os\nhello = 1\n",
            "docs/readme.md": "say hello\n",
            "flags.txt": "-v verbose\n",
            "many.txt": "".join(f"match {n}\n" for n in range(150)),
            "wide.txt": "needle " + "x" * 1000 + "\n",
            "blob.bin": b"\x00hello\x00",
        },
    )
    return RepoTools(root)


def test_matches_are_reported_with_path_and_line(tools: RepoTools) -> None:
    out = tools.grep("def hello").splitlines()
    assert out == ["src/a.py:1:def hello():"]


def test_search_can_be_scoped_to_a_path(tools: RepoTools) -> None:
    out = tools.grep("hello", path="src").splitlines()
    assert sorted(out) == [
        "src/a.py:1:def hello():",
        "src/a.py:2:    return 'hello'",
        "src/b.py:2:hello = 1",
    ]


def test_extended_regex_and_binaries_are_handled(tools: RepoTools) -> None:
    out = tools.grep("^(def|import) ")
    assert "src/a.py:1:def hello():" in out
    assert "src/b.py:1:import os" in out
    assert "blob.bin" not in tools.grep("hello")


def test_no_matches_is_stated(tools: RepoTools) -> None:
    assert tools.grep("does-not-exist-anywhere") == "nenhuma ocorrência"


def test_patterns_starting_with_a_dash_are_not_treated_as_options(tools: RepoTools) -> None:
    assert tools.grep("-v verbose") == "flags.txt:1:-v verbose"


def test_results_are_capped_and_the_rest_is_counted(tools: RepoTools) -> None:
    out = tools.grep("match", path="many.txt").splitlines()
    assert len(out) == MAX_GREP_RESULTS + 1
    assert out[-1] == "[50 resultados a mais omitidos; restrinja a busca]"
    assert len(tools.grep("match", path="many.txt", max_results=5).splitlines()) == 6


def test_long_lines_are_clipped(tools: RepoTools) -> None:
    (line,) = tools.grep("needle").splitlines()
    assert len(line) == MAX_GREP_LINE
    assert line.endswith("…")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pattern": ""}, "não pode ser vazio"),
        ({"pattern": "x" * 201}, "mais de"),
        ({"pattern": "(unclosed"}, "padrão de busca inválido"),
        ({"pattern": "a", "path": "../x"}, "fora do repositório"),
        ({"pattern": "a", "path": ".git"}, "indisponível"),
    ],
)
def test_bad_requests_are_explained(
    tools: RepoTools, kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ToolError, match=message):
        tools.grep(**kwargs)  # type: ignore[arg-type]


def test_a_slow_search_times_out(tools: RepoTools, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="git grep", timeout=10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ToolError, match="excedeu o tempo"):
        tools.grep("anything")
