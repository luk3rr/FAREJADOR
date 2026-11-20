# Filename: test_failure_path.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json
from pathlib import Path

import httpx
import pytest
import respx
from tests.llm_fakes import call, reply
from tests.pipeline_env import REPO, build_env

from farejador.agent.llm import ModelApiError
from farejador.agent.runner import InvalidModelOutput
from farejador.dispatcher import Dispatcher
from farejador.github.errors import AuthError, GitHubApiError
from farejador.models import TriggerKind
from farejador.review.pipeline import failure_outcome
from farejador.state.store import Outcome, TriggerStatus
from farejador.workspace import WorkspaceError


def _outcomes(env: object) -> list[str]:
    rows = env.store._db().execute("SELECT outcome FROM review_run").fetchall()  # type: ignore[attr-defined]
    return [row[0] for row in rows]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (ModelApiError("x"), Outcome.FAILED_MODEL),
        (InvalidModelOutput("x"), Outcome.FAILED_MODEL),
        (GitHubApiError(500, "x"), Outcome.FAILED_GITHUB),
        (AuthError("x"), Outcome.FAILED_GITHUB),
        (WorkspaceError("x"), Outcome.FAILED_INTERNAL),
        (RuntimeError("x"), Outcome.FAILED_INTERNAL),
    ],
)
def test_exceptions_map_to_outcomes(error: Exception, outcome: Outcome) -> None:
    assert failure_outcome(error) is outcome


async def test_a_model_failure_records_the_run_posts_one_notice_and_reraises(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [ModelApiError("model API returned HTTP 500")])
    trigger = env.trigger()
    with pytest.raises(ModelApiError):
        await env.pipeline.run(trigger)

    assert _outcomes(env) == ["failed_model"]
    assert env.review_route.call_count == 0
    assert env.comment_route.call_count == 1
    notice = json.loads(env.comment_route.calls.last.request.content)["body"]
    assert "não conseguiu concluir a revisão automática" in notice
    assert env.sha[:7] in notice
    assert "HTTP 500" not in notice
    assert env.store.has_review_run("o/r", 1) is False


async def test_repeated_invalid_output_is_a_model_failure(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [reply(), reply(), reply()])
    with pytest.raises(InvalidModelOutput):
        await env.pipeline.run(env.trigger())
    assert _outcomes(env) == ["failed_model"]
    assert env.comment_route.call_count == 1


async def test_a_github_failure_while_reading_the_diff_is_recorded_as_github(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [])
    env.diff_route.mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(GitHubApiError):
        await env.pipeline.run(env.trigger())
    assert _outcomes(env) == ["failed_github"]
    assert env.comment_route.call_count == 1


async def test_a_workspace_failure_is_internal(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [])
    # a removed remote makes the checkout fail
    import shutil

    shutil.rmtree(env.remote)
    with pytest.raises(WorkspaceError):
        await env.pipeline.run(env.trigger())
    assert _outcomes(env) == ["failed_internal"]


async def test_if_the_notice_cannot_be_posted_the_original_error_still_surfaces(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [ModelApiError("boom")])
    env.comment_route.mock(return_value=httpx.Response(500, json={"message": "down"}))
    with pytest.raises(ModelApiError):
        await env.pipeline.run(env.trigger())
    assert _outcomes(env) == ["failed_model"]


async def test_the_dispatcher_marks_the_trigger_failed_and_never_repeats_it(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [ModelApiError("boom"), reply(call("list_dir", {}))])
    from tests.factories import make_first

    trigger = make_first(1, repo=REPO)
    dispatcher = Dispatcher(env.store, {TriggerKind.FIRST_REVIEW: env.pipeline.run}, workers=1)
    await dispatcher.start()
    await dispatcher.submit(trigger)
    await dispatcher.stop()

    record = env.store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.FAILED, "ModelApiError")
    assert env.comment_route.call_count == 1

    await dispatcher.start()
    from farejador.dispatcher import SubmitResult

    assert await dispatcher.submit(trigger) is SubmitResult.DUPLICATE
    await dispatcher.stop()
    assert env.comment_route.call_count == 1
    assert len(env.llm.calls) == 1
