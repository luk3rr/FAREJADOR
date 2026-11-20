# Filename: test_client_read.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import httpx
import pytest
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.client import GitHubClient
from farejador.github.errors import GitHubApiError

API = "https://api.github.com"


def _client() -> GitHubClient:
    return GitHubClient(FakeAuth(), sleep=SleepRecorder())


def _pr(number: int, *, draft: bool = False) -> dict[str, object]:
    return {
        "number": number,
        "title": f"PR {number}",
        "draft": draft,
        "state": "open",
        "head": {"sha": f"sha{number}"},
        "user": {"login": "alice"},
        "html_url": f"https://github.com/o/r/pull/{number}",
    }


async def test_list_installations_follows_pagination(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/app/installations", params={"per_page": "100"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "account": {"login": "a"}}],
            headers={"Link": f'<{API}/app/installations?page=2>; rel="next"'},
        )
    )
    respx_mock.get(f"{API}/app/installations", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"id": 2, "account": {"login": "b"}}])
    )
    installations = await _client().list_installations()
    assert [(i.id, i.account_login) for i in installations] == [(1, "a"), (2, "b")]


async def test_list_installation_repos(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/installation/repositories").mock(
        return_value=httpx.Response(
            200, json={"repositories": [{"full_name": "o/r"}, {"full_name": "o/s"}]}
        )
    )
    assert await _client().list_installation_repos(7) == ["o/r", "o/s"]


async def test_list_open_prs_returns_etag_and_all_pages(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/repos/o/r/pulls", params={"state": "open", "per_page": "100"}).mock(
        return_value=httpx.Response(
            200,
            json=[_pr(1)],
            headers={"ETag": 'W/"abc"', "Link": f'<{API}/repos/o/r/pulls?page=2>; rel="next"'},
        )
    )
    respx_mock.get(f"{API}/repos/o/r/pulls", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[_pr(2, draft=True)])
    )
    result = await _client().list_open_prs(7, "o/r")
    assert result.etag == 'W/"abc"'
    assert result.not_modified is False
    assert result.data is not None
    assert [(p.number, p.draft, p.head_sha) for p in result.data] == [
        (1, False, "sha1"),
        (2, True, "sha2"),
    ]


async def test_list_open_prs_sends_etag_and_handles_304(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/repos/o/r/pulls").mock(return_value=httpx.Response(304))
    result = await _client().list_open_prs(7, "o/r", etag='W/"abc"')
    assert result.not_modified is True
    assert result.data is None
    assert result.etag == 'W/"abc"'
    assert route.calls.last.request.headers["If-None-Match"] == 'W/"abc"'


async def test_get_pr_and_diff(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/repos/o/r/pulls/5").mock(
        side_effect=[httpx.Response(200, json=_pr(5)), httpx.Response(200, text="diff --git a b\n")]
    )
    client = _client()
    pr = await client.get_pr(7, "o/r", 5)
    assert pr.title == "PR 5"
    assert await client.get_diff(7, "o/r", 5) == "diff --git a b\n"
    assert route.calls.last.request.headers["Accept"] == "application/vnd.github.diff"
    assert route.calls[0].request.headers["X-GitHub-Api-Version"] == "2022-11-28"


async def test_list_issue_comments_with_since_etag_and_304(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/repos/o/r/issues/5/comments").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {
                        "id": 11,
                        "body": "@farejador please",
                        "user": {"login": "alice"},
                        "created_at": "2026-11-20T10:00:00Z",
                        "updated_at": "2026-11-20T10:00:00Z",
                    }
                ],
                headers={"ETag": '"c1"'},
            ),
            httpx.Response(304),
        ]
    )
    client = _client()
    first = await client.list_issue_comments(7, "o/r", 5, since="2026-11-20T09:00:00Z")
    assert first.data is not None
    assert (first.data[0].id, first.data[0].author_login) == (11, "alice")
    assert first.etag == '"c1"'
    assert route.calls[0].request.url.params["since"] == "2026-11-20T09:00:00Z"
    second = await client.list_issue_comments(7, "o/r", 5, etag='"c1"')
    assert second.not_modified is True


async def test_list_issue_comments_follows_pagination(respx_mock: respx.MockRouter) -> None:
    def comment(identifier: int) -> dict[str, object]:
        return {"id": identifier, "body": "x", "user": {"login": "alice"}}

    respx_mock.get(f"{API}/repos/o/r/issues/5/comments", params={"per_page": "100"}).mock(
        return_value=httpx.Response(
            200,
            json=[comment(1)],
            headers={"Link": f'<{API}/repos/o/r/issues/5/comments?page=2>; rel="next"'},
        )
    )
    respx_mock.get(f"{API}/repos/o/r/issues/5/comments", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[comment(2)])
    )
    result = await _client().list_issue_comments(7, "o/r", 5)
    assert result.data is not None
    assert [c.id for c in result.data] == [1, 2]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"role_name": "maintain", "permission": "write"}, True),
        ({"role_name": "admin", "permission": "admin"}, True),
        ({"permission": "write"}, True),
        ({"role_name": "read", "permission": "read"}, False),
        ({"permission": "none"}, False),
    ],
)
async def test_can_write_by_role(
    respx_mock: respx.MockRouter, body: dict[str, str], expected: bool
) -> None:
    respx_mock.get(f"{API}/repos/o/r/collaborators/alice/permission").mock(
        return_value=httpx.Response(200, json=body)
    )
    assert await _client().can_write(7, "o/r", "alice") is expected


async def test_can_write_is_false_when_user_is_not_a_collaborator(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(f"{API}/repos/o/r/collaborators/eve/permission").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    assert await _client().can_write(7, "o/r", "eve") is False


async def test_can_write_propagates_other_errors(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/repos/o/r/collaborators/eve/permission").mock(
        return_value=httpx.Response(403, json={"message": "forbidden"})
    )
    with pytest.raises(GitHubApiError):
        await _client().can_write(7, "o/r", "eve")
