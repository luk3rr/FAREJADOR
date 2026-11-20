# Filename: test_suggestion.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest

from farejador.review.diff import DiffFile, DiffLine, LineKind
from farejador.review.findings import Category, Finding, Severity
from farejador.review.suggestion import MAX_DIFF_LINES, verified_diff
from farejador.review.validator import anchor

CODE = {
    10: "def total(items):",
    11: "    soma = 0",
    12: "    for item in items:",
    13: "        soma += item.preco",
    14: "    return soma",
}


def _file(context: tuple[int, ...] = (10,)) -> DiffFile:
    lines = [
        DiffLine(LineKind.CONTEXT if n in context else LineKind.ADDED, text, n, n)
        for n, text in CODE.items()
    ]
    return DiffFile(path="a.py", old_path="a.py", lines=lines)


def test_a_correct_diff_is_accepted_and_normalised() -> None:
    raw = (
        "-    soma = 0\n-    for item in items:\n-        soma += item.preco\n"
        "+    soma = sum(i.preco for i in items)"
    )
    assert verified_diff(raw, _file(), 11) == raw


def test_the_git_style_marker_followed_by_a_space_is_tolerated() -> None:
    raw = "-     soma = 0\n+     soma = 1"
    assert verified_diff(raw, _file(), 11) == "-    soma = 0\n+    soma = 1"


def test_context_lines_must_exist_too() -> None:
    good = " def total(items):\n-    soma = 0\n+    soma = 1"
    bad = " def outra(items):\n-    soma = 0\n+    soma = 1"
    assert verified_diff(good, _file(), 11) == good
    assert verified_diff(bad, _file(), 11) is None


def test_lines_to_remove_that_do_not_exist_drop_the_diff() -> None:
    assert verified_diff("-    soma = 42\n+    soma = 1", _file(), 11) is None


def test_trailing_whitespace_does_not_matter() -> None:
    assert verified_diff("-    soma = 0   \n+    soma = 1", _file(), 11) is not None


def test_a_diff_with_only_additions_has_nothing_to_check() -> None:
    raw = "+    # nova linha\n+    pass"
    assert verified_diff(raw, _file(), 11) == raw


def test_the_block_must_be_near_the_anchor_line() -> None:
    raw = "-    return soma\n+    return 0"
    assert verified_diff(raw, _file(), 14) is not None
    assert verified_diff(raw, _file(), 40) is None


def test_removed_code_that_is_not_in_the_new_file_is_rejected() -> None:
    # a line that only existed before the change (a removed line of the diff) is not valid
    file = _file()
    file.lines.append(DiffLine(LineKind.REMOVED, "    antigo = 1", 20, None))
    assert verified_diff("-    antigo = 1\n+    novo = 1", file, 20) is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   \n  ",
        "sem marcador\n+ok",
        "  só contexto\n  outra",
        "\n".join(f"+linha {n}" for n in range(MAX_DIFF_LINES + 1)),
    ],
)
def test_malformed_or_too_long_diffs_are_dropped(raw: str | None) -> None:
    assert verified_diff(raw, _file(), 11) is None


def test_a_fence_written_by_the_model_is_removed() -> None:
    raw = "```diff\n-    soma = 0\n+    soma = 1\n```"
    assert verified_diff(raw, _file(), 11) == "-    soma = 0\n+    soma = 1"


def test_the_maximum_length_is_accepted() -> None:
    raw = "\n".join(f"+linha {n}" for n in range(MAX_DIFF_LINES))
    assert verified_diff(raw, _file(), 11) == raw


def _finding(diff: str | None) -> Finding:
    return Finding(
        file="a.py",
        line=11,
        severity=Severity.LOW,
        category=Category.COMPLEXITY,
        problem="p",
        rationale="r",
        suggestion="s",
        suggestion_diff=diff,
    )


def test_the_anchor_step_keeps_a_verified_diff_and_drops_an_invented_one() -> None:
    files = [_file(context=())]
    real = _finding("-    soma = 0\n+    soma = 1")
    invented = _finding("-    isto não existe\n+    soma = 1").model_copy(update={"line": 12})
    result = anchor([real, invented], files)
    by_line = {f.line: f for f in result.inline}
    assert by_line[11].suggestion_diff == "-    soma = 0\n+    soma = 1"
    assert by_line[12].suggestion_diff is None
    # the comment itself is still posted; only the unreliable code block is removed
    assert by_line[12].suggestion == "s"
