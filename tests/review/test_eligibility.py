# Filename: test_eligibility.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import httpx
import pytest
import respx
from tests.llm_fakes import call, finding, reply, submit_review
from tests.pipeline_env import API, REPO, build_env, pr_json

from farejador.dispatcher import Dispatcher, SubmitResult, TriggerSkipped
from farejador.models import TriggerKind
from farejador.state.store import Outcome, TriggerStatus


async def test_draft_pull_requests_are_skipped_without_touching_the_diff(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [], draft=True)
    with pytest.raises(TriggerSkipped, match="draft"):
        await env.pipeline.run(env.trigger())
    assert env.diff_route.call_count == 0
    assert env.review_route.call_count == 0
    assert env.llm.calls == []


async def test_closed_pull_requests_are_skipped(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [], state="closed")
    with pytest.raises(TriggerSkipped, match="closed"):
        await env.pipeline.run(env.trigger())
    assert env.review_route.call_count == 0


async def test_a_pull_request_that_was_already_reviewed_is_skipped(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [])
    earlier = env.trigger()
    env.store.record_run(
        earlier.key, steps=1, tokens=1, duration_s=0.1, findings=0, outcome=Outcome.DONE
    )
    with pytest.raises(TriggerSkipped, match="already-reviewed"):
        await env.pipeline.run(earlier)
    assert env.review_route.call_count == 0


async def test_a_failed_earlier_attempt_does_not_count_as_reviewed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [reply(submit_review([finding("b.py", 2)]))])
    trigger = env.trigger()
    env.store.record_run(
        trigger.key, steps=0, tokens=0, duration_s=0.1, findings=0, outcome=Outcome.FAILED_MODEL
    )
    await env.pipeline.run(trigger)
    assert env.review_route.call_count == 1


async def test_a_draft_is_reviewed_once_it_becomes_ready_and_later_pushes_are_ignored(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(call("list_dir", {}, "c1")), reply(submit_review([finding("b.py", 2)]))],
    )
    sha = env.sha
    env.pr_route.mock(
        side_effect=[
            httpx.Response(200, json=pr_json(sha, draft=True)),
            httpx.Response(200, json=pr_json(sha, draft=False)),
            httpx.Response(200, json=pr_json("f" * 40, draft=False)),
        ]
    )
    dispatcher = Dispatcher(env.store, {TriggerKind.FIRST_REVIEW: env.pipeline.run}, workers=1)
    await dispatcher.start()
    from tests.factories import make_first

    trigger = make_first(1, repo=REPO)

    # 1. opened as a draft: nothing is posted and the key is released
    assert await dispatcher.submit(trigger) is SubmitResult.ENQUEUED
    await dispatcher.stop()
    record = env.store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.SKIPPED, "draft")
    assert env.review_route.call_count == 0

    # 2. ready_for_review: the same key is claimed again and the review is posted
    await dispatcher.start()
    assert await dispatcher.submit(trigger) is SubmitResult.ENQUEUED
    await dispatcher.stop()
    assert env.review_route.call_count == 1
    done = env.store.get_trigger(trigger.key)
    assert done is not None
    assert done.status is TriggerStatus.DONE

    # 3. a new push produces nothing: the key is done, so the trigger is a duplicate
    await dispatcher.start()
    assert await dispatcher.submit(trigger) is SubmitResult.DUPLICATE
    await dispatcher.stop()
    assert env.review_route.call_count == 1
    assert env.pr_route.call_count == 2
    assert API in str(env.pr_route.calls.last.request.url)
