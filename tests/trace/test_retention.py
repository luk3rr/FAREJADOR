# Filename: test_retention.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio
import logging
from pathlib import Path

import pytest
from tests.trace.helpers import Clock, begin, finding, finish, make_store, one_step

from farejador.trace.retention import purge_expired, retention_loop, run_maintenance
from farejador.trace.store import TraceStore, open_readonly


def _count(tmp_path: Path, table: str) -> int:
    conn = open_readonly(tmp_path / "trace.db")
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608


def test_a_run_of_31_days_is_deleted_and_one_of_29_days_is_kept(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    old = begin(store, key="old")
    one_step(store, old)
    store.add_finding(old, finding())
    finish(store, old)
    clock.advance(days=2)
    young = begin(store, key="young")
    one_step(store, young)
    finish(store, young)
    clock.advance(days=29)  # old is 31 days old, young is 29

    assert purge_expired(store, retention_days=30) == 1
    conn = open_readonly(tmp_path / "trace.db")
    assert [r[0] for r in conn.execute("SELECT id FROM trace_run")] == [young]


def test_the_children_are_deleted_together_with_the_run(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    run_id = begin(store)
    one_step(store, run_id)
    store.add_finding(run_id, finding())
    clock.advance(days=40)
    purge_expired(store, retention_days=30)
    for table in ("trace_run", "trace_step", "trace_tool_result", "trace_finding"):
        assert _count(tmp_path, table) == 0, table


def test_many_runs_are_deleted_in_batches(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    for number in range(25):
        begin(store, key=f"k{number}", pr=number + 1)
    clock.advance(days=45)
    assert purge_expired(store, retention_days=30, batch_size=10) == 25
    assert store.count_runs() == 0


def test_maintenance_marks_stale_runs_and_purges(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    begin(store, key="gone")
    clock.advance(days=35)
    begin(store, key="stuck")
    clock.advance(hours=2)
    stale, deleted = run_maintenance(store, retention_days=30)
    # "gone" was also abandoned, so both are marked; only the 35-day-old one is purged
    assert (stale, deleted) == (2, 1)


async def test_the_loop_runs_at_start_then_every_interval_and_logs_the_count(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    begin(store)
    clock.advance(days=31)
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise asyncio.CancelledError

    with caplog.at_level(logging.INFO), pytest.raises(asyncio.CancelledError):
        await retention_loop(store, 30, interval_s=86400, sleep=fake_sleep)
    assert waits == [86400, 86400]
    messages = [r for r in caplog.records if r.getMessage() == "trace maintenance finished"]
    assert len(messages) == 2
    assert messages[0].deleted_runs == 1  # type: ignore[attr-defined]
    assert messages[1].deleted_runs == 0  # type: ignore[attr-defined]


async def test_an_error_in_the_maintenance_is_logged_and_never_ends_the_loop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = TraceStore(tmp_path / "trace.db")  # never opened: every pass fails
    calls = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise asyncio.CancelledError

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await retention_loop(store, 30, sleep=fake_sleep)
    assert calls == 3
    assert len([r for r in caplog.records if "maintenance failed" in r.getMessage()]) == 3
