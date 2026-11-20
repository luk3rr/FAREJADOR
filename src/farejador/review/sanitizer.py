# Filename: sanitizer.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Makes untrusted model text safe to publish as GitHub Markdown (FR-14, R-3)."""

from __future__ import annotations

import re

_ZERO_WIDTH_SPACE = "​"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INVISIBLE = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_DANGEROUS_LINK = re.compile(r"\[([^\]]*)\]\(\s*(?:javascript|data|vbscript):[^)]*\)", re.I)
_HTML_START = re.compile(r"<(?=[A-Za-z/!?])")
_MENTION = re.compile(r"(?<![\w`@])@(?=[A-Za-z0-9])")
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_ELLIPSIS = "…"


def sanitize(text: str, *, max_length: int) -> str:
    """Neutralise mentions, raw HTML, images and risky links; cap length; balance fences."""
    text = _CONTROL.sub("", text)
    text = _INVISIBLE.sub("", text)
    text = _IMAGE.sub(lambda m: m.group(1) or "image", text)
    text = _DANGEROUS_LINK.sub(r"\1", text)

    out_lines: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
        elif in_fence:
            out_lines.append(line)
        else:
            out_lines.append(_neutralise_prose(line))
    text = "\n".join(out_lines)

    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + _ELLIPSIS
    return _balance_fences(text)


def _neutralise_prose(line: str) -> str:
    """Apply the prose-only rules to the parts of a line that are not inline code."""
    parts: list[str] = []
    cursor = 0
    for match in _INLINE_CODE.finditer(line):
        parts.append(_escape_prose(line[cursor : match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(_escape_prose(line[cursor:]))
    return "".join(parts)


def _escape_prose(segment: str) -> str:
    segment = _HTML_START.sub("&lt;", segment)
    return _MENTION.sub("@" + _ZERO_WIDTH_SPACE, segment)


def _balance_fences(text: str) -> str:
    fences = sum(1 for line in text.split("\n") if _FENCE.match(line))
    if fences % 2 == 1:
        text = text.rstrip("\n") + "\n```"
    return text
