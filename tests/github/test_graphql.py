# Filename: test_graphql.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import httpx
import pytest
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.client import GitHubClient
from farejador.github.errors import GitHubApiError

URL = "https://api.github.com/graphql"


def _page(nodes: list[dict[str, object]], *, has_next: bool, cursor: str | None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                            "nodes": nodes,
                        }
                    }
                }
            }
        },
    )


def _node(thread_id: str, *, resolved: bool = False) -> dict[str, object]:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "path": "a.py",
        "line": 4,
        "comments": {"nodes": [{"body": "smell", "author": {"login": "farejador[bot]"}}]},
    }


def _client() -> GitHubClient:
    return GitHubClient(FakeAuth(), sleep=SleepRecorder())


async def test_list_review_threads_paginates(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(URL).mock(
        side_effect=[
            _page([_node("T1")], has_next=True, cursor="c1"),
            _page([_node("T2", resolved=True)], has_next=False, cursor=None),
        ]
    )
    threads = await _client().list_review_threads(7, "o/r", 5)
    assert [(t.id, t.is_resolved, t.author_login, t.body) for t in threads] == [
        ("T1", False, "farejador[bot]", "smell"),
        ("T2", True, "farejador[bot]", "smell"),
    ]
    first = json.loads(route.calls[0].request.content)["variables"]
    second = json.loads(route.calls[1].request.content)["variables"]
    assert first == {"owner": "o", "name": "r", "number": 5, "after": None}
    assert second["after"] == "c1"


async def test_thread_without_comments_is_tolerated(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(
        return_value=_page(
            [
                {
                    "id": "T9",
                    "isResolved": False,
                    "path": None,
                    "line": None,
                    "comments": {"nodes": []},
                }
            ],
            has_next=False,
            cursor=None,
        )
    )
    (thread,) = await _client().list_review_threads(7, "o/r", 5)
    assert (thread.path, thread.line, thread.author_login, thread.body) == (None, None, "", "")


async def test_resolve_review_thread_sends_the_mutation(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"resolveReviewThread": {"thread": {"id": "T1", "isResolved": True}}}},
        )
    )
    await _client().resolve_review_thread(7, "T1")
    body = json.loads(route.calls.last.request.content)
    assert "resolveReviewThread" in body["query"]
    assert body["variables"] == {"threadId": "T1"}


async def test_graphql_errors_become_api_errors(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "Could not resolve"}]})
    )
    with pytest.raises(GitHubApiError, match="Could not resolve"):
        await _client().resolve_review_thread(7, "T1")
