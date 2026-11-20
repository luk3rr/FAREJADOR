# Filename: test_validator.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import random

from farejador.review.diff import DiffFile, DiffLine, LineKind
from farejador.review.findings import Category, Finding, Severity
from farejador.review.validator import anchor, normalize_path


def _file(path: str, added: list[int], context: list[int] | None = None) -> DiffFile:
    lines = [DiffLine(LineKind.ADDED, "x", None, n) for n in added]
    lines += [DiffLine(LineKind.CONTEXT, "c", n, n) for n in (context or [])]
    return DiffFile(path=path, old_path=path, lines=lines)


def _finding(file: str, line: int, message: str = "smell") -> Finding:
    return Finding(
        file=file,
        line=line,
        severity=Severity.LOW,
        category=Category.OTHER,
        problem=message,
    )


def test_findings_on_added_lines_are_inline() -> None:
    result = anchor([_finding("a.py", 3)], [_file("a.py", [2, 3])])
    assert [(f.file, f.line) for f in result.inline] == [("a.py", 3)]
    assert result.unanchored == []


def test_context_lines_are_not_valid_anchors() -> None:
    result = anchor([_finding("a.py", 5)], [_file("a.py", [2], context=[5])])
    assert result.inline == []
    assert [(u.reason, u.finding.line) for u in result.unanchored] == [("line-not-added", 5)]


def test_unknown_files_are_reported_with_the_right_reason() -> None:
    result = anchor(
        [_finding("missing.py", 1), _finding("lock.json", 1)],
        [_file("a.py", [1])],
        ignored_paths=["lock.json"],
    )
    assert [(u.finding.file, u.reason) for u in result.unanchored] == [
        ("missing.py", "file-not-in-diff"),
        ("lock.json", "file-ignored"),
    ]


def test_path_prefixes_added_by_models_are_normalised() -> None:
    assert normalize_path("./src/a.py") == "src/a.py"
    assert normalize_path("b/src/a.py") == "src/a.py"
    assert normalize_path(" a/src/a.py ") == "src/a.py"
    result = anchor([_finding("b/src/a.py", 4)], [_file("src/a.py", [4])])
    assert result.inline[0].file == "src/a.py"


def test_a_path_that_really_starts_with_a_slash_prefix_dir_is_kept() -> None:
    result = anchor([_finding("a/x.py", 1)], [_file("a/x.py", [1])])
    assert [f.file for f in result.inline] == ["a/x.py"]


def test_identical_findings_are_deduplicated_but_different_ones_are_kept() -> None:
    findings = [
        _finding("a.py", 1, "same"),
        _finding("a.py", 1, "same"),
        _finding("a.py", 1, "other"),
    ]
    result = anchor(findings, [_file("a.py", [1])])
    assert [f.problem for f in result.inline] == ["same", "other"]


def test_inline_limit_moves_the_excess_to_the_summary() -> None:
    findings = [_finding("a.py", n) for n in range(1, 6)]
    result = anchor(findings, [_file("a.py", [1, 2, 3, 4, 5])], max_inline=3)
    assert [f.line for f in result.inline] == [1, 2, 3]
    assert [(u.finding.line, u.reason) for u in result.unanchored] == [
        (4, "inline-limit"),
        (5, "inline-limit"),
    ]


def test_every_inline_comment_is_an_added_line_for_random_inputs() -> None:
    rng = random.Random(1234)
    for _ in range(200):
        files = [
            _file(
                f"f{i}.py",
                rng.sample(range(1, 40), rng.randint(0, 8)),
                rng.sample(range(1, 40), rng.randint(0, 8)),
            )
            for i in range(rng.randint(1, 4))
        ]
        findings = [
            _finding(
                rng.choice([f.path for f in files] + ["ghost.py", "b/f0.py"]),
                rng.randint(1, 45),
                f"m{rng.randint(0, 3)}",
            )
            for _ in range(rng.randint(0, 25))
        ]
        result = anchor(findings, files, max_inline=10)
        added = {f.path: f.added_lines for f in files}
        assert len(result.inline) <= 10
        for finding in result.inline:
            assert finding.line in added[finding.file]
        total_unique = len({(normalize_path(f.file), f.line, f.problem) for f in findings})
        assert len(result.inline) + len(result.unanchored) == total_unique
