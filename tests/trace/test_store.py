# Filename: test_store.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json
import sqlite3
from pathlib import Path

import pytest
from tests.trace.helpers import (
    NOW,
    SENTINEL,
    Clock,
    begin,
    finding,
    finish,
    make_store,
    one_step,
)

from farejador.review.filters import MASKED
from farejador.trace.store import (
    Disposition,
    RunOutcome,
    ToolResult,
    TraceStore,
    TraceUnavailable,
    open_readonly,
)


def test_the_file_is_created_with_the_schema_and_a_version(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert (tmp_path / "trace.db").exists()
    assert store.schema_version == 1
    tables = {
        row[0]
        for row in sqlite3.connect(tmp_path / "trace.db").execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"trace_run", "trace_step", "trace_tool_result", "trace_finding"} <= tables
    store.close()
    assert TraceStore(tmp_path / "trace.db").open().schema_version == 1  # reopening is a no-op


def test_a_run_with_steps_tools_and_findings_is_stored_in_order(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    run_id = begin(store)
    one_step(store, run_id, index=0)
    one_step(store, run_id, index=1, content="second")
    store.add_finding(run_id, finding())
    store.add_finding(
        run_id, finding(disposition=Disposition.SUMMARY, reason="line_not_added", line=9)
    )
    finish(store, run_id)

    conn = open_readonly(tmp_path / "trace.db")
    run = conn.execute("SELECT * FROM trace_run").fetchone()
    assert (run["outcome"], run["repo"], run["repo_public"], run["steps"]) == (
        "complete",
        "o/r",
        1,
        1,
    )
    assert json.loads(run["budgets_json"])["max_steps"] == 15
    steps = conn.execute("SELECT * FROM trace_step ORDER BY idx").fetchall()
    assert [s["idx"] for s in steps] == [0, 1]
    assert json.loads(steps[1]["input_messages_json"]) == [{"role": "user", "content": "second"}]
    assert json.loads(steps[0]["tool_calls_json"])[0]["name"] == "read_file"
    results = conn.execute("SELECT * FROM trace_tool_result").fetchall()
    assert [(r["name"], r["content"], r["truncated"]) for r in results] == [
        ("read_file", "file body", 0)
    ] * 2
    findings = conn.execute("SELECT disposition, reason FROM trace_finding ORDER BY id").fetchall()
    assert [tuple(f) for f in findings] == [("inline", None), ("summary", "line_not_added")]


def test_no_secret_reaches_the_file_in_any_field(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    run_id = begin(store)
    leaked = f"here is {SENTINEL} inside"
    store.add_step(
        run_id,
        index=0,
        started_at=NOW,
        duration_s=1.0,
        tokens=1,
        input_messages=[{"role": "user", "content": leaked}],
        response_content=leaked,
        reasoning=leaked,
        tool_calls=[{"id": "c", "name": "grep", "arguments": json.dumps({"pattern": SENTINEL})}],
        tool_results=[ToolResult("c", "grep", 0.1, leaked)],
    )
    store.add_finding(
        run_id,
        finding(
            path=leaked,
            problem=leaked,
            rationale=leaked,
            suggestion=leaked,
            suggestion_diff=f"-{SENTINEL}\n+x",
        ),
    )
    store.finish_run(
        run_id,
        outcome=RunOutcome.FAILED,
        steps=1,
        tokens=1,
        duration_s=1.0,
        error_category="internal",
        error_message=leaked,
    )
    store.close()

    raw = b"".join(
        path.read_bytes() for path in tmp_path.iterdir() if path.name.startswith("trace.db")
    )
    assert SENTINEL.encode() not in raw
    assert MASKED.encode() in raw


def test_oversized_content_is_truncated_and_the_run_is_flagged(tmp_path: Path) -> None:
    store = make_store(tmp_path, max_item_chars=200, max_run_bytes=100_000)
    run_id = begin(store)
    store.add_step(
        run_id,
        index=0,
        started_at=NOW,
        duration_s=1.0,
        tokens=1,
        input_messages=[],
        response_content=None,
        reasoning=None,
        tool_calls=[],
        tool_results=[ToolResult("c", "read_file", 0.1, "y" * 5000)],
    )
    finish(store, run_id)
    conn = open_readonly(tmp_path / "trace.db")
    result = conn.execute("SELECT * FROM trace_tool_result").fetchone()
    assert (result["truncated"], result["original_chars"]) == (1, 5000)
    assert len(result["content"]) < 300
    assert conn.execute("SELECT truncated FROM trace_run").fetchone()[0] == 1


def test_the_run_ceiling_stops_storing_text_but_keeps_the_metadata(tmp_path: Path) -> None:
    store = make_store(tmp_path, max_item_chars=10_000, max_run_bytes=10_000)
    run_id = begin(store)
    for index in range(5):
        one_step(store, run_id, index=index, content="z" * 4000)
    finish(store, run_id)
    conn = open_readonly(tmp_path / "trace.db")
    steps = conn.execute("SELECT idx, tokens, input_messages_json FROM trace_step").fetchall()
    assert [s["idx"] for s in steps] == [0, 1, 2, 3, 4]
    assert all(s["tokens"] == 100 for s in steps)
    assert json.loads(steps[-1]["input_messages_json"])[0]["content"] == ""
    total = sum(len(s["input_messages_json"]) for s in steps)
    assert total < 12_000


def test_a_private_or_unknown_repository_downgrades_its_older_runs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = begin(store, repo="o/r", public=True, key="a")
    other = begin(store, repo="o/other", public=True, key="b")
    begin(store, repo="o/r", public=None, key="c")
    conn = open_readonly(tmp_path / "trace.db")
    visibility = {r["id"]: r["repo_public"] for r in conn.execute("SELECT * FROM trace_run")}
    assert visibility[first] == 0  # downgraded
    assert visibility[other] == 1  # another repository is untouched
    begin(store, repo="o/r", public=True, key="d")  # a public run never promotes the old ones
    assert (
        open_readonly(tmp_path / "trace.db")
        .execute("SELECT repo_public FROM trace_run WHERE id = ?", (first,))
        .fetchone()[0]
        == 0
    )


def test_unknown_visibility_is_stored_as_null_and_does_not_downgrade_itself(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    run_id = begin(store, public=None)
    row = (
        open_readonly(tmp_path / "trace.db")
        .execute("SELECT repo_public FROM trace_run WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row[0] is None


def test_abandoned_runs_become_incomplete_after_an_hour(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    old = begin(store, key="old")
    clock.advance(minutes=30)
    recent = begin(store, key="recent")
    clock.advance(minutes=45)  # the first one is 75 min old, the second 45 min
    assert store.mark_stale_running() == 1
    conn = open_readonly(tmp_path / "trace.db")
    outcomes = {r["id"]: r["outcome"] for r in conn.execute("SELECT id, outcome FROM trace_run")}
    assert outcomes == {old: "incomplete", recent: "running"}


def test_the_readonly_connection_cannot_write(tmp_path: Path) -> None:
    make_store(tmp_path)
    conn = open_readonly(tmp_path / "trace.db")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM trace_run")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")


@pytest.mark.parametrize("problem", ["missing", "garbage", "directory"])
def test_an_unusable_file_raises_a_clear_error_and_never_anything_else(
    tmp_path: Path, problem: str
) -> None:
    target = tmp_path / "trace.db"
    if problem == "garbage":
        target.write_bytes(b"this is not a sqlite database" * 50)
    elif problem == "directory":
        target.mkdir()
    if problem == "missing":
        with pytest.raises(TraceUnavailable):
            open_readonly(target)
    else:
        with pytest.raises(TraceUnavailable):
            TraceStore(target).open()
        with pytest.raises(TraceUnavailable):
            open_readonly(target)


def test_using_a_store_that_is_closed_raises_the_same_error(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.close()
    with pytest.raises(TraceUnavailable):
        begin(store)


def test_a_failed_open_leaves_no_connection_behind(tmp_path: Path) -> None:
    target = tmp_path / "trace.db"
    target.write_bytes(b"this is not a sqlite database" * 50)
    store = TraceStore(target)
    with pytest.raises(TraceUnavailable):
        store.open()
    assert store._conn is None  # closed and forgotten, not left to the garbage collector
