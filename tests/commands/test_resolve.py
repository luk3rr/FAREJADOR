# Filename: test_resolve.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import pytest
import respx
from tests.command_env import build_cmd_env, thread_node
from tests.llm_fakes import call, reply, submit_review

from farejador.state.store import ThreadStatus


def _verdicts(*items: tuple[str, bool]):  # type: ignore[no-untyped-def]
    return call(
        "submit_verdicts",
        {"verdicts": [{"thread_id": t, "fixed": f, "note": "n"} for t, f in items]},
    )


async def test_fixed_threads_are_resolved_on_github_and_in_the_store(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", True), ("T2", False), ("T3", True)))],
        threads=[thread_node("T1"), thread_node("T2"), thread_node("T3")],
    )
    await cmd.handler.run(cmd.trigger())
    assert cmd.resolved_ids == ["T1", "T3"]
    statuses = {t.thread_id: t.status for t in cmd.env.store.list_threads("o/r", 1)}
    assert statuses == {
        "T1": ThreadStatus.RESOLVED,
        "T2": ThreadStatus.OPEN,
        "T3": ThreadStatus.RESOLVED,
    }


async def test_a_thread_that_cannot_be_resolved_stays_pending_and_the_others_proceed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", True), ("T2", True)))],
        threads=[thread_node("T1"), thread_node("T2")],
    )
    cmd.failing_ids.add("T1")
    await cmd.handler.run(cmd.trigger())
    assert cmd.resolved_ids == ["T2"]
    statuses = {t.thread_id: t.status for t in cmd.env.store.list_threads("o/r", 1)}
    assert statuses == {"T1": ThreadStatus.OPEN, "T2": ThreadStatus.RESOLVED}
    # T1 is still pending, so no new review was started
    assert cmd.env.review_route.call_count == 0
    assert cmd.env.comment_route.call_count == 1


async def test_no_thread_is_resolved_when_the_model_says_nothing_is_fixed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", False)))],
        threads=[thread_node("T1")],
    )
    await cmd.handler.run(cmd.trigger())
    assert cmd.resolved_ids == []


async def test_a_partial_reevaluation_never_resolves_threads_without_a_verdict(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    from farejador.agent.runner import Budget

    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(call("list_dir", {}, "c1")), reply(_verdicts(("T1", True)))],  # T2 missing
        threads=[thread_node("T1"), thread_node("T2")],
        budget=Budget(max_steps=1),
    )
    await cmd.handler.run(cmd.trigger())
    assert cmd.resolved_ids == []
    assert cmd.env.review_route.call_count == 0
    assert submit_review is not None


async def test_a_resolve_failure_logs_the_reason_github_gave(
    tmp_path: Path, respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", True)))],
        threads=[thread_node("T1")],
    )
    cmd.failing_ids.add("T1")
    with caplog.at_level("WARNING", logger="farejador.commands"):
        await cmd.handler.run(cmd.trigger())
    record = next(r for r in caplog.records if r.getMessage() == "could not resolve a thread")
    assert record.thread_id == "T1"  # type: ignore[attr-defined]
    assert "cannot resolve" in record.reason  # type: ignore[attr-defined]
