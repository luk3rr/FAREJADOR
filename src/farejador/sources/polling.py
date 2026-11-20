# Filename: polling.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Polling source for local use without a public endpoint (FR-2, NFR-9, ADR-5).

Each cycle lists the repositories where the App is installed, their open pull requests and the
new comments, and turns them into the same triggers the webhook source produces. Conditional
requests (ETag) keep unchanged resources free of rate limit.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from farejador.dispatcher import SubmitResult
from farejador.github.client import GitHubClient
from farejador.github.errors import AuthError, GitHubApiError
from farejador.github.models import IssueComment, PullRequest
from farejador.models import Trigger, TriggerSource
from farejador.state.store import StateStore, TriggerStatus

logger = logging.getLogger(__name__)

Submit = Callable[[Trigger], Awaitable[SubmitResult]]


@dataclass(slots=True)
class PollStats:
    """What one polling cycle did; used in logs and tests."""

    repos: int = 0
    open_prs: int = 0
    first_reviews: int = 0
    commands: int = 0
    not_modified: int = 0
    errors: int = 0


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class PollingSource:
    """Turns periodic GitHub reads into triggers for the dispatcher."""

    def __init__(
        self,
        *,
        client: GitHubClient,
        store: StateStore,
        submit: Submit,
        trigger_text: str = "@farejador",
        bot_login: str | None = None,
        interval_s: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self._client = client
        self._store = store
        self._submit = submit
        self._trigger_text = trigger_text.lower()
        self._bot_login = bot_login.lower() if bot_login else None
        self._interval = interval_s
        self._sleep = sleep
        self._started_at = now()
        self._pr_cache: dict[str, tuple[str | None, list[PullRequest]]] = {}

    # -- loop ------------------------------------------------------------------------------

    async def run(self) -> None:
        """Poll forever; transient errors are logged and the next cycle tries again."""
        while True:
            try:
                stats = await self.poll_once()
                logger.info("poll cycle finished", extra=_as_fields(stats))
            except Exception:
                logger.exception("poll cycle failed")
            await self._sleep(self._interval)

    async def poll_once(self) -> PollStats:
        stats = PollStats()
        for installation in await self._client.list_installations():
            try:
                repos = await self._client.list_installation_repos(installation.id)
            except (GitHubApiError, AuthError):
                stats.errors += 1
                logger.warning(
                    "could not list repositories", extra={"installation": installation.id}
                )
                continue
            for repo in repos:
                stats.repos += 1
                try:
                    await self._poll_repo(installation.id, repo, stats)
                except (GitHubApiError, AuthError):
                    stats.errors += 1
                    logger.warning("could not poll repository", extra={"repo": repo})
        return stats

    # -- one repository -------------------------------------------------------------------

    async def _poll_repo(self, installation_id: int, repo: str, stats: PollStats) -> None:
        cached_etag, cached_prs = self._pr_cache.get(repo, (None, []))
        fetched = await self._client.list_open_prs(installation_id, repo, etag=cached_etag)
        if fetched.not_modified:
            stats.not_modified += 1
            prs = cached_prs
        else:
            prs = fetched.data or []
            self._pr_cache[repo] = (fetched.etag, prs)
        stats.open_prs += len(prs)

        for pr in prs:
            await self._maybe_first_review(installation_id, repo, pr, stats)
            await self._poll_comments(installation_id, repo, pr, stats)

    async def _maybe_first_review(
        self, installation_id: int, repo: str, pr: PullRequest, stats: PollStats
    ) -> None:
        if pr.draft:
            return
        trigger = Trigger.first_review(
            repo=repo,
            installation_id=installation_id,
            pr_number=pr.number,
            sender_login=pr.author_login,
            source=TriggerSource.POLLING,
            head_sha=pr.head_sha,
        )
        record = await asyncio.to_thread(self._store.get_trigger, trigger.key)
        if record is not None and record.status is not TriggerStatus.SKIPPED:
            return  # already handled (done, failed) or in flight
        if await asyncio.to_thread(self._store.has_review_run, repo, pr.number):
            return
        if await self._submit(trigger) is SubmitResult.ENQUEUED:
            stats.first_reviews += 1

    async def _poll_comments(
        self, installation_id: int, repo: str, pr: PullRequest, stats: PollStats
    ) -> None:
        key = f"comments:{repo}#{pr.number}"
        cursor = await asyncio.to_thread(self._store.get_cursor, key)
        etag, last_seen = cursor if cursor is not None else (None, None)
        since = last_seen or self._started_at

        result = await self._client.list_issue_comments(
            installation_id, repo, pr.number, since=since, etag=etag
        )
        if result.not_modified:
            stats.not_modified += 1
            return

        newest = since
        for comment in sorted(result.data or [], key=lambda item: item.created_at):
            if comment.created_at < since:
                continue  # edited old comment returned by the ``since`` filter
            newest = max(newest, comment.created_at)
            if not self._is_command(comment):
                continue
            trigger = Trigger.command(
                repo=repo,
                installation_id=installation_id,
                pr_number=pr.number,
                comment_id=comment.id,
                sender_login=comment.author_login,
                source=TriggerSource.POLLING,
            )
            if await self._submit(trigger) is SubmitResult.ENQUEUED:
                stats.commands += 1
        await asyncio.to_thread(self._store.set_cursor, key, result.etag, newest)

    def _is_command(self, comment: IssueComment) -> bool:
        if self._bot_login and comment.author_login.lower() == self._bot_login:
            return False
        return self._trigger_text in comment.body.lower()


def _as_fields(stats: PollStats) -> dict[str, int]:
    return {
        "repos": stats.repos,
        "open_prs": stats.open_prs,
        "first_reviews": stats.first_reviews,
        "commands": stats.commands,
        "not_modified": stats.not_modified,
        "errors": stats.errors,
    }
