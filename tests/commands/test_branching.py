# Filename: test_branching.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json
from pathlib import Path

import respx
from tests.command_env import build_cmd_env, thread_node
from tests.llm_fakes import call, finding, reply, submit_review

from farejador.state.store import Outcome, TriggerStatus


def _verdicts(*items: tuple[str, bool]):  # type: ignore[no-untyped-def]
    return call(
        "submit_verdicts",
        {"verdicts": [{"thread_id": t, "fixed": f, "note": "n"} for t, f in items]},
    )


async def test_without_any_open_thread_a_new_review_is_posted_at_the_current_head(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [reply(submit_review([finding("b.py", 2)]))])
    trigger = cmd.trigger()
    await cmd.handler.run(trigger)

    assert cmd.env.review_route.call_count == 1
    payload = json.loads(cmd.env.review_route.calls.last.request.content)
    assert payload["commit_id"] == cmd.env.sha
    assert len(payload["comments"]) == 1
    assert cmd.env.comment_route.call_count == 0
    # the run belongs to the command trigger
    assert cmd.env.store.has_review_run("o/r", 1) is True
    row = cmd.env.store._db().execute("SELECT trigger_key FROM review_run").fetchone()
    assert row[0] == trigger.key
    # only the review prompt was used: no thread re-evaluation tool
    assert cmd.env.llm.calls[0].tool_names[-1] == "submit_review"


async def test_when_every_thread_was_fixed_a_new_review_follows(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", True), ("T2", True))), reply(submit_review([finding("b.py", 2)]))],
        threads=[thread_node("T1"), thread_node("T2")],
    )
    await cmd.handler.run(cmd.trigger())
    assert cmd.resolved_ids == ["T1", "T2"]
    assert cmd.env.review_route.call_count == 1
    assert cmd.env.comment_route.call_count == 0
    assert [c.tool_names[-1] for c in cmd.env.llm.calls] == ["submit_verdicts", "submit_review"]


async def test_with_pending_threads_only_a_status_comment_is_posted(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    kept = thread_node("T2")
    kept["path"], kept["line"] = "src/a.py", 12
    kept["comments"]["nodes"][0]["body"] = "**média · complexidade**\n\nExtract this branch."
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", True), ("T2", False), ("T3", False)))],
        threads=[thread_node("T1"), kept, thread_node("T3")],
    )
    await cmd.handler.run(cmd.trigger())

    assert cmd.env.review_route.call_count == 0
    assert cmd.env.comment_route.call_count == 1
    body = json.loads(cmd.env.comment_route.calls.last.request.content)["body"]
    assert body.startswith("## Status do Farejador")
    assert "Resolvidos: 1 · Ainda pendentes: 2" in body
    assert "- `src/a.py:12` — Extract this branch." in body
    assert "mencione `@farejador` de novo para uma nova revisão" in body
    assert len(cmd.env.llm.calls) == 1  # no review conversation was started


async def test_threads_left_open_on_purpose_count_as_pending(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", False)))],
        threads=[thread_node("T1")],
    )
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 0
    body = json.loads(cmd.env.comment_route.calls.last.request.content)["body"]
    assert "Ainda pendentes: 1" in body


async def test_a_review_triggered_by_a_command_works_even_if_the_pr_was_reviewed_before(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [reply(submit_review())])
    earlier = cmd.env.trigger()
    cmd.env.store.record_run(
        earlier.key, steps=1, tokens=1, duration_s=0.1, findings=0, outcome=Outcome.DONE
    )
    cmd.env.store.mark(earlier.key, TriggerStatus.DONE)  # the first review is finished
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 1


async def test_a_failure_in_the_new_review_posts_one_notice_and_reraises(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    import pytest

    from farejador.agent.llm import ModelApiError

    cmd = build_cmd_env(tmp_path, respx_mock, [ModelApiError("boom")])
    with pytest.raises(ModelApiError):
        await cmd.handler.run(cmd.trigger())
    assert cmd.env.comment_route.call_count == 1
    assert cmd.env.review_route.call_count == 0


async def test_two_commands_on_the_same_pull_request_run_one_after_the_other(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    import asyncio

    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(submit_review([finding("b.py", 2)])), reply(_verdicts(("T1", False)))],
        threads=[],
    )
    first, second = cmd.trigger(10), cmd.trigger(11)

    async def register_thread_after_first_review(_number: int) -> None:
        return None

    # when the first command finishes, its review has "created" a bot thread
    original = cmd.env.client.create_review

    async def create_review(*args: object, **kwargs: object) -> int:
        result = await original(*args, **kwargs)  # type: ignore[arg-type]
        cmd.threads.append(thread_node("T1"))
        return result

    cmd.env.client.create_review = create_review  # type: ignore[method-assign]
    await asyncio.gather(cmd.handler.run(first), cmd.handler.run(second))

    # the second command saw the thread created by the first and only posted a status
    assert cmd.env.review_route.call_count == 1
    assert cmd.env.comment_route.call_count == 1
    assert [c.tool_names[-1] for c in cmd.env.llm.calls] == ["submit_review", "submit_verdicts"]
