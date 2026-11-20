# Filename: test_bot_login.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import httpx
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.client import GitHubClient, resolve_bot_login


def _client() -> GitHubClient:
    return GitHubClient(FakeAuth(), sleep=SleepRecorder())


async def test_bot_login_is_derived_from_the_app_slug(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://api.github.com/app").mock(
        return_value=httpx.Response(200, json={"slug": "farejador"})
    )
    assert await resolve_bot_login(_client()) == "farejador[bot]"
    assert route.calls.last.request.headers["Authorization"] == "Bearer app-jwt"


async def test_override_skips_the_network(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://api.github.com/app").mock(return_value=httpx.Response(500))
    assert await resolve_bot_login(_client(), "custom[bot]") == "custom[bot]"
    assert route.call_count == 0
