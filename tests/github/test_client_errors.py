# Filename: test_client_errors.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import httpx
import pytest
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.client import GitHubClient
from farejador.github.errors import AuthError, GitHubApiError

PR_URL = "https://api.github.com/repos/o/r/pulls/1"
PR_JSON = {"number": 1, "head": {"sha": "abc"}, "title": "t", "user": {"login": "alice"}}


def _client(auth: FakeAuth, sleep: SleepRecorder, retries: int = 3) -> GitHubClient:
    return GitHubClient(auth, max_retries=retries, sleep=sleep)


async def test_server_errors_are_retried_with_backoff(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(PR_URL).mock(
        side_effect=[httpx.Response(502), httpx.Response(503), httpx.Response(200, json=PR_JSON)]
    )
    sleep = SleepRecorder()
    pr = await _client(FakeAuth(), sleep).get_pr(1, "o/r", 1)
    assert pr.head_sha == "abc"
    assert route.call_count == 3
    assert sleep.delays == [0.5, 1.0]


async def test_retry_after_header_is_honoured(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(PR_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=PR_JSON),
        ]
    )
    sleep = SleepRecorder()
    await _client(FakeAuth(), sleep).get_pr(1, "o/r", 1)
    assert sleep.delays == [7.0]


async def test_retries_are_bounded(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(PR_URL).mock(return_value=httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(GitHubApiError) as info:
        await _client(FakeAuth(), SleepRecorder(), retries=2).get_pr(1, "o/r", 1)
    assert info.value.status == 500
    assert route.call_count == 3


async def test_client_errors_are_not_retried_and_carry_the_message(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get(PR_URL).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(GitHubApiError, match="Not Found") as info:
        await _client(FakeAuth(), SleepRecorder()).get_pr(1, "o/r", 1)
    assert info.value.status == 404
    assert route.call_count == 1


async def test_non_json_error_body_falls_back_to_reason(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(PR_URL).mock(return_value=httpx.Response(403, text="forbidden"))
    with pytest.raises(GitHubApiError) as info:
        await _client(FakeAuth(), SleepRecorder()).get_pr(1, "o/r", 1)
    assert info.value.status == 403


async def test_401_invalidates_the_token_and_retries_once(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(PR_URL).mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json=PR_JSON)]
    )
    auth = FakeAuth()
    await _client(auth, SleepRecorder()).get_pr(9, "o/r", 1)
    assert auth.invalidated == [9]
    assert route.calls[0].request.headers["Authorization"] == "Bearer token-9-v1"
    assert route.calls[1].request.headers["Authorization"] == "Bearer token-9-v2"


async def test_repeated_401_raises_auth_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(PR_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(AuthError):
        await _client(FakeAuth(), SleepRecorder()).get_pr(9, "o/r", 1)


async def test_app_level_401_raises_auth_error_without_retry(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://api.github.com/app").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthError):
        await _client(FakeAuth(), SleepRecorder()).get_bot_login()
    assert route.call_count == 1
