# Filename: test_findings.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest
from pydantic import ValidationError

from farejador.review.findings import (
    MAX_DIFF,
    MAX_PROBLEM,
    MAX_RATIONALE,
    MAX_SUGGESTION,
    Category,
    Finding,
    ReviewResult,
    Severity,
)


def _finding(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "file": "a.py",
        "line": 3,
        "severity": "medium",
        "category": "naming",
        "problem": "Renomeie esta variável.",
        "rationale": "O nome atual não revela a intenção.",
        "suggestion": "Use um nome descritivo.",
    }
    return base | overrides


def test_valid_finding_parses_enums_and_strips_whitespace() -> None:
    finding = Finding.model_validate(_finding(problem="  Renomeie.  "))
    assert finding.severity is Severity.MEDIUM
    assert finding.category is Category.NAMING
    assert finding.problem == "Renomeie."
    assert finding.rationale == "O nome atual não revela a intenção."
    assert finding.suggestion_diff is None


def test_only_the_problem_is_mandatory_for_the_model_output_to_be_usable() -> None:
    finding = Finding.model_validate(
        {"file": "a.py", "line": 1, "severity": "low", "category": "other", "problem": "x"}
    )
    assert (finding.rationale, finding.suggestion, finding.suggestion_diff) == (None, None, None)


def test_extra_fields_from_the_model_are_ignored() -> None:
    finding = Finding.model_validate(_finding(confidence=0.9, id="x"))
    assert not hasattr(finding, "confidence")


@pytest.mark.parametrize(
    "overrides",
    [
        {"line": 0},
        {"file": ""},
        {"problem": ""},
        {"problem": "x" * (MAX_PROBLEM + 1)},
        {"rationale": "x" * (MAX_RATIONALE + 1)},
        {"suggestion": "x" * (MAX_SUGGESTION + 1)},
        {"suggestion_diff": "x" * (MAX_DIFF + 1)},
        {"severity": "critical"},
        {"category": "style"},
    ],
)
def test_invalid_findings_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(_finding(**overrides))


def test_fields_at_their_limits_are_accepted() -> None:
    finding = Finding.model_validate(
        _finding(
            problem="p" * MAX_PROBLEM,
            rationale="r" * MAX_RATIONALE,
            suggestion="s" * MAX_SUGGESTION,
            suggestion_diff="d" * MAX_DIFF,
        )
    )
    assert len(finding.problem) == MAX_PROBLEM


def test_review_result_limits() -> None:
    findings = [_finding(line=i + 1) for i in range(50)]
    assert len(ReviewResult.model_validate({"summary": "ok", "findings": findings}).findings) == 50
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(
            {"summary": "ok", "findings": [_finding(line=i + 1) for i in range(51)]}
        )
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({"summary": "x" * 2001, "findings": []})


def test_review_result_defaults_to_no_findings() -> None:
    assert ReviewResult.model_validate({"summary": "clean"}).findings == []
