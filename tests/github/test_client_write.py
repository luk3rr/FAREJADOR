# Filename: test_client_write.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import httpx
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.client import GitHubClient
from farejador.github.models import ReviewComment

API = "https://api.github.com"


async def test_create_review_sends_inline_comments_as_a_comment_review(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post(f"{API}/repos/o/r/pulls/5/reviews").mock(
        return_value=httpx.Response(200, json={"id": 777})
    )
    client = GitHubClient(FakeAuth(), sleep=SleepRecorder())
    review_id = await client.create_review(
        7,
        "o/r",
        5,
        commit_id="abc123",
        body="summary",
        comments=[ReviewComment(path="a.py", line=12, body="smell")],
    )
    assert review_id == 777
    payload = json.loads(route.calls.last.request.content)
    assert payload == {
        "commit_id": "abc123",
        "event": "COMMENT",
        "body": "summary",
        "comments": [{"path": "a.py", "line": 12, "side": "RIGHT", "body": "smell"}],
    }


async def test_post_comment_uses_the_issues_api(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{API}/repos/o/r/issues/5/comments").mock(
        return_value=httpx.Response(201, json={"id": 31})
    )
    client = GitHubClient(FakeAuth(), sleep=SleepRecorder())
    assert await client.post_comment(7, "o/r", 5, "status") == 31
    assert json.loads(route.calls.last.request.content) == {"body": "status"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer token-7-v1"
