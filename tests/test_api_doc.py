# Filename: test_api_doc.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""docs/api.md says what the API really does (FR-18)."""

import re
from pathlib import Path

from tests.api_env import api_client, seed

from farejador.api.routes import (
    DayCount,
    DurationStats,
    FindingDestinations,
    FindingOut,
    ModelRow,
    ReviewDetail,
    ReviewSummary,
    StatsOut,
    StatsTotals,
    StatusOut,
    StepOut,
    TokenStats,
    ToolResultOut,
)

DOC = (Path(__file__).resolve().parent.parent / "docs" / "api.md").read_text()


def test_the_documented_routes_are_the_real_ones() -> None:
    documented = set(re.findall(r"`GET (/api/[^`]*)`", DOC))
    assert documented == {
        "/api/reviews",
        "/api/reviews/{id}",
        "/api/stats",
        "/api/status",
        "/api/openapi.json",
    }


async def test_the_documented_parameters_match_the_openapi_schema(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    try:
        async with api_client(seeded.path) as client:
            schema = (await client.get("/openapi.json")).json()
    finally:
        seeded.store.close()
    parameters = {p["name"] for p in schema["paths"]["/reviews"]["get"]["parameters"]}
    assert parameters == {"limit", "cursor", "repo", "pr", "outcome", "since", "until"}
    for name in parameters:
        assert f"`{name}`" in DOC, name
    limit = next(
        p for p in schema["paths"]["/reviews"]["get"]["parameters"] if p["name"] == "limit"
    )
    assert (limit["schema"]["minimum"], limit["schema"]["maximum"], limit["schema"]["default"]) == (
        1,
        50,
        20,
    )
    assert "de 1 a 50" in DOC and "| 20 |" in DOC


def test_every_field_of_the_responses_is_documented() -> None:
    models = [
        ReviewSummary, ReviewDetail, StepOut, ToolResultOut, FindingOut, StatusOut,
        StatsOut, StatsTotals, DurationStats, TokenStats, DayCount, FindingDestinations, ModelRow,
    ]  # fmt: skip
    for model in models:
        for field in model.model_fields:
            assert f'"{field}"' in DOC, f"{model.__name__}.{field} is not in docs/api.md"


def test_every_error_the_api_can_return_is_documented() -> None:
    for text in (
        '"not_found"',
        '"method_not_allowed"',
        '"invalid_parameter"',
        '"trace_unavailable"',
        "429",
        "Allow: GET, HEAD",
        "no-store",
        "public, max-age=30",
    ):
        assert text in DOC, text


def test_the_documented_enums_are_the_real_ones() -> None:
    for value in ("inline", "summary", "dropped", "file_ignored", "file_not_in_diff",
                  "line_not_added", "inline_limit", "duplicate", "model_api", "invalid_output",
                  "github_api", "budget", "internal", "complete", "partial", "failed"):  # fmt: skip
        assert f"`{value}`" in DOC, value


def test_the_privacy_and_safety_rules_are_stated() -> None:
    assert "apenas repositórios **públicos**" in DOC
    assert "404" in DOC and "exatamente igual" in DOC
    assert "não confiável" in DOC and "escape" in DOC
    assert "«segredo-removido»" in DOC


def test_the_hidden_error_text_is_documented_as_it_is_in_the_code() -> None:
    from farejador.trace.queries import HIDDEN_ERROR_MESSAGE

    assert f"`{HIDDEN_ERROR_MESSAGE}`" in DOC
    assert "só é pública para `budget`, `model_api` e" in DOC
