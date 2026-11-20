# Filename: validator.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Anchor validation: inline comments only on added lines of the reviewed diff (FR-13)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from farejador.review.diff import DiffFile
from farejador.review.findings import Finding
from farejador.review.suggestion import verified_diff

DEFAULT_MAX_INLINE = 30


@dataclass(frozen=True, slots=True)
class Unanchored:
    finding: Finding
    reason: str


@dataclass(frozen=True, slots=True)
class AnchorResult:
    inline: list[Finding]
    unanchored: list[Unanchored]


def normalize_path(path: str) -> str:
    """Drop the prefixes models like to add (``./``, ``a/``, ``b/``) and surrounding spaces."""
    path = path.strip()
    for prefix in ("./", "a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def anchor(
    findings: Sequence[Finding],
    files: Sequence[DiffFile],
    *,
    ignored_paths: Collection[str] = (),
    max_inline: int = DEFAULT_MAX_INLINE,
) -> AnchorResult:
    """Split findings into inline comments and findings that must go to the summary."""
    reviewed = {diff_file.path: diff_file.added_lines for diff_file in files}
    by_path = {diff_file.path: diff_file for diff_file in files}
    ignored = set(ignored_paths)
    inline: list[Finding] = []
    unanchored: list[Unanchored] = []
    seen: set[tuple[str, int, str]] = set()

    for finding in findings:
        path = finding.file if finding.file in reviewed else normalize_path(finding.file)
        key = (path, finding.line, finding.problem)
        if key in seen:
            continue
        seen.add(key)

        added = reviewed.get(path)
        if added is None:
            reason = "file-ignored" if path in ignored else "file-not-in-diff"
            unanchored.append(Unanchored(finding, reason))
        elif finding.line not in added:
            unanchored.append(Unanchored(finding, "line-not-added"))
        elif len(inline) >= max_inline:
            unanchored.append(Unanchored(finding, "inline-limit"))
        else:
            checked = verified_diff(finding.suggestion_diff, by_path[path], finding.line)
            inline.append(finding.model_copy(update={"file": path, "suggestion_diff": checked}))
    return AnchorResult(inline, unanchored)
