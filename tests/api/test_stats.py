# Filename: test_stats.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""GET /api/stats: right numbers, public only, consistent with the list (FR-9, FR-10)."""

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.api.test_perf import _bulk
from tests.api_env import api_client, make_run
from tests.trace.helpers import Clock

from farejador.trace import queries
from farejador.trace.store import RunOutcome, TraceStore

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)


def at(clock: Clock, stamp: str) -> None:
    clock.now = datetime.fromisoformat(stamp).replace(tzinfo=UTC)


def build(tmp_path: Path) -> Path:
    """A small, hand-checkable history: see the expectations in the tests."""
    clock = Clock(NOW)
    store = TraceStore(tmp_path / "trace.db", clock=clock).open()

    def run(stamp: str, **kwargs: Any) -> int:
        at(clock, stamp)
        kwargs.setdefault("repo", "o/r")
        kwargs.setdefault("public", True)
        return make_run(store, key=stamp, **kwargs)

    run("2026-11-21T09:00:00", model="model-a", duration_s=10, tokens=1000, findings=(2, 1, 0))
    run(
        "2026-11-21T10:00:00",
        model="model-a",
        outcome=RunOutcome.FAILED,
        duration_s=2,
        tokens=0,
        findings=(0, 0, 0),
        steps=0,
        error=("model_api", "HTTP 429"),
    )
    run(
        "2026-11-20T08:00:00",
        model="model-b",
        outcome=RunOutcome.PARTIAL,
        duration_s=30,
        tokens=5000,
        findings=(1, 2, 1),
    )
    run(
        "2026-11-18T08:00:00",
        model="model-a",
        prompt_version="2026-11-21.1",
        duration_s=20,
        tokens=3000,
        findings=(3, 0, 0),
    )
    run(
        "2026-11-19T08:00:00",
        outcome=RunOutcome.INCOMPLETE,
        duration_s=5,
        tokens=200,
        findings=(0, 0, 1),
    )
    run("2026-11-14T23:59:59", model="model-a", duration_s=99, tokens=99_000)  # before the 7 days
    # a run that is still going on: no finish, so it is "partial" and has no duration or tokens
    at(clock, "2026-11-21T11:30:00")
    store.begin_run(
        trigger_key="running",
        kind="review",
        repo="o/r",
        pr_number=9,
        head_sha=None,
        repo_public=True,
        model="test/model",
        prompt_version="2026-11-21.2",
        app_version="0.1.0",
        budgets={},
    )
    # private and unknown repositories: they must not show anywhere
    run("2026-11-21T11:00:00", repo="acme/secret", public=False, model="secret/model", tokens=777)
    run("2026-11-21T11:10:00", repo="x/unknown", public=None, model="unknown/model", tokens=888)
    store.close()
    return tmp_path / "trace.db"


async def get_stats(path: Path, query: str = "", **client_kwargs: Any) -> Any:
    async with api_client(path, clock=lambda: NOW, **client_kwargs) as client:
        return await client.get(f"/stats{query}")


async def test_the_numbers_of_a_seven_day_window_match_the_hand_computed_ones(
    tmp_path: Path,
) -> None:
    body = (await get_stats(build(tmp_path), "?days=7")).json()
    assert (body["days"], body["since"], body["until"], body["capped"]) == (
        7,
        "2026-11-15",
        "2026-11-21",
        False,
    )
    assert body["totals"] == {
        "reviews": 6,  # the 14th is out; private, unknown and... the running one is in
        "complete": 2,
        "partial": 3,  # partial, incomplete and the one still running
        "failed": 1,
        "failure_rate": round(1 / 6, 4),
    }
    # finished runs only: 10, 2, 30, 20 and 5 seconds; 1000, 0, 5000, 3000 and 200 tokens
    assert body["duration_s"] == {"median": 10.0, "p95": 30.0}
    assert body["tokens"] == {"mean": 1840.0, "median": 1000.0}
    assert body["findings"] == {"inline": 6, "summary": 3, "dropped": 2}


async def test_each_day_of_the_window_is_listed_even_when_empty(tmp_path: Path) -> None:
    body = (await get_stats(build(tmp_path), "?days=7")).json()
    assert [(d["day"], d["reviews"]) for d in body["by_day"]] == [
        ("2026-11-15", 0),
        ("2026-11-16", 0),
        ("2026-11-17", 0),
        ("2026-11-18", 1),
        ("2026-11-19", 1),
        ("2026-11-20", 1),
        ("2026-11-21", 3),
    ]
    assert sum(d["reviews"] for d in body["by_day"]) == body["totals"]["reviews"]


async def test_the_table_by_model_and_prompt(tmp_path: Path) -> None:
    body = (await get_stats(build(tmp_path), "?days=7")).json()
    assert body["by_model"] == [
        {
            "model": "model-a",
            "prompt_version": "2026-11-21.2",
            "reviews": 2,
            "failed": 1,
            "mean_tokens": 500.0,
            "median_duration_s": 6.0,
            "findings_per_review": 1.5,
        },
        {
            "model": "test/model",  # the incomplete run and the one still running
            "prompt_version": "2026-11-21.2",
            "reviews": 2,
            "failed": 0,
            "mean_tokens": 200.0,  # the running one has no tokens yet and is left out
            "median_duration_s": 5.0,
            "findings_per_review": 0.5,
        },
        {
            "model": "model-a",
            "prompt_version": "2026-11-21.1",
            "reviews": 1,
            "failed": 0,
            "mean_tokens": 3000.0,
            "median_duration_s": 20.0,
            "findings_per_review": 3.0,
        },
        {
            "model": "model-b",
            "prompt_version": "2026-11-21.2",
            "reviews": 1,
            "failed": 0,
            "mean_tokens": 5000.0,
            "median_duration_s": 30.0,
            "findings_per_review": 4.0,
        },
    ]


async def test_private_and_unknown_repositories_appear_nowhere(tmp_path: Path) -> None:
    response = await get_stats(build(tmp_path), "?days=30")
    for leak in ("secret", "unknown", "acme", "x/unknown", "777", "888"):
        assert leak not in response.text, leak
    body = response.json()
    assert body["totals"]["reviews"] == 7  # the 14th is inside 30 days
    assert {row["model"] for row in body["by_model"]} == {"model-a", "model-b", "test/model"}


async def test_the_window_starts_at_midnight_utc_of_its_first_day(tmp_path: Path) -> None:
    path = build(tmp_path)
    seven = (await get_stats(path, "?days=7")).json()
    thirty = (await get_stats(path)).json()  # the default
    assert seven["totals"]["reviews"] + 1 == thirty["totals"]["reviews"]  # exactly the 14th run
    assert thirty["days"] == 30 and thirty["since"] == "2026-10-23"
    assert len(thirty["by_day"]) == 30
    one = (await get_stats(path, "?days=1")).json()
    assert one["since"] == one["until"] == "2026-11-21"
    assert [d["day"] for d in one["by_day"]] == ["2026-11-21"]
    assert one["totals"]["reviews"] == 3


async def test_a_run_exactly_at_midnight_is_inside_and_one_second_before_is_outside(
    tmp_path: Path,
) -> None:
    clock = Clock(NOW)
    store = TraceStore(tmp_path / "trace.db", clock=clock).open()
    for stamp in ("2026-11-14T23:59:59", "2026-11-15T00:00:00"):
        at(clock, stamp)
        make_run(store, repo="o/r", public=True, key=stamp)
    store.close()
    body = (await get_stats(tmp_path / "trace.db", "?days=7")).json()
    assert body["totals"]["reviews"] == 1
    assert body["by_day"][0] == {"day": "2026-11-15", "reviews": 1}


async def test_median_and_p95_use_the_nearest_rank_of_the_finished_runs(tmp_path: Path) -> None:
    clock = Clock(NOW)
    store = TraceStore(tmp_path / "trace.db", clock=clock).open()
    for second in range(1, 21):
        at(clock, "2026-11-21T08:00:00")
        make_run(store, repo="o/r", public=True, key=str(second), duration_s=float(second))
    store.close()
    body = (await get_stats(tmp_path / "trace.db", "?days=1")).json()
    assert body["duration_s"] == {"median": 10.5, "p95": 19.0}


async def test_an_empty_period_is_all_zeros_and_nulls(tmp_path: Path) -> None:
    TraceStore(tmp_path / "trace.db").open().close()
    body = (await get_stats(tmp_path / "trace.db", "?days=3")).json()
    assert body["totals"] == {
        "reviews": 0,
        "complete": 0,
        "partial": 0,
        "failed": 0,
        "failure_rate": 0.0,
    }
    assert body["duration_s"] == {"median": None, "p95": None}
    assert body["tokens"] == {"mean": None, "median": None}
    assert body["findings"] == {"inline": 0, "summary": 0, "dropped": 0}
    assert body["by_model"] == []
    assert len(body["by_day"]) == 3 and all(d["reviews"] == 0 for d in body["by_day"])


async def test_the_totals_equal_what_the_paginated_list_shows_for_the_same_period(
    tmp_path: Path,
) -> None:
    path = build(tmp_path)
    async with api_client(path, clock=lambda: NOW) as client:
        stats = (await client.get("/stats", params={"days": 7})).json()
        items: list[dict[str, Any]] = []
        cursor = None
        while True:
            params: dict[str, Any] = {
                "limit": 2,
                "since": "2026-11-15T00:00:00Z",
                "until": "2026-11-21T12:00:00Z",
            }
            if cursor:
                params["cursor"] = cursor
            page = (await client.get("/reviews", params=params)).json()
            items += page["items"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
    assert stats["totals"]["reviews"] == len(items)
    for outcome in ("complete", "partial", "failed"):
        assert stats["totals"][outcome] == sum(1 for i in items if i["outcome"] == outcome)
    for destination in ("inline", "summary", "dropped"):
        assert stats["findings"][destination] == sum(i[f"findings_{destination}"] for i in items)


@pytest.mark.parametrize(
    "query", ["?days=0", "?days=366", "?days=-1", "?days=abc", "?days=1.5", "?days="]
)
async def test_invalid_days_get_a_422_that_names_the_field(tmp_path: Path, query: str) -> None:
    response = await get_stats(build(tmp_path), query)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_parameter"
    assert response.json()["detail"][0]["field"] == "days"


@pytest.mark.parametrize("days", [1, 365])
async def test_the_limits_of_days_are_accepted(tmp_path: Path, days: int) -> None:
    body = (await get_stats(build(tmp_path), f"?days={days}")).json()
    assert len(body["by_day"]) == days


async def test_the_cache_policy_is_60_seconds_on_success_and_never_on_errors(
    tmp_path: Path,
) -> None:
    path = build(tmp_path)
    ok = await get_stats(path)
    bad = await get_stats(path, "?days=0")
    missing = await get_stats(tmp_path / "absent.db")
    assert ok.headers["cache-control"] == "public, max-age=60"
    assert bad.headers["cache-control"] == "no-store"
    assert missing.status_code == 503 and missing.json() == {"error": "trace_unavailable"}
    assert missing.headers["cache-control"] == "no-store"
    assert ok.headers["x-content-type-options"] == "nosniff"


async def test_only_reads_are_allowed_and_head_works(tmp_path: Path) -> None:
    path = build(tmp_path)
    async with api_client(path, clock=lambda: NOW) as client:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = await client.request(method, "/stats")
            assert response.status_code == 405, method
            assert response.headers["allow"] == "GET, HEAD"
        head = await client.head("/stats")
    assert head.status_code == 200 and head.content == b""


async def test_the_answer_has_exactly_the_contracted_keys(tmp_path: Path) -> None:
    body = (await get_stats(build(tmp_path), "?days=7")).json()
    assert set(body) == {
        "days", "since", "until", "capped", "totals", "duration_s", "tokens", "by_day",
        "findings", "by_model",
    }  # fmt: skip
    assert set(body["totals"]) == {"reviews", "complete", "partial", "failed", "failure_rate"}
    assert set(body["by_model"][0]) == {
        "model", "prompt_version", "reviews", "failed", "mean_tokens", "median_duration_s",
        "findings_per_review",
    }  # fmt: skip


async def test_a_very_large_period_is_capped_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "STATS_ROW_CAP", 3)
    body = (await get_stats(build(tmp_path), "?days=7")).json()
    assert body["capped"] is True
    assert body["totals"]["reviews"] == 3


async def test_the_default_clock_is_the_real_one(tmp_path: Path) -> None:
    TraceStore(tmp_path / "trace.db").open().close()
    async with api_client(tmp_path / "trace.db") as client:
        body = (await client.get("/stats", params={"days": 1})).json()
    assert body["until"] == datetime.now(UTC).date().isoformat()


async def test_reading_takes_at_most_two_sql_statements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = build(tmp_path)
    statements: list[str] = []
    from farejador.api import routes

    real = routes.open_readonly

    def counting(target: Path | str) -> sqlite3.Connection:
        conn = real(target)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(routes, "open_readonly", counting)
    await get_stats(path, "?days=30")
    reads = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert 1 <= len(reads) <= 2, reads


async def test_ten_thousand_runs_are_aggregated_fast_and_the_answer_is_small(
    tmp_path: Path,
) -> None:
    path = _bulk(tmp_path, 10_000)
    moment = datetime(2026, 11, 28, 23, 0, tzinfo=UTC)
    timings: list[float] = []
    async with api_client(path, clock=lambda: moment) as client:
        for _ in range(20):
            started = time.perf_counter()
            response = await client.get("/stats", params={"days": 30})
            timings.append(time.perf_counter() - started)
        wide = await client.get("/stats", params={"days": 365})
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert response.status_code == 200 and response.json()["totals"]["reviews"] > 7000
    assert p95 < 0.2, f"p95 {p95 * 1000:.0f} ms"
    assert len(wide.content) < 50_000
    assert len(wide.json()["by_day"]) == 365
