# Filename: sanitize.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Mask and truncate every free text before it reaches the trace database (FR-6, FR-14).

Masking comes first so the masking marker is never cut in half, and the size limits come second.
One ``Sanitizer`` serves one run: it also enforces the byte ceiling of the whole run (FN-5, FN-6).
"""

from __future__ import annotations

from dataclasses import dataclass

from farejador.review.filters import mask

TRUNCATION_NOTE = "[…cortado: {original} caracteres no original]"


@dataclass(frozen=True, slots=True)
class Clean:
    """A sanitized text and what was lost on the way."""

    text: str
    truncated: bool
    original_chars: int


class Sanitizer:
    """Per-run budget of characters per item and bytes per run."""

    def __init__(self, max_item_chars: int, max_run_bytes: int) -> None:
        self._max_item_chars = max_item_chars
        self._max_run_bytes = max_run_bytes
        self._used_bytes = 0
        self.truncated = False

    @property
    def exhausted(self) -> bool:
        """True once the run ceiling was reached: later items keep only their metadata."""
        return self._used_bytes >= self._max_run_bytes

    def clean(self, value: str | None) -> Clean:
        """Mask secrets, then cut to the item limit and to what is left of the run budget."""
        if not value:
            return Clean("", False, 0)
        original = len(value)
        text = mask(value)
        truncated = False
        if len(text) > self._max_item_chars:
            text = text[: self._max_item_chars] + TRUNCATION_NOTE.format(original=original)
            truncated = True
        remaining = self._max_run_bytes - self._used_bytes
        encoded = text.encode("utf-8")
        if len(encoded) > remaining:
            text = encoded[: max(remaining, 0)].decode("utf-8", errors="ignore")
            if text:
                text += TRUNCATION_NOTE.format(original=original)
            truncated = True
            self._used_bytes = self._max_run_bytes
        else:
            self._used_bytes += len(encoded)
        if truncated:
            self.truncated = True
        return Clean(text, truncated, original)
