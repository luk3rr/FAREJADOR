# Filename: test_authorization.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import httpx
import pytest
import respx
from tests.command_env import PERMISSION_URL, build_cmd_env
from tests.llm_fakes import reply, submit_review

from farejador.dispatcher import TriggerSkipped
from farejador.github.errors import GitHubApiError
from farejador.models import Trigger, TriggerSource
from farejador.state.store import TriggerStatus


@pytest.mark.parametrize("role", ["write", "maintain", "admin"])
async def test_users_with_write_access_can_run_commands(
    tmp_path: Path, respx_mock: respx.MockRouter, role: str
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [reply(submit_review())], role=role)
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 1


@pytest.mark.parametrize("role", ["read", "triage", "none"])
async def test_users_without_write_access_get_no_response_at_all(
    tmp_path: Path, respx_mock: respx.MockRouter, role: str
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [], role=role)
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 0
    assert cmd.env.comment_route.call_count == 0
    assert cmd.env.pr_route.call_count == 0
    assert cmd.env.llm.calls == []


async def test_a_user_who_is_not_a_collaborator_is_ignored(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [])
    cmd.permission_route.mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 0
    assert cmd.env.comment_route.call_count == 0


async def test_an_error_checking_permissions_is_a_normal_failure(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [])
    cmd.permission_route.mock(return_value=httpx.Response(403, json={"message": "forbidden"}))
    with pytest.raises(GitHubApiError):
        await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 0


async def test_a_closed_pull_request_is_skipped(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [], state="closed")
    with pytest.raises(TriggerSkipped, match="closed"):
        await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 0


async def test_draft_pull_requests_accept_commands(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [reply(submit_review())], draft=True)
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 1


async def test_a_command_while_the_first_review_is_running_is_dropped(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [])
    first = Trigger.first_review(
        repo="o/r", installation_id=99, pr_number=1, sender_login="alice",
        source=TriggerSource.POLLING,
    )  # fmt: skip
    cmd.env.store.try_claim(first)
    cmd.env.store.mark(first.key, TriggerStatus.RUNNING)
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 0
    assert cmd.env.comment_route.call_count == 0
    assert cmd.env.llm.calls == []
    assert cmd.permission_route.calls.last.request.url.path == PERMISSION_URL.removeprefix(
        "https://api.github.com"
    )


async def test_a_finished_first_review_does_not_block_commands(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [reply(submit_review())])
    first = Trigger.first_review(
        repo="o/r", installation_id=99, pr_number=1, sender_login="alice",
        source=TriggerSource.POLLING,
    )  # fmt: skip
    cmd.env.store.try_claim(first)
    cmd.env.store.mark(first.key, TriggerStatus.DONE)
    await cmd.handler.run(cmd.trigger())
    assert cmd.env.review_route.call_count == 1
