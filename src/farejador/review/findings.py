# Filename: findings.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Finding and review result models (design.md, contract C-D)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_PROBLEM = 500
MAX_RATIONALE = 1500
MAX_SUGGESTION = 1000
MAX_DIFF = 1500
MAX_SUMMARY = 2000
MAX_FINDINGS = 50


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Category(StrEnum):
    MAINTAINABILITY = "maintainability"
    READABILITY = "readability"
    COMPLEXITY = "complexity"
    DUPLICATION = "duplication"
    NAMING = "naming"
    ERROR_HANDLING = "error-handling"
    TESTING = "testing"
    DESIGN = "design"
    PERFORMANCE = "performance"
    SECURITY = "security"
    OTHER = "other"


class Finding(BaseModel):
    """One issue reported by the model; extra fields sent by the model are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    severity: Severity
    category: Category
    problem: str = Field(min_length=1, max_length=MAX_PROBLEM)
    rationale: str | None = Field(default=None, max_length=MAX_RATIONALE)
    suggestion: str | None = Field(default=None, max_length=MAX_SUGGESTION)
    # Whitespace is part of a diff: the first line may be context, which starts with a space.
    suggestion_diff: Annotated[
        str | None, StringConstraints(strip_whitespace=False, max_length=MAX_DIFF)
    ] = None


class ReviewResult(BaseModel):
    """The arguments of the final ``submit_review`` tool call."""

    model_config = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)

    summary: str = Field(max_length=MAX_SUMMARY)
    findings: list[Finding] = Field(default_factory=list, max_length=MAX_FINDINGS)
