# Filename: client.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Async GitHub REST and GraphQL client (FR-2, FR-6, FR-15, FR-16, FR-17, NFR-9)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from farejador.github import graphql
from farejador.github.auth import GitHubAuth
from farejador.github.errors import AuthError, GitHubApiError
from farejador.github.models import (
    Installation,
    IssueComment,
    PullRequest,
    ReviewComment,
    ReviewThread,
)

API_VERSION = "2022-11-28"
JSON_ACCEPT = "application/vnd.github+json"
DIFF_ACCEPT = "application/vnd.github.diff"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_WRITE_ROLES = frozenset({"admin", "maintain", "write"})


@dataclass(frozen=True, slots=True)
class Fetched[T]:
    """Result of a conditional read: ``data`` is None when GitHub answered 304."""

    data: T | None
    etag: str | None
    not_modified: bool = False


class GitHubClient:
    """Thin typed wrapper over the GitHub endpoints listed in design.md, contract C-E."""

    def __init__(
        self,
        auth: GitHubAuth,
        *,
        http: httpx.AsyncClient | None = None,
        base_url: str = "https://api.github.com",
        max_retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._auth = auth
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._sleep = sleep

    # -- transport ---------------------------------------------------------

    async def _send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            response = await self._http.request(
                method, url, headers=headers, json=json, params=params
            )
            if response.status_code not in _RETRY_STATUSES or attempt == self._max_retries:
                return response
            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after) if retry_after and retry_after.isdigit() else 0.5 * 2**attempt
            )
            await self._sleep(min(delay, 30.0))
        raise AssertionError("unreachable")  # pragma: no cover

    async def _call(
        self,
        method: str,
        path: str,
        *,
        installation_id: int | None,
        accept: str = JSON_ACCEPT,
        json: Any = None,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
    ) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        for auth_attempt in range(2):
            token = (
                self._auth.app_jwt()
                if installation_id is None
                else await self._auth.token_for(installation_id)
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": accept,
                "X-GitHub-Api-Version": API_VERSION,
            }
            if etag:
                headers["If-None-Match"] = etag
            response = await self._send(method, url, headers, json, params)
            if response.status_code == 401 and auth_attempt == 0 and installation_id is not None:
                self._auth.invalidate(installation_id)
                continue
            break
        if response.status_code == 401:
            raise AuthError("GitHub rejected the credentials (HTTP 401)")
        if response.status_code >= 400:
            raise GitHubApiError(response.status_code, _message(response))
        return response

    async def _paginate(
        self,
        path: str,
        *,
        installation_id: int | None,
        params: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url: str | None = path
        query: dict[str, Any] | None = {"per_page": 100, **(params or {})}
        while url:
            response = await self._call("GET", url, installation_id=installation_id, params=query)
            body = response.json()
            items.extend(body[key] if key else body)
            url = response.links.get("next", {}).get("url")
            query = None
        return items

    async def _all_pages(self, first: httpx.Response, installation_id: int) -> list[dict[str, Any]]:
        """Collect a list endpoint whose first page was already fetched (for ETag reads)."""
        items: list[dict[str, Any]] = list(first.json())
        next_url = first.links.get("next", {}).get("url")
        while next_url:
            page = await self._call("GET", next_url, installation_id=installation_id)
            items.extend(page.json())
            next_url = page.links.get("next", {}).get("url")
        return items

    # -- app level ---------------------------------------------------------

    async def list_installations(self) -> list[Installation]:
        raw = await self._paginate("/app/installations", installation_id=None)
        return [Installation.from_api(item) for item in raw]

    async def get_bot_login(self) -> str:
        """The login GitHub uses for the App's own comments, for example ``slug[bot]``."""
        response = await self._call("GET", "/app", installation_id=None)
        return f"{response.json()['slug']}[bot]"

    # -- reads -------------------------------------------------------------

    async def list_installation_repos(self, installation_id: int) -> list[str]:
        raw = await self._paginate(
            "/installation/repositories", installation_id=installation_id, key="repositories"
        )
        return [str(item["full_name"]) for item in raw]

    async def list_open_prs(
        self, installation_id: int, repo: str, etag: str | None = None
    ) -> Fetched[list[PullRequest]]:
        """Open PRs; the ETag applies to the first page, so 304 means nothing changed."""
        first = await self._call(
            "GET",
            f"/repos/{repo}/pulls",
            installation_id=installation_id,
            params={"state": "open", "per_page": 100},
            etag=etag,
        )
        if first.status_code == 304:
            return Fetched(None, etag, not_modified=True)
        items = await self._all_pages(first, installation_id)
        return Fetched([PullRequest.from_api(item) for item in items], first.headers.get("ETag"))

    async def get_pr(self, installation_id: int, repo: str, number: int) -> PullRequest:
        response = await self._call(
            "GET", f"/repos/{repo}/pulls/{number}", installation_id=installation_id
        )
        return PullRequest.from_api(response.json())

    async def get_diff(self, installation_id: int, repo: str, number: int) -> str:
        response = await self._call(
            "GET",
            f"/repos/{repo}/pulls/{number}",
            installation_id=installation_id,
            accept=DIFF_ACCEPT,
        )
        return response.text

    async def list_issue_comments(
        self,
        installation_id: int,
        repo: str,
        number: int,
        *,
        since: str | None = None,
        etag: str | None = None,
    ) -> Fetched[list[IssueComment]]:
        params: dict[str, Any] = {"per_page": 100}
        if since:
            params["since"] = since
        first = await self._call(
            "GET",
            f"/repos/{repo}/issues/{number}/comments",
            installation_id=installation_id,
            params=params,
            etag=etag,
        )
        if first.status_code == 304:
            return Fetched(None, etag, not_modified=True)
        items = await self._all_pages(first, installation_id)
        return Fetched([IssueComment.from_api(item) for item in items], first.headers.get("ETag"))

    async def get_permission(self, installation_id: int, repo: str, user: str) -> str:
        """The collaborator's role name, such as ``admin``, ``maintain``, ``write`` or ``read``."""
        response = await self._call(
            "GET",
            f"/repos/{repo}/collaborators/{user}/permission",
            installation_id=installation_id,
        )
        data = response.json()
        return str(data.get("role_name") or data.get("permission") or "none")

    async def can_write(self, installation_id: int, repo: str, user: str) -> bool:
        try:
            role = await self.get_permission(installation_id, repo, user)
        except GitHubApiError as exc:
            if exc.status == 404:
                return False
            raise
        return role in _WRITE_ROLES

    # -- writes ------------------------------------------------------------

    async def create_review(
        self,
        installation_id: int,
        repo: str,
        number: int,
        *,
        commit_id: str,
        body: str,
        comments: list[ReviewComment],
    ) -> int:
        """Create a COMMENT review with inline comments and return its id (A19)."""
        response = await self._call(
            "POST",
            f"/repos/{repo}/pulls/{number}/reviews",
            installation_id=installation_id,
            json={
                "commit_id": commit_id,
                "event": "COMMENT",
                "body": body,
                "comments": [comment.to_api() for comment in comments],
            },
        )
        return int(response.json()["id"])

    async def post_comment(self, installation_id: int, repo: str, number: int, body: str) -> int:
        response = await self._call(
            "POST",
            f"/repos/{repo}/issues/{number}/comments",
            installation_id=installation_id,
            json={"body": body},
        )
        return int(response.json()["id"])

    async def add_reaction(self, installation_id: int, repo: str, number: int, content: str) -> int:
        """React to the pull request itself; GitHub answers with the existing one if repeated."""
        response = await self._call(
            "POST",
            f"/repos/{repo}/issues/{number}/reactions",
            installation_id=installation_id,
            json={"content": content},
        )
        return int(response.json()["id"])

    async def delete_reaction(
        self, installation_id: int, repo: str, number: int, reaction_id: int
    ) -> None:
        await self._call(
            "DELETE",
            f"/repos/{repo}/issues/{number}/reactions/{reaction_id}",
            installation_id=installation_id,
        )

    # -- graphql -----------------------------------------------------------

    async def _graphql(
        self, installation_id: int, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._call(
            "POST",
            "/graphql",
            installation_id=installation_id,
            json={"query": query, "variables": variables},
        )
        body = response.json()
        if body.get("errors"):
            messages = "; ".join(str(error.get("message", "")) for error in body["errors"])
            raise GitHubApiError(200, f"GraphQL error: {messages}")
        data: dict[str, Any] = body["data"]
        return data

    async def list_review_threads(
        self, installation_id: int, repo: str, number: int
    ) -> list[ReviewThread]:
        owner, name = repo.split("/", 1)
        threads: list[ReviewThread] = []
        cursor: str | None = None
        while True:
            data = await self._graphql(
                installation_id,
                graphql.LIST_THREADS,
                {"owner": owner, "name": name, "number": number, "after": cursor},
            )
            page = data["repository"]["pullRequest"]["reviewThreads"]
            threads.extend(ReviewThread.from_graphql(node) for node in page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return threads
            cursor = page["pageInfo"]["endCursor"]

    async def resolve_review_thread(self, installation_id: int, thread_id: str) -> None:
        await self._graphql(installation_id, graphql.RESOLVE_THREAD, {"threadId": thread_id})


async def resolve_bot_login(client: GitHubClient, override: str | None = None) -> str:
    """Use the configured login when present, otherwise derive it from ``GET /app``."""
    return override if override else await client.get_bot_login()


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", response.reason_phrase))
    except ValueError:
        return response.reason_phrase
