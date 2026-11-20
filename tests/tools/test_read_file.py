# Filename: test_read_file.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import pytest
from tests.gitrepo import make_repo

from farejador.tools import MAX_READ_CHARS, MAX_READ_LINES, RepoTools, ToolError


@pytest.fixture
def tools(tmp_path: Path) -> RepoTools:
    root = tmp_path / "repo"
    long_lines = "".join(f"line {n}\n" for n in range(1, 1001))
    wide_lines = "".join(f"{'x' * 200}\n" for _ in range(300))
    make_repo(
        root,
        {
            "small.py": "a = 1\nb = 2\nc = 3\n",
            "long.txt": long_lines,
            "wide.txt": wide_lines,
            "empty.txt": "",
            "blob.bin": b"\x00\x01\x02binary",
            "latin.txt": b"caf\xe9\n",
        },
    )
    return RepoTools(root)


def test_small_file_is_returned_with_line_numbers(tools: RepoTools) -> None:
    out = tools.read_file("small.py")
    assert out.splitlines() == ["small.py (linhas 1-3 de 3)", "1: a = 1", "2: b = 2", "3: c = 3"]


def test_line_ranges_are_honoured(tools: RepoTools) -> None:
    out = tools.read_file("small.py", start_line=2, end_line=3)
    assert out.splitlines() == ["small.py (linhas 2-3 de 3)", "2: b = 2", "3: c = 3"]
    assert tools.read_file("small.py", start_line=3).splitlines()[1:] == ["3: c = 3"]


def test_end_line_past_the_end_is_clamped(tools: RepoTools) -> None:
    assert tools.read_file("small.py", end_line=99).splitlines()[0] == "small.py (linhas 1-3 de 3)"


def test_long_files_are_truncated_by_lines_and_say_how_to_continue(tools: RepoTools) -> None:
    out = tools.read_file("long.txt")
    lines = out.splitlines()
    assert lines[0] == f"long.txt (linhas 1-{MAX_READ_LINES} de 1000)"
    assert lines[1].startswith("[truncado: chame de novo com start_line=401")
    assert len(lines) == 2 + MAX_READ_LINES
    nxt = tools.read_file("long.txt", start_line=401)
    assert nxt.splitlines()[2] == "401: line 401"


def test_wide_files_are_truncated_by_characters(tools: RepoTools) -> None:
    out = tools.read_file("wide.txt")
    assert len(out) <= MAX_READ_CHARS + 300
    assert "[truncado: chame de novo com start_line=" in out


def test_empty_file_is_readable(tools: RepoTools) -> None:
    assert tools.read_file("empty.txt") == "empty.txt (linhas 1-0 de 0)"


def test_invalid_utf8_is_replaced_not_fatal(tools: RepoTools) -> None:
    assert "caf" in tools.read_file("latin.txt")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"path": "missing.py"}, "arquivo não encontrado"),
        ({"path": "."}, "não é um arquivo"),
        ({"path": "blob.bin"}, "arquivo binário"),
        ({"path": "small.py", "start_line": 0}, "pelo menos 1"),
        ({"path": "small.py", "start_line": 3, "end_line": 2}, "não pode ser menor"),
        ({"path": "small.py", "start_line": 9}, "além do fim"),
    ],
)
def test_errors_are_explained(tools: RepoTools, kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ToolError, match=message):
        tools.read_file(**kwargs)  # type: ignore[arg-type]


def test_files_over_the_size_limit_are_refused(tools: RepoTools, tmp_path: Path) -> None:
    big = tmp_path / "repo" / "big.txt"
    big.write_bytes(b"a\n" * 1_100_000)
    with pytest.raises(ToolError, match="grande demais"):
        tools.read_file("big.txt")


def test_unreadable_files_are_reported_as_text_not_exceptions(
    tools: RepoTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(self: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", deny)
    assert "não foi possível ler o arquivo" in tools.execute("read_file", {"path": "small.py"})


def test_secrets_in_file_content_are_masked_before_reaching_the_model(tmp_path: Path) -> None:
    root = tmp_path / "secrets-repo"
    token = "ghp_" + "a" * 36
    make_repo(
        root,
        {
            "app.py": f"TOKEN = '{token}'\nprint('ok')\n",
            "key.txt": (
                "-----BEGIN PRIVATE KEY-----\nMIIEabc123\n-----END PRIVATE KEY-----\nafter\n"
            ),
        },
    )
    tools = RepoTools(root)
    read = tools.execute("read_file", {"path": "app.py"})
    assert token not in read
    assert "«segredo-removido»" in read
    assert "2: print('ok')" in read
    assert token not in tools.execute("grep", {"pattern": "TOKEN"})
    key = tools.execute("read_file", {"path": "key.txt"})
    assert "MIIEabc123" not in key
    assert key.splitlines()[-1] == "4: after"
