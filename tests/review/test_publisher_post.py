# Filename: test_publisher_post.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import httpx
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.client import GitHubClient
from farejador.github.models import ReviewComment
from farejador.review.publisher import Publisher, ReviewPayload

API = "https://api.github.com"


def _publisher() -> Publisher:
    return Publisher(GitHubClient(FakeAuth(), sleep=SleepRecorder()))


async def test_post_review_sends_the_commit_body_and_inline_comments(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post(f"{API}/repos/o/r/pulls/3/reviews").mock(
        return_value=httpx.Response(200, json={"id": 5})
    )
    payload = ReviewPayload("body", [ReviewComment(path="a.py", line=4, body="smell")])
    review_id = await _publisher().post_review(9, "o/r", 3, commit_sha="abc123", payload=payload)
    assert review_id == 5
    sent = json.loads(route.calls.last.request.content)
    assert sent["commit_id"] == "abc123"
    assert sent["body"] == "body"
    assert sent["comments"] == [{"path": "a.py", "line": 4, "side": "RIGHT", "body": "smell"}]


async def test_post_comment_goes_through_the_issues_api(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{API}/repos/o/r/issues/3/comments").mock(
        return_value=httpx.Response(201, json={"id": 6})
    )
    assert await _publisher().post_comment(9, "o/r", 3, "status") == 6
    assert json.loads(route.calls.last.request.content) == {"body": "status"}


async def test_post_notice_posts_once_and_reports_success(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{API}/repos/o/r/issues/3/comments").mock(
        return_value=httpx.Response(201, json={"id": 6})
    )
    ok = await _publisher().post_notice(
        9, "o/r", 3, commit_sha="abcdef123", trigger_text="@farejador"
    )
    assert ok is True
    assert route.call_count == 1
    assert (
        "não conseguiu concluir a revisão automática"
        in json.loads(route.calls.last.request.content)["body"]
    )


async def test_post_notice_never_raises_when_github_is_down(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{API}/repos/o/r/issues/3/comments").mock(
        return_value=httpx.Response(403, json={"message": "no"})
    )
    ok = await _publisher().post_notice(9, "o/r", 3, commit_sha="abc", trigger_text="@farejador")
    assert ok is False
