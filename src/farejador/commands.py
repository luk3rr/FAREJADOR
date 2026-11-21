# Filename: commands.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The ``command`` use case: re-evaluate open threads, then maybe review again (FR-16..FR-18)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from functools import partial

from farejador.agent.runner import AgentRunner
from farejador.agent.schemas import OpenThread
from farejador.dispatcher import TriggerSkipped
from farejador.github.client import GitHubClient
from farejador.github.errors import AuthError, GitHubApiError
from farejador.github.models import ReviewThread, same_login
from farejador.models import Trigger
from farejador.review.pipeline import (
    FirstReview,
    PipelineConfig,
    TokenProvider,
    WorkspaceOpener,
    finish_failed,
    is_public,
)
from farejador.review.publisher import PendingThread, Publisher
from farejador.state.store import StateStore, ThreadStatus, TriggerStatus
from farejador.trace.recorder import NULL_RUN, NullRecorder, Recorder, RunTrace
from farejador.trace.store import RunOutcome

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles a comment that mentions Farejador, only for users with write access."""

    def __init__(
        self,
        *,
        client: GitHubClient,
        token_for: TokenProvider,
        store: StateStore,
        runner: AgentRunner,
        publisher: Publisher,
        open_workspace: WorkspaceOpener,
        review: FirstReview,
        config: PipelineConfig | None = None,
        recorder: Recorder | None = None,
    ) -> None:
        self._client = client
        self._token_for = token_for
        self._store = store
        self._runner = runner
        self._publisher = publisher
        self._open_workspace = open_workspace
        self._review = review
        self._recorder: Recorder = recorder or NullRecorder()
        self._config = config or PipelineConfig()
        self._locks: defaultdict[tuple[str, int], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def run(self, trigger: Trigger) -> None:
        """Handle a ``command`` trigger; one command at a time per pull request."""
        async with self._locks[(trigger.repo, trigger.pr_number)]:
            await self._handle(trigger)

    # -- steps -----------------------------------------------------------------------------

    async def _handle(self, trigger: Trigger) -> None:
        installation, repo = trigger.installation_id, trigger.repo
        started = time.monotonic()

        if not await self._client.can_write(installation, repo, trigger.sender_login):
            logger.info(
                "command ignored: user has no write access",
                extra={"repo": repo, "pr": trigger.pr_number, "user": trigger.sender_login},
            )
            return

        pr = await self._client.get_pr(installation, repo, trigger.pr_number)
        if pr.state != "open":
            raise TriggerSkipped("closed")
        if await self._first_review_in_flight(trigger):
            logger.info(
                "command ignored: the first review is still running",
                extra={"repo": repo, "pr": trigger.pr_number},
            )
            return

        await self._publisher.acknowledge(installation, repo, pr.number)
        trace: RunTrace = NULL_RUN
        try:
            open_threads = await self._open_bot_threads(trigger)
            resolved = 0
            pending = open_threads
            if open_threads:
                trace = self._recorder.begin(
                    trigger_key=trigger.key,
                    kind="command",
                    repo=repo,
                    pr_number=pr.number,
                    head_sha=pr.head_sha,
                    repo_public=is_public(pr),
                )
                resolved, pending = await self._reevaluate(
                    trigger, pr.head_sha, open_threads, trace
                )
        except Exception as exc:
            finish_failed(trace, exc, started)
            await self._review.report_failure(trigger, pr.head_sha, exc, started)
            raise

        if pending:
            body = self._publisher.format_status(
                resolved=resolved,
                pending=[PendingThread(t.path, t.line, t.body) for t in pending],
                trigger_text=self._config.trigger_text,
            )
            await self._publisher.post_comment(installation, repo, trigger.pr_number, body)
            return
        await self._review.review_now(trigger)

    async def _first_review_in_flight(self, trigger: Trigger) -> bool:
        first_key = f"first:{trigger.repo}#{trigger.pr_number}"
        record = await asyncio.to_thread(self._store.get_trigger, first_key)
        return record is not None and record.status in (
            TriggerStatus.CLAIMED,
            TriggerStatus.RUNNING,
        )

    async def _open_bot_threads(self, trigger: Trigger) -> list[ReviewThread]:
        """Open threads created by the bot; GitHub is the source of truth, the store follows."""
        installation, repo, number = trigger.installation_id, trigger.repo, trigger.pr_number
        threads = await self._client.list_review_threads(installation, repo, number)
        stored = {
            thread.thread_id: thread
            for thread in await asyncio.to_thread(self._store.list_threads, repo, number)
        }
        bot = self._config.bot_login or ""

        open_threads: list[ReviewThread] = []
        for thread in threads:
            is_bot = same_login(thread.author_login, bot) if bot else thread.id in stored
            if not is_bot:
                continue
            if thread.is_resolved:
                if thread.id in stored and stored[thread.id].status is ThreadStatus.OPEN:
                    await asyncio.to_thread(
                        self._store.set_thread_status, thread.id, ThreadStatus.RESOLVED
                    )
                continue
            if thread.id not in stored:
                await asyncio.to_thread(
                    partial(
                        self._store.add_thread,
                        thread.id,
                        run_id=None,
                        repo=repo,
                        pr_number=number,
                        path=thread.path,
                        line=thread.line,
                    )
                )
            open_threads.append(thread)
        return open_threads

    async def _reevaluate(
        self,
        trigger: Trigger,
        head_sha: str,
        open_threads: list[ReviewThread],
        trace: RunTrace = NULL_RUN,
    ) -> tuple[int, list[ReviewThread]]:
        """Ask the agent about each open thread and resolve those that were fixed."""
        token = await self._token_for(trigger.installation_id)
        async with self._open_workspace(trigger.repo, head_sha, token) as workspace:
            run = await self._runner.reevaluate(
                threads=[
                    OpenThread(thread_id=t.id, path=t.path, line=t.line, body=t.body)
                    for t in open_threads
                ],
                tools=workspace.tools,
                trace=trace,
            )
        trace.finish(
            outcome=RunOutcome.PARTIAL if run.partial else RunOutcome.COMPLETE,
            steps=run.steps,
            tokens=run.tokens,
            duration_s=run.duration_s,
            error_category="budget" if run.partial else None,
            error_message=run.note,
        )

        resolved = 0
        pending: list[ReviewThread] = []
        for thread in open_threads:
            verdict = run.verdicts.get(thread.id)
            if verdict is None or not verdict.fixed:
                pending.append(thread)
                continue
            try:
                await self._client.resolve_review_thread(trigger.installation_id, thread.id)
            except (GitHubApiError, AuthError):
                logger.warning("could not resolve a thread", extra={"thread_id": thread.id})
                pending.append(thread)
                continue
            await asyncio.to_thread(self._store.set_thread_status, thread.id, ThreadStatus.RESOLVED)
            resolved += 1
        return resolved, pending
