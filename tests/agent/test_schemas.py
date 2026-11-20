# Filename: test_schemas.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest
from pydantic import ValidationError

from farejador.agent import schemas
from farejador.review.findings import Category, Finding, Severity


def _fn(tool: dict[str, object]) -> dict[str, object]:
    function: dict[str, object] = tool["function"]  # type: ignore[assignment]
    return function


def test_tools_have_the_names_and_required_arguments_of_the_contract() -> None:
    expected = {
        "read_file": ["path"],
        "grep": ["pattern"],
        "submit_review": ["summary", "findings"],
        "submit_verdicts": ["verdicts"],
    }
    tools = [schemas.READ_FILE, schemas.GREP, schemas.SUBMIT_REVIEW, schemas.SUBMIT_VERDICTS]
    for tool in tools:
        function = _fn(tool)
        assert tool["type"] == "function"
        assert function["parameters"]["required"] == expected[function["name"]]  # type: ignore[index]
    assert "required" not in _fn(schemas.LIST_DIR)["parameters"]  # type: ignore[operator]


def test_exploration_tools_are_exactly_the_three_read_only_tools() -> None:
    names = {_fn(tool)["name"] for tool in schemas.EXPLORATION_TOOLS}
    assert names == {"read_file", "grep", "list_dir"} == schemas.EXPLORATION_TOOL_NAMES


def test_finding_schema_enums_match_the_models() -> None:
    props = schemas.FINDING_SCHEMA["properties"]
    assert props["severity"]["enum"] == [item.value for item in Severity]
    assert props["category"]["enum"] == [item.value for item in Category]
    required = set(schemas.FINDING_SCHEMA["required"])
    # the model is asked for all three parts, although only the problem is mandatory to parse
    assert required == {
        "file",
        "line",
        "severity",
        "category",
        "problem",
        "rationale",
        "suggestion",
    }
    assert {name for name, field in Finding.model_fields.items() if field.is_required()} <= required
    assert "suggestion_diff" in schemas.FINDING_SCHEMA["properties"]
    assert "suggestion_diff" not in required


def test_verdicts_payload_ignores_extra_fields_and_defaults_the_note() -> None:
    payload = schemas.VerdictsPayload.model_validate(
        {"verdicts": [{"thread_id": "T1", "fixed": True, "confidence": 1}], "extra": 1}
    )
    assert payload.verdicts[0].note == ""


@pytest.mark.parametrize(
    "verdict",
    [{"thread_id": "", "fixed": True}, {"thread_id": "T", "fixed": "maybe"}, {"thread_id": "T"}],
)
def test_invalid_verdicts_are_rejected(verdict: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        schemas.VerdictsPayload.model_validate({"verdicts": [verdict]})
