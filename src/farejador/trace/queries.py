# Filename: queries.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Read-only queries over the trace, which only ever see public repositories (FR-11, FN-10).

``PUBLIC`` is the single privacy condition: every statement that reads ``trace_run`` embeds it,
and a test fails if one does not. A run of a private repository, or of one whose visibility is
unknown, is invisible here, and so is its existence (M-011).
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from farejador.trace.store import format_time

PUBLIC = "r.repo_public = 1"
QUERY_DEADLINE_S = 5.0
MAX_ID = 2**62

_OPEN_OUTCOMES = ("partial", "running", "incomplete")  # all shown to the world as "partial"
# The text of an internal error can reveal how the server is set up ("check the private key",
# the first line of a git failure), so the public API shows it only for categories whose messages
# are written for the reader; the full text stays in the database.
_PUBLIC_ERROR_CATEGORIES = frozenset({"budget", "model_api", "invalid_output"})
HIDDEN_ERROR_MESSAGE = "detalhes omitidos"
_CURSOR_RE = re.compile(r"^[0-9]{1,19}$")


class InvalidCursor(ValueError):
    """The cursor does not come from this API."""


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(str(last_id).encode("ascii")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursor from None
    if not _CURSOR_RE.fullmatch(raw) or not 0 < int(raw) <= MAX_ID:
        raise InvalidCursor
    return int(raw)


def public_outcome(outcome: str) -> str:
    """Runs still ``running`` or left ``incomplete`` are shown as ``partial``."""
    return "partial" if outcome in _OPEN_OUTCOMES else outcome


@dataclass(frozen=True, slots=True)
class ListFilters:
    repo: str | None = None
    pr_number: int | None = None
    outcome: str | None = None  # "complete", "partial" or "failed"
    since: datetime | None = None
    until: datetime | None = None


def with_deadline(conn: sqlite3.Connection, seconds: float = QUERY_DEADLINE_S) -> None:
    """Interrupt any statement that runs longer than ``seconds`` (NFR-3.3)."""
    deadline = time.monotonic() + seconds
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)


_SUMMARY_COLUMNS = """
    r.id, r.repo, r.pr_number, r.head_sha, r.kind, r.model, r.prompt_version, r.app_version,
    r.outcome, r.steps, r.tokens, r.duration_s, r.error_category, r.started_at,
    (SELECT COUNT(*) FROM trace_finding f WHERE f.run_id = r.id AND f.disposition = 'inline')
        AS findings_inline,
    (SELECT COUNT(*) FROM trace_finding f WHERE f.run_id = r.id AND f.disposition = 'summary')
        AS findings_summary,
    (SELECT COUNT(*) FROM trace_finding f WHERE f.run_id = r.id AND f.disposition = 'dropped')
        AS findings_dropped
"""


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "repo": row["repo"],
        "pr_number": row["pr_number"],
        "head_sha": row["head_sha"],
        "kind": row["kind"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "app_version": row["app_version"],
        "outcome": public_outcome(row["outcome"]),
        "step_count": row["steps"],
        "tokens": row["tokens"],
        "duration_s": row["duration_s"],
        "findings_inline": row["findings_inline"],
        "findings_summary": row["findings_summary"],
        "findings_dropped": row["findings_dropped"],
        "error_category": row["error_category"],
        "started_at": row["started_at"],
    }


def list_runs(
    conn: sqlite3.Connection,
    *,
    limit: int,
    after_id: int | None = None,
    filters: ListFilters | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """A page of summaries, newest first, plus the cursor id of the next page if there is one."""
    filters = filters or ListFilters()
    clauses: list[str] = []  # extra conditions; the privacy one is written in the statement
    params: list[Any] = []
    if after_id is not None:
        clauses.append("r.id < ?")
        params.append(after_id)
    if filters.repo is not None:
        clauses.append("r.repo = ?")
        params.append(filters.repo)
    if filters.pr_number is not None:
        clauses.append("r.pr_number = ?")
        params.append(filters.pr_number)
    if filters.outcome == "partial":
        clauses.append(f"r.outcome IN ({', '.join('?' for _ in _OPEN_OUTCOMES)})")
        params.extend(_OPEN_OUTCOMES)
    elif filters.outcome is not None:
        clauses.append("r.outcome = ?")
        params.append(filters.outcome)
    if filters.since is not None:
        clauses.append("r.started_at >= ?")
        params.append(format_time(filters.since))
    if filters.until is not None:
        clauses.append("r.started_at <= ?")
        params.append(format_time(filters.until))
    extra = "".join(f" AND {clause}" for clause in clauses)
    sql = (
        f"SELECT {_SUMMARY_COLUMNS} FROM trace_run r WHERE {PUBLIC}{extra} "  # noqa: S608
        "ORDER BY r.id DESC LIMIT ?"
    )
    rows = conn.execute(sql, [*params, limit + 1]).fetchall()
    page = rows[:limit]
    next_id = page[-1]["id"] if len(rows) > limit and page else None
    return [_summary(row) for row in page], next_id


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    """The full trace of one run, or ``None`` when it does not exist or is not public."""
    sql = (
        f"SELECT {_SUMMARY_COLUMNS}, r.budgets_json, r.error_message, r.truncated "  # noqa: S608
        f"FROM trace_run r WHERE r.id = ? AND {PUBLIC}"
    )
    row = conn.execute(sql, (run_id,)).fetchone()
    if row is None:
        return None
    detail = _summary(row)
    detail["budgets"] = json.loads(row["budgets_json"])
    category = row["error_category"]
    shown = category in _PUBLIC_ERROR_CATEGORIES
    detail["error"] = (
        {
            "category": category,
            "message": (row["error_message"] or "") if shown else HIDDEN_ERROR_MESSAGE,
        }
        if category
        else None
    )
    detail["truncated"] = bool(row["truncated"])

    steps = conn.execute(
        "SELECT id, idx, started_at, duration_s, tokens, input_messages_json, response_content,"
        " reasoning, tool_calls_json FROM trace_step WHERE run_id = ? ORDER BY idx",
        (run_id,),
    ).fetchall()
    results_by_step: dict[int, list[dict[str, Any]]] = {}
    for result in conn.execute(
        "SELECT t.step_id, t.call_id, t.name, t.duration_s, t.content, t.truncated,"
        " t.original_chars FROM trace_tool_result t JOIN trace_step s ON s.id = t.step_id"
        " WHERE s.run_id = ? ORDER BY t.id",
        (run_id,),
    ):
        results_by_step.setdefault(result["step_id"], []).append(
            {
                "call_id": result["call_id"],
                "name": result["name"],
                "duration_s": result["duration_s"],
                "content": result["content"],
                "truncated": bool(result["truncated"]),
                "original_chars": result["original_chars"],
            }
        )
    detail["steps"] = [
        {
            "index": step["idx"],
            "started_at": step["started_at"],
            "duration_s": step["duration_s"],
            "tokens": step["tokens"],
            "input_messages": json.loads(step["input_messages_json"]),
            "response": {
                "content": step["response_content"],
                "reasoning": step["reasoning"],
                "tool_calls": json.loads(step["tool_calls_json"]),
            },
            "tool_results": results_by_step.get(step["id"], []),
        }
        for step in steps
    ]
    detail["findings"] = [
        {
            "path": finding["path"],
            "line": finding["line"],
            "severity": finding["severity"],
            "category": finding["category"],
            "problem": finding["problem"],
            "rationale": finding["rationale"],
            "suggestion": finding["suggestion"],
            "suggestion_diff": finding["suggestion_diff"],
            "diff_dropped": bool(finding["diff_dropped"]),
            "disposition": finding["disposition"],
            "reason": finding["reason"],
        }
        for finding in conn.execute(
            "SELECT path, line, severity, category, problem, rationale, suggestion,"
            " suggestion_diff, diff_dropped, disposition, reason"
            " FROM trace_finding WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
    ]
    return detail


def count_public(conn: sqlite3.Connection) -> int:
    sql = f"SELECT COUNT(*) FROM trace_run r WHERE {PUBLIC}"  # noqa: S608
    return int(conn.execute(sql).fetchone()[0])


# -- aggregates for the dashboard overview (FR-9, ADR-4) ----------------------------------------

STATS_ROW_CAP = 50_000

_STATS_COLUMNS = """
    r.outcome, r.started_at, r.model, r.prompt_version, r.duration_s, r.tokens, r.finished_at,
    (SELECT COUNT(*) FROM trace_finding f WHERE f.run_id = r.id AND f.disposition = 'inline')
        AS findings_inline,
    (SELECT COUNT(*) FROM trace_finding f WHERE f.run_id = r.id AND f.disposition = 'summary')
        AS findings_summary,
    (SELECT COUNT(*) FROM trace_finding f WHERE f.run_id = r.id AND f.disposition = 'dropped')
        AS findings_dropped
"""


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile of an already sorted list; ``None`` when it is empty."""
    if not sorted_values:
        return None
    rank = max(math.ceil(fraction * len(sorted_values)), 1)
    return round(sorted_values[rank - 1], 3)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def period_start(now: datetime, days: int) -> datetime:
    """Midnight UTC of the first day of a window of ``days`` calendar days ending today."""
    first = now.date() - timedelta(days=days - 1)
    return datetime(first.year, first.month, first.day, tzinfo=now.tzinfo)


def stats(conn: sqlite3.Connection, *, now: datetime, days: int) -> dict[str, Any]:
    """Everything the overview shows for the last ``days`` days, from public repositories only.

    One pass over the runs of the period (at most ``STATS_ROW_CAP``); the medians and the 95th
    percentile come from sorted lists in Python because SQLite has no percentile function.
    """
    since = period_start(now, days)
    sql = (
        f"SELECT {_STATS_COLUMNS} FROM trace_run r "  # noqa: S608
        f"WHERE {PUBLIC} AND r.started_at >= ? AND r.started_at <= ? ORDER BY r.id LIMIT ?"
    )
    rows = conn.execute(sql, (format_time(since), format_time(now), STATS_ROW_CAP + 1)).fetchall()
    capped = len(rows) > STATS_ROW_CAP
    rows = rows[:STATS_ROW_CAP]

    outcomes = {"complete": 0, "partial": 0, "failed": 0}
    per_day: dict[str, int] = {}
    findings = {"inline": 0, "summary": 0, "dropped": 0}
    durations: list[float] = []
    tokens: list[float] = []
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        outcomes[public_outcome(row["outcome"])] += 1
        day = row["started_at"][:10]
        per_day[day] = per_day.get(day, 0) + 1
        run_findings = (row["findings_inline"], row["findings_summary"], row["findings_dropped"])
        findings["inline"] += run_findings[0]
        findings["summary"] += run_findings[1]
        findings["dropped"] += run_findings[2]
        finished = row["finished_at"] is not None
        if finished and row["duration_s"] is not None:
            durations.append(float(row["duration_s"]))
        if finished:
            tokens.append(float(row["tokens"]))
        group = groups.setdefault(
            (row["model"], row["prompt_version"]),
            {"reviews": 0, "failed": 0, "tokens": [], "durations": [], "findings": 0},
        )
        group["reviews"] += 1
        group["failed"] += 1 if public_outcome(row["outcome"]) == "failed" else 0
        group["findings"] += sum(run_findings)
        if finished:
            group["tokens"].append(float(row["tokens"]))
            if row["duration_s"] is not None:
                group["durations"].append(float(row["duration_s"]))

    total = sum(outcomes.values())
    first_day: date = since.date()
    by_day = [
        {"day": (first_day + timedelta(days=offset)).isoformat(), "reviews": 0}
        for offset in range((now.date() - first_day).days + 1)
    ]
    for entry in by_day:
        entry["reviews"] = per_day.get(str(entry["day"]), 0)

    by_model = [
        {
            "model": model,
            "prompt_version": prompt_version,
            "reviews": group["reviews"],
            "failed": group["failed"],
            "mean_tokens": _mean(group["tokens"]),
            "median_duration_s": _median(group["durations"]),
            "findings_per_review": round(group["findings"] / group["reviews"], 3),
        }
        for (model, prompt_version), group in groups.items()
    ]
    by_model.sort(key=lambda item: (-int(item["reviews"]), item["model"], item["prompt_version"]))

    sorted_durations = sorted(durations)
    return {
        "days": days,
        "since": since.date().isoformat(),
        "until": now.date().isoformat(),
        "capped": capped,
        "totals": {
            "reviews": total,
            "complete": outcomes["complete"],
            "partial": outcomes["partial"],
            "failed": outcomes["failed"],
            "failure_rate": round(outcomes["failed"] / total, 4) if total else 0.0,
        },
        "duration_s": {
            "median": _median(durations),
            "p95": _percentile(sorted_durations, 0.95),
        },
        "tokens": {"mean": _mean(tokens), "median": _median(tokens)},
        "by_day": by_day,
        "findings": findings,
        "by_model": by_model,
    }
