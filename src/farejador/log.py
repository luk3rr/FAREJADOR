# Filename: log.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Structured JSON logging with secret redaction (FR-23, NFR-3)."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, TextIO

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[A-Za-z0-9+/=\s]*"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-or-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)x-access-token:[^@\s]+@"),
)

_MIN_SECRET_LENGTH = 4
_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "fields"}


class Redactor:
    """Masks known secret values and common credential patterns in text."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = sorted(
            {secret for secret in secrets if len(secret) >= _MIN_SECRET_LENGTH},
            key=len,
            reverse=True,
        )

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {str(key): self.redact_value(item) for key, item in value.items()}
        if isinstance(value, list | tuple | set):
            return [self.redact_value(item) for item in value]
        return value


class JsonFormatter(logging.Formatter):
    """Formats records as one JSON object per line, with redaction applied last."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(self._redactor.redact_value(payload), default=str, ensure_ascii=False)


def configure_logging(
    level: str = "INFO", secrets: Iterable[str] = (), stream: TextIO | None = None
) -> None:
    """Install a single JSON handler on the root logger; safe to call repeatedly."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter(Redactor(secrets)))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())


def log_run(
    logger: logging.Logger,
    *,
    repo: str,
    pr: int,
    sha: str,
    mode: str,
    steps: int,
    tokens: int,
    duration_s: float,
    findings: int,
    outcome: str,
) -> None:
    """Emit the per-review summary record required by FR-23."""
    logger.info(
        "review_run",
        extra={
            "repo": repo,
            "pr": pr,
            "sha": sha,
            "mode": mode,
            "steps": steps,
            "tokens": tokens,
            "duration_s": round(duration_s, 3),
            "findings": findings,
            "outcome": outcome,
        },
    )
