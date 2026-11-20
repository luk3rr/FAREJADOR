# Filename: filters.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Ignore list and secret masking applied before anything reaches the model (FR-7, FR-19)."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from farejador.review.diff import DiffFile, FileStatus

# Not code-like on purpose: a placeholder such as "[MASKED]" read as a Python list and made the
# model invent a TypeError. The guillemets also survive the markdown sanitizer.
MASKED = "«segredo-removido»"

# -- ignore list -----------------------------------------------------------------------------

_SECRET_FILES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "id_rsa*")
_SECRET_ALLOWED = frozenset({".env.example", ".env.sample", ".env.template"})
_LOCKFILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
        "composer.lock",
    }
)
_GENERATED = ("*.min.js", "*.min.css", "*.map", "*_pb2.py", "*.pb.go", "dist/**", "build/**")
_VENDORED = ("node_modules/**", "vendor/**", "__pycache__/**")
_BINARY_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".pdf", ".zip", ".gz", ".tar",
        ".tgz", ".jar", ".war", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4",
        ".mov", ".class", ".so", ".dll", ".exe", ".bin",
    }
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class IgnoreDecision:
    ignored: bool
    reason: str = ""


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path.startswith(prefix + "/") or f"/{prefix}/" in f"/{path}"
    name = PurePosixPath(path).name
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern)


def is_secret_path(path: str) -> bool:
    """Whether a path names a file that normally carries credentials (``.env``, keys, ...)."""
    name = PurePosixPath(path).name
    if name in _SECRET_ALLOWED:
        return False
    return any(_matches(path, pattern) for pattern in _SECRET_FILES)


def check_ignored(diff_file: DiffFile, extra_globs: Iterable[str] = ()) -> IgnoreDecision:
    """Decide whether a changed file is skipped, and why (the reason goes to the summary)."""
    path = diff_file.path
    name = PurePosixPath(path).name
    if diff_file.status is FileStatus.DELETED:
        return IgnoreDecision(True, "deleted")
    if diff_file.is_binary or PurePosixPath(name).suffix.lower() in _BINARY_EXTENSIONS:
        return IgnoreDecision(True, "binary")
    if is_secret_path(path):
        return IgnoreDecision(True, "secret-bearing")
    if name in _LOCKFILES:
        return IgnoreDecision(True, "lockfile")
    if any(_matches(path, p) for p in _GENERATED):
        return IgnoreDecision(True, "generated")
    if any(_matches(path, p) for p in _VENDORED):
        return IgnoreDecision(True, "vendored")
    if any(_matches(path, p) for p in extra_globs):
        return IgnoreDecision(True, "custom")
    return IgnoreDecision(False)


# -- secret masking --------------------------------------------------------------------------

_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-or-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
)
_URL_CREDENTIALS = re.compile(r"(://[^/\s:@]+:)[^@\s]+(@)")
_ASSIGNMENT = re.compile(
    r"(?i)(\b[A-Za-z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)"
    r"[A-Za-z0-9_]*[\"']?\s*[:=]\s*)"
    r"(?:([\"'])[^\"'\n]{6,}\2|[A-Za-z0-9+/=_.-]{12,}(?![A-Za-z0-9+/=_.(-]))"
)


class Masker:
    """Masks secrets line by line, never changing the number of lines (FR-19).

    A private key block spans several lines, so the masker remembers whether it is inside one.
    """

    def __init__(self) -> None:
        self._in_private_key = False

    def line(self, text: str) -> str:
        if self._in_private_key:
            if _PEM_END.search(text):
                self._in_private_key = False
            return MASKED
        if _PEM_BEGIN.search(text):
            self._in_private_key = _PEM_END.search(text) is None
            return MASKED
        for pattern in _TOKEN_PATTERNS:
            text = pattern.sub(MASKED, text)
        text = _URL_CREDENTIALS.sub(rf"\1{MASKED}\2", text)
        return _ASSIGNMENT.sub(rf"\1{MASKED}", text)


def mask(text: str) -> str:
    """Mask secrets in multi-line text, keeping the line count."""
    masker = Masker()
    return "\n".join(masker.line(line) for line in text.split("\n"))
