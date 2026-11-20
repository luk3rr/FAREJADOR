# Filename: models.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Shared domain models, starting with the Trigger contract (design.md, C-A)."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TriggerKind(StrEnum):
    """What a trigger asks the system to do."""

    FIRST_REVIEW = "first_review"
    COMMAND = "command"


class TriggerSource(StrEnum):
    """Which event source produced a trigger."""

    WEBHOOK = "webhook"
    POLLING = "polling"


class Trigger(BaseModel):
    """An event that may cause work; ``key`` is the idempotency key (FR-4)."""

    model_config = ConfigDict(frozen=True)

    key: str
    kind: TriggerKind
    repo: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    installation_id: int
    pr_number: int = Field(ge=1)
    head_sha: str | None = None
    comment_id: int | None = None
    sender_login: str
    source: TriggerSource

    @model_validator(mode="after")
    def _check_key_matches_kind(self) -> Self:
        if self.kind is TriggerKind.FIRST_REVIEW:
            if self.comment_id is not None:
                raise ValueError("first_review triggers must not carry a comment_id")
            expected = f"first:{self.repo}#{self.pr_number}"
        else:
            if self.comment_id is None:
                raise ValueError("command triggers require a comment_id")
            expected = f"cmd:{self.comment_id}"
        if self.key != expected:
            raise ValueError(f"key must be {expected!r} for kind {self.kind.value}")
        return self

    @classmethod
    def first_review(
        cls,
        *,
        repo: str,
        installation_id: int,
        pr_number: int,
        sender_login: str,
        source: TriggerSource,
        head_sha: str | None = None,
    ) -> Self:
        """Build the automatic first-review trigger of a pull request."""
        return cls(
            key=f"first:{repo}#{pr_number}",
            kind=TriggerKind.FIRST_REVIEW,
            repo=repo,
            installation_id=installation_id,
            pr_number=pr_number,
            head_sha=head_sha,
            sender_login=sender_login,
            source=source,
        )

    @classmethod
    def command(
        cls,
        *,
        repo: str,
        installation_id: int,
        pr_number: int,
        comment_id: int,
        sender_login: str,
        source: TriggerSource,
    ) -> Self:
        """Build the trigger of a command comment, keyed by the comment id."""
        return cls(
            key=f"cmd:{comment_id}",
            kind=TriggerKind.COMMAND,
            repo=repo,
            installation_id=installation_id,
            pr_number=pr_number,
            comment_id=comment_id,
            sender_login=sender_login,
            source=source,
        )
