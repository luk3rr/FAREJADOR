# Filename: test_contract.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The API answers with exactly the fields promised in design.md § 2.8 (FR-18)."""

import re
from pathlib import Path

from tests.api_env import api_client, seed

from farejador.api.routes import (
    DayCount,
    DurationStats,
    ErrorOut,
    FindingDestinations,
    FindingOut,
    MessageOut,
    ModelRow,
    ResponseOut,
    ReviewDetail,
    ReviewSummary,
    StatsOut,
    StatsTotals,
    StatusOut,
    StepOut,
    TokenStats,
    ToolCallOut,
    ToolResultOut,
)

ROOT = Path(__file__).resolve().parent.parent.parent
DESIGN = ROOT / ".aidlc" / "261121-review-trace-api" / "design.md"

SUMMARY = {
    "id", "repo", "pr_number", "head_sha", "kind", "model", "prompt_version", "app_version",
    "outcome", "step_count", "tokens", "duration_s", "findings_inline", "findings_summary",
    "findings_dropped", "error_category", "started_at",
}  # fmt: skip
DETAIL = SUMMARY | {"budgets", "steps", "findings", "error", "truncated"}
STEP = {
    "index", "started_at", "duration_s", "tokens", "input_messages", "response", "tool_results",
}  # fmt: skip
TOOL_RESULT = {"call_id", "name", "duration_s", "content", "truncated", "original_chars"}
FINDING = {
    "path", "line", "severity", "category", "problem", "rationale", "suggestion",
    "suggestion_diff", "diff_dropped", "disposition", "reason",
}  # fmt: skip


def test_the_models_have_exactly_the_contract_fields() -> None:
    assert set(ReviewSummary.model_fields) == SUMMARY
    assert set(ReviewDetail.model_fields) == DETAIL
    assert set(StepOut.model_fields) == STEP
    assert set(ToolResultOut.model_fields) == TOOL_RESULT
    assert set(FindingOut.model_fields) == FINDING
    assert set(ResponseOut.model_fields) == {"content", "reasoning", "tool_calls"}
    assert set(ToolCallOut.model_fields) == {"id", "name", "arguments"}
    assert set(MessageOut.model_fields) == {"role", "content", "tool_call_id"}
    assert set(ErrorOut.model_fields) == {"category", "message"}
    assert set(StatusOut.model_fields) == {
        "status",
        "trace_available",
        "retention_days",
        "reviews",
        "app_version",
        "started_at",
    }


async def test_the_real_responses_match_the_models(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    async with api_client(seeded.path) as client:
        listed = (await client.get("/reviews")).json()
        detail = (await client.get(f"/reviews/{seeded.public_ids[0]}")).json()
    assert set(listed) == {"items", "next_cursor"}
    assert all(set(item) == SUMMARY for item in listed["items"])
    assert set(detail) == DETAIL
    assert all(set(step) == STEP for step in detail["steps"])
    assert all(set(result) == TOOL_RESULT for s in detail["steps"] for result in s["tool_results"])
    assert all(set(finding) == FINDING for finding in detail["findings"])


def test_the_design_document_names_the_same_summary_fields() -> None:
    """The contract is written in 2.8; keep the document and the code from drifting apart."""
    if not DESIGN.exists():
        return  # the design folder is kept local, not in git
    text = DESIGN.read_text()
    block = text.split("// GET /api/reviews\n", 1)[1].split("```", 1)[0]
    documented = set(re.findall(r'"([a-z_]+)":', block))
    assert (SUMMARY - {"steps"}) <= documented | {"next_cursor", "items"}


def test_the_stats_models_have_exactly_the_contract_fields() -> None:
    assert set(StatsOut.model_fields) == {
        "days", "since", "until", "capped", "totals", "duration_s", "tokens", "by_day",
        "findings", "by_model",
    }  # fmt: skip
    assert set(StatsTotals.model_fields) == {
        "reviews", "complete", "partial", "failed", "failure_rate",
    }  # fmt: skip
    assert set(DurationStats.model_fields) == {"median", "p95"}
    assert set(TokenStats.model_fields) == {"mean", "median"}
    assert set(DayCount.model_fields) == {"day", "reviews"}
    assert set(FindingDestinations.model_fields) == {"inline", "summary", "dropped"}
    assert set(ModelRow.model_fields) == {
        "model", "prompt_version", "reviews", "failed", "mean_tokens", "median_duration_s",
        "findings_per_review",
    }  # fmt: skip
