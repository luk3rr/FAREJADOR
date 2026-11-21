# Filename: suggestion.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Validation of the optional ``-``/``+`` suggestion shown in a comment.

The model writes the lines to remove (``-``), to add (``+``) and optional context (space). A
suggestion that "removes" code that does not exist would mislead the reader, so the lines that
must already exist are checked against the file as it is in the pull request; when they do not
match, the diff is dropped and only the text of the suggestion is shown.
"""

from __future__ import annotations

from farejador.review.diff import DiffFile, LineKind

MAX_DIFF_LINES = 20
SEARCH_WINDOW = 10
_MARKERS = ("-", "+", " ")


def _parse(raw: str, *, strip_space: bool) -> list[tuple[str, str]] | None:
    lines = [line for line in raw.strip("\n").splitlines() if not line.lstrip().startswith("```")]
    if not lines or len(lines) > MAX_DIFF_LINES:
        return None
    parsed: list[tuple[str, str]] = []
    for line in lines:
        if line == "":
            parsed.append((" ", ""))
            continue
        marker, text = line[0], line[1:]
        if marker not in _MARKERS:
            # a context line written without its leading space; whether it is real code is
            # checked against the file, so a made-up line is still rejected
            marker, text = " ", line
        if strip_space and marker != " " and text.startswith(" "):
            text = text[1:]
        parsed.append((marker, text))
    if not any(marker in "+-" for marker, _ in parsed):
        return None
    return parsed


def _exists(parsed: list[tuple[str, str]], diff_file: DiffFile, anchor_line: int) -> bool:
    """Whether the lines that must already exist appear together near the anchor line."""
    existing = [text for marker, text in parsed if marker in "- "]
    if not existing:
        return True  # only additions: nothing to check
    new_side = {
        line.new_line: line.text.rstrip()
        for line in diff_file.lines
        if line.kind in (LineKind.ADDED, LineKind.CONTEXT) and line.new_line is not None
    }
    for start in range(anchor_line - SEARCH_WINDOW, anchor_line + SEARCH_WINDOW + 1):
        if all(
            new_side.get(start + offset) == text.rstrip() for offset, text in enumerate(existing)
        ):
            return True
    return False


def verified_diff(raw: str | None, diff_file: DiffFile, anchor_line: int) -> str | None:
    """The normalised diff text, or ``None`` when it is malformed, too long or not real code.

    Models often write ``- code`` with a space after the marker. Both spellings are accepted:
    the exact one first, then the one with a single space removed after ``-`` and ``+``.
    """
    if not raw or not raw.strip():
        return None
    for strip_space in (False, True):
        parsed = _parse(raw, strip_space=strip_space)
        if parsed is not None and _exists(parsed, diff_file, anchor_line):
            return "\n".join(f"{marker}{text}" for marker, text in parsed)
    return None
