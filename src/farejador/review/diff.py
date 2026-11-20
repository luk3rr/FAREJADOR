# Filename: diff.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Unified diff parsing with new-file line numbers, and numbered rendering (FR-6)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

_DIFF_HEADER = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$")
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_HUNK_HEADER = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")
_FILE_CLOSE_TAG = "</file>"


class LineKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CONTEXT = "context"
    HUNK = "hunk"


class FileStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: LineKind
    text: str
    old_line: int | None = None
    new_line: int | None = None


@dataclass(slots=True)
class DiffFile:
    path: str
    old_path: str
    status: FileStatus = FileStatus.MODIFIED
    is_binary: bool = False
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def added_lines(self) -> frozenset[int]:
        """New-file line numbers of the added lines (the only valid inline anchors)."""
        return frozenset(
            line.new_line
            for line in self.lines
            if line.kind is LineKind.ADDED and line.new_line is not None
        )


def parse_diff(text: str) -> list[DiffFile]:
    """Parse a unified diff; unreadable sections are skipped, empty input gives ``[]``."""
    files: list[DiffFile] = []
    section: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("diff --git ") and section:
            _append(files, _parse_section(section))
            section = []
        if raw.startswith("diff --git ") or section:
            section.append(raw)
    if section:
        _append(files, _parse_section(section))
    return files


def _append(files: list[DiffFile], parsed: DiffFile | None) -> None:
    if parsed is not None:
        files.append(parsed)


def _unquote(path: str) -> str:
    path = path.strip()
    if len(path) >= 2 and path[0] == path[-1] == '"':
        path = path[1:-1]
    return path


def _strip_prefix(path: str, prefix: str) -> str:
    return path[len(prefix) :] if path.startswith(prefix) else path


def _header_paths(line: str) -> tuple[str, str] | None:
    """Extract the old and new paths from a ``diff --git`` line, quoted or not."""
    if line.startswith('diff --git "'):
        quoted = _QUOTED.findall(line)
        if len(quoted) != 2:
            return None
        return _strip_prefix(quoted[0], "a/"), _strip_prefix(quoted[1], "b/")
    header = _DIFF_HEADER.match(line)
    if header is None:
        return None
    return header.group("old"), header.group("new")


def _parse_section(lines: list[str]) -> DiffFile | None:
    paths = _header_paths(lines[0])
    if paths is None:
        return None
    parsed = DiffFile(path=paths[1], old_path=paths[0])

    index = 1
    while index < len(lines) and not lines[index].startswith("@@"):
        line = lines[index]
        if line.startswith("new file mode"):
            parsed.status = FileStatus.ADDED
        elif line.startswith("deleted file mode"):
            parsed.status = FileStatus.DELETED
        elif line.startswith("rename from "):
            parsed.status = FileStatus.RENAMED
            parsed.old_path = _unquote(line[len("rename from ") :])
        elif line.startswith("rename to "):
            parsed.status = FileStatus.RENAMED
            parsed.path = _unquote(line[len("rename to ") :])
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            parsed.is_binary = True
        elif line.startswith("--- ") and line != "--- /dev/null":
            parsed.old_path = _strip_prefix(_unquote(line[4:]), "a/")
        elif line.startswith("+++ ") and line != "+++ /dev/null":
            parsed.path = _strip_prefix(_unquote(line[4:]), "b/")
        index += 1

    if parsed.status is FileStatus.DELETED:
        parsed.path = parsed.old_path
    _parse_hunks(parsed, lines[index:])
    return parsed


def _parse_hunks(parsed: DiffFile, lines: list[str]) -> None:
    old_line = new_line = 0
    for raw in lines:
        hunk = _HUNK_HEADER.match(raw)
        if hunk is not None:
            old_line, new_line = int(hunk.group("old")), int(hunk.group("new"))
            parsed.lines.append(DiffLine(LineKind.HUNK, raw))
        elif raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        elif raw.startswith("+"):
            parsed.lines.append(DiffLine(LineKind.ADDED, raw[1:], None, new_line))
            new_line += 1
        elif raw.startswith("-"):
            parsed.lines.append(DiffLine(LineKind.REMOVED, raw[1:], old_line, None))
            old_line += 1
        else:
            text = raw[1:] if raw.startswith(" ") else raw
            parsed.lines.append(DiffLine(LineKind.CONTEXT, text, old_line, new_line))
            old_line += 1
            new_line += 1


def render_numbered(
    files: Iterable[DiffFile], mask_line: Callable[[str], str] | None = None
) -> str:
    """Render files for the prompt with new-file line numbers (FR-13, R-1).

    ``mask_line`` is applied to every code line; it must keep one output line per input line.
    The closing tag of the file delimiter is neutralised inside code so the diff cannot
    break out of its data block (R-3).
    """
    rendered: list[str] = []
    for diff_file in files:
        rendered.append(f'<file path="{diff_file.path.replace(chr(34), "%22")}">')
        for line in diff_file.lines:
            if line.kind is LineKind.HUNK:
                rendered.append(line.text)
                continue
            text = mask_line(line.text) if mask_line else line.text
            text = text.replace(_FILE_CLOSE_TAG, "<\\/file>")
            if line.kind is LineKind.ADDED:
                rendered.append(f"{line.new_line:>5} | + {text}")
            elif line.kind is LineKind.CONTEXT:
                rendered.append(f"{line.new_line:>5} |   {text}")
            else:
                rendered.append(f"{'':>5} | - {text}")
        rendered.append(_FILE_CLOSE_TAG)
    return "\n".join(rendered)
