# Filename: test_recorder.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The recorder never blocks and never raises (FR-7, NFR-2.1, NFR-2.2, NFR-2.4)."""

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from tests.trace.helpers import NOW, SENTINEL, finding, make_store

from farejador.trace.recorder import NULL_RUN, NullRecorder, TraceRecorder
from farejador.trace.store import RunOutcome, ToolResult, TraceStore, open_readonly

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="SQLite crashes with an access violation under a writer thread on Windows CI",
)


def _recorder(store: TraceStore, **kwargs: Any) -> TraceRecorder:
    recorder = TraceRecorder(
        store,
        model="test/model",
        prompt_version="2026-11-21.2",
        app_version="0.1.0",
        budgets={"max_steps": 15},
        **kwargs,
    )
    recorder.start()
    return recorder


def _begin(recorder: TraceRecorder, key: str = "k") -> Any:
    return recorder.begin(
        trigger_key=key, kind="review", repo="o/r", pr_number=1, head_sha="a" * 40, repo_public=True
    )


def _step(run: Any, index: int = 0, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "index": index,
        "started_at": NOW,
        "duration_s": 1.0,
        "tokens": 10,
        "input_messages": [{"role": "user", "content": "hi"}],
        "response_content": "ok",
        "reasoning": None,
        "tool_calls": [],
        "tool_results": [],
    }
    values.update(overrides)
    run.step(**values)


def _finish(run: Any, outcome: RunOutcome = RunOutcome.COMPLETE) -> None:
    run.finish(outcome=outcome, steps=1, tokens=10, duration_s=1.0)


def test_operations_reach_the_file_in_order_after_stop(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    recorder = _recorder(store)
    run = _begin(recorder)
    for index in range(5):
        _step(run, index)
    run.findings([finding()])
    _finish(run)
    recorder.stop()

    conn = open_readonly(tmp_path / "trace.db")
    row = conn.execute("SELECT * FROM trace_run").fetchone()
    assert (row["model"], row["prompt_version"], row["app_version"], row["outcome"]) == (
        "test/model",
        "2026-11-21.2",
        "0.1.0",
        "complete",
    )
    assert [s["idx"] for s in conn.execute("SELECT idx FROM trace_step ORDER BY id")] == [
        0,
        1,
        2,
        3,
        4,
    ]
    assert conn.execute("SELECT COUNT(*) FROM trace_finding").fetchone()[0] == 1


def test_the_recorder_copies_what_it_is_given_because_the_agent_keeps_mutating_it(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    recorder = _recorder(store)
    run = _begin(recorder)
    messages = [{"role": "user", "content": "original"}]
    results = [ToolResult("c", "grep", 0.1, "result")]
    _step(run, input_messages=messages, tool_results=results)
    messages[0]["content"] = "mutated"
    messages.append({"role": "user", "content": "extra"})
    _finish(run)
    recorder.stop()
    row = (
        open_readonly(tmp_path / "trace.db")
        .execute("SELECT input_messages_json FROM trace_step")
        .fetchone()
    )
    assert "original" in row[0] and "mutated" not in row[0] and "extra" not in row[0]


def test_a_secret_in_the_reasoning_is_masked_by_the_writer(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    recorder = _recorder(store)
    run = _begin(recorder)
    _step(run, reasoning=f"vou usar {SENTINEL} para entrar")
    _finish(run)
    recorder.stop()
    value = (
        open_readonly(tmp_path / "trace.db").execute("SELECT reasoning FROM trace_step").fetchone()
    )
    assert SENTINEL not in value[0] and "«segredo-removido»" in value[0]


class _ExplodingStore(TraceStore):
    """A store whose writes fail, to prove the recorder contains every error."""

    def add_step(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk full")


def test_a_failing_write_never_reaches_the_caller_and_marks_the_run_incomplete(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _ExplodingStore(tmp_path / "trace.db").open()
    recorder = _recorder(store)
    with caplog.at_level(logging.ERROR):
        run = _begin(recorder)
        _step(run)  # raises inside the writer thread
        _finish(run)  # a complete run that lost data is stored as incomplete
        recorder.stop()
    assert recorder.failed == 1
    assert any("trace write failed" in r.getMessage() for r in caplog.records)
    outcome = (
        open_readonly(tmp_path / "trace.db").execute("SELECT outcome FROM trace_run").fetchone()
    )
    assert outcome[0] == "incomplete"


def test_a_failed_run_keeps_its_failed_outcome_even_after_a_lost_record(tmp_path: Path) -> None:
    store = _ExplodingStore(tmp_path / "trace.db").open()
    recorder = _recorder(store)
    run = _begin(recorder)
    _step(run)
    run.finish(
        outcome=RunOutcome.FAILED,
        steps=0,
        tokens=0,
        duration_s=1.0,
        error_category="model_api",
        error_message="HTTP 429",
    )
    recorder.stop()
    row = (
        open_readonly(tmp_path / "trace.db")
        .execute("SELECT outcome, error_category FROM trace_run")
        .fetchone()
    )
    assert (row[0], row[1]) == ("failed", "model_api")


def test_a_full_queue_drops_records_without_blocking_or_raising(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    gate = threading.Event()

    class SlowStore(TraceStore):
        def begin_run(self, **kwargs: Any) -> int:
            gate.wait(5)
            return super().begin_run(**kwargs)

    store = SlowStore(tmp_path / "trace.db").open()
    recorder = _recorder(store, queue_size=3)
    with caplog.at_level(logging.ERROR):
        started = time.perf_counter()
        run = _begin(recorder)
        for index in range(50):
            _step(run, index)
        elapsed = time.perf_counter() - started
    assert elapsed < 0.5  # nothing waited for the blocked writer
    assert recorder.dropped >= 40
    assert any("trace record dropped" in r.getMessage() for r in caplog.records)
    gate.set()
    _finish(run)
    recorder.stop()


def test_enqueueing_costs_well_under_a_millisecond(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    recorder = _recorder(store, queue_size=5000)
    run = _begin(recorder)
    started = time.perf_counter()
    for index in range(1000):
        _step(run, index, input_messages=[{"role": "user", "content": "m" * 500}])
    average_ms = (time.perf_counter() - started) / 1000 * 1000
    recorder.stop()
    assert average_ms < 1, f"{average_ms:.3f} ms per record"


def test_stop_flushes_everything_that_was_queued(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    recorder = _recorder(store, queue_size=2000)
    run = _begin(recorder)
    for index in range(300):
        _step(run, index)
    _finish(run)
    started = time.perf_counter()
    recorder.stop(timeout=5)
    assert time.perf_counter() - started < 5
    assert (
        open_readonly(tmp_path / "trace.db")
        .execute("SELECT COUNT(*) FROM trace_step")
        .fetchone()[0]
        == 300
    )


def test_after_stop_new_records_are_ignored_silently(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    recorder = _recorder(store)
    recorder.stop()
    run = _begin(recorder)
    _step(run)
    _finish(run)
    assert recorder.dropped == 3
    assert store.count_runs() == 0
    recorder.stop()  # stopping twice is harmless


def test_a_store_that_cannot_begin_a_run_makes_every_later_call_a_no_op(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.db")  # never opened
    recorder = _recorder(store)
    run = _begin(recorder)
    _step(run)
    run.findings([finding()])
    _finish(run)
    recorder.stop()
    assert recorder.failed >= 1


def test_the_null_recorder_and_run_accept_anything() -> None:
    run = NullRecorder().begin(whatever=1)
    assert run is NULL_RUN
    run.step(index=0)
    run.findings([])
    run.finish(outcome=RunOutcome.COMPLETE)
