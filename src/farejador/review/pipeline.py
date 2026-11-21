# Filename: pipeline.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The first-review use case, from trigger to published review (FR-3, FR-15, FR-20)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from functools import partial

from farejador.agent.llm import ModelApiError
from farejador.agent.runner import AgentRunner, InvalidModelOutput, ReviewRun
from farejador.dispatcher import TriggerSkipped
from farejador.github.client import GitHubClient
from farejador.github.errors import AuthError, GitHubApiError
from farejador.github.models import PullRequest, same_login
from farejador.log import log_run
from farejador.models import Trigger
from farejador.review.diff import DiffFile, parse_diff, render_numbered
from farejador.review.filters import Masker, check_ignored, mask
from farejador.review.publisher import Publisher
from farejador.review.validator import (
    DEFAULT_MAX_INLINE,
    AnchorDecision,
    AnchorResult,
    anchor,
)
from farejador.state.store import Outcome, StateStore
from farejador.trace.recorder import NULL_RUN, NullRecorder, Recorder, RunTrace
from farejador.trace.store import Disposition, FindingRecord, RunOutcome
from farejador.workspace import Workspace

logger = logging.getLogger(__name__)

TokenProvider = Callable[[int], Awaitable[str]]
WorkspaceOpener = Callable[[str, str, str], AbstractAsyncContextManager[Workspace]]


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    mode: str = "polling"
    max_files: int = 40
    max_inline: int = DEFAULT_MAX_INLINE
    ignore_globs: Sequence[str] = field(default_factory=tuple)
    trigger_text: str = "@farejador"
    bot_login: str | None = None


def error_category(error: BaseException) -> str:
    """The category of a failure as shown in the trace."""
    if isinstance(error, ModelApiError):
        return "model_api"
    if isinstance(error, InvalidModelOutput):
        return "invalid_output"
    if isinstance(error, GitHubApiError | AuthError):
        return "github_api"
    return "internal"


def is_public(pr: PullRequest) -> bool | None:
    """Whether the repository is public; ``None`` (unknown) is treated as private (FN-3)."""
    return None if pr.repo_private is None else not pr.repo_private


def finish_failed(trace: RunTrace, error: BaseException, started: float) -> None:
    """Close a trace as failed; never raises."""
    try:
        trace.finish(
            outcome=RunOutcome.FAILED,
            steps=0,
            tokens=0,
            duration_s=time.monotonic() - started,
            error_category=error_category(error),
            error_message=str(error)[:500] or type(error).__name__,
        )
    except Exception:
        logger.error("could not close the trace of a failed run")


def finding_records(decisions: Sequence[AnchorDecision]) -> list[FindingRecord]:
    """One trace record per finding the model returned, with its destination and reason."""
    return [
        FindingRecord(
            path=decision.finding.file,
            line=decision.finding.line,
            severity=decision.finding.severity.value,
            category=decision.finding.category.value,
            problem=decision.finding.problem,
            rationale=decision.finding.rationale or "",
            suggestion=decision.finding.suggestion or "",
            suggestion_diff=decision.finding.suggestion_diff,
            diff_dropped=decision.diff_dropped,
            disposition=Disposition(decision.disposition),
            reason=decision.reason,
        )
        for decision in decisions
    ]


def failure_outcome(error: BaseException) -> Outcome:
    """Map an exception to the run outcome recorded in the state store (design.md, C-H)."""
    if isinstance(error, ModelApiError | InvalidModelOutput):
        return Outcome.FAILED_MODEL
    if isinstance(error, GitHubApiError | AuthError):
        return Outcome.FAILED_GITHUB
    return Outcome.FAILED_INTERNAL


class FirstReview:
    """Reviews a pull request once, automatically, and publishes the result."""

    def __init__(
        self,
        *,
        client: GitHubClient,
        token_for: TokenProvider,
        store: StateStore,
        runner: AgentRunner,
        publisher: Publisher,
        open_workspace: WorkspaceOpener,
        config: PipelineConfig | None = None,
        recorder: Recorder | None = None,
    ) -> None:
        self._client = client
        self._token_for = token_for
        self._store = store
        self._runner = runner
        self._publisher = publisher
        self._open_workspace = open_workspace
        self._config = config or PipelineConfig()
        self._recorder: Recorder = recorder or NullRecorder()

    async def run(self, trigger: Trigger) -> None:
        """Handle a ``first_review`` trigger; raise ``TriggerSkipped`` when not applicable."""
        await self._execute(trigger, first_review=True)

    async def review_now(self, trigger: Trigger) -> None:
        """Review the current head on request (a command): no draft or "already reviewed" rule."""
        await self._execute(trigger, first_review=False)

    async def _execute(self, trigger: Trigger, *, first_review: bool) -> None:
        started = time.monotonic()
        sha = trigger.head_sha or ""
        trace: RunTrace = NULL_RUN
        try:
            pr = await self._client.get_pr(trigger.installation_id, trigger.repo, trigger.pr_number)
            sha = pr.head_sha
            await self._check_eligible(trigger, pr, first_review=first_review)
            trace = self._recorder.begin(
                trigger_key=trigger.key,
                kind="review",
                repo=trigger.repo,
                pr_number=pr.number,
                head_sha=pr.head_sha,
                repo_public=is_public(pr),
            )
            eyes = await self._publisher.acknowledge(
                trigger.installation_id, trigger.repo, pr.number
            )
            await self._review(trigger, pr, started, trace, eyes)
        except TriggerSkipped:
            raise
        except Exception as exc:
            finish_failed(trace, exc, started)
            await self.report_failure(trigger, sha, exc, started)
            raise

    # -- steps -----------------------------------------------------------------------------

    async def _check_eligible(
        self, trigger: Trigger, pr: PullRequest, *, first_review: bool
    ) -> None:
        if pr.state != "open":
            raise TriggerSkipped("closed")
        if not first_review:
            return  # an explicit command may review drafts and already reviewed pull requests
        if pr.draft:
            raise TriggerSkipped("draft")
        reviewed = await asyncio.to_thread(
            self._store.has_review_run, trigger.repo, trigger.pr_number
        )
        if reviewed:
            raise TriggerSkipped("already-reviewed")

    def _classify(self, files: list[DiffFile]) -> tuple[list[DiffFile], list[tuple[str, str]]]:
        reviewed: list[DiffFile] = []
        skipped: list[tuple[str, str]] = []
        for diff_file in files:
            decision = check_ignored(diff_file, self._config.ignore_globs)
            if decision.ignored:
                skipped.append((diff_file.path, decision.reason))
            elif not diff_file.added_lines:
                skipped.append((diff_file.path, "no-added-lines"))
            elif len(reviewed) >= self._config.max_files:
                skipped.append((diff_file.path, "file-limit"))
            else:
                reviewed.append(diff_file)
        return reviewed, skipped

    async def _review(
        self,
        trigger: Trigger,
        pr: PullRequest,
        started: float,
        trace: RunTrace,
        received_id: int | None = None,
    ) -> None:
        installation, repo = trigger.installation_id, trigger.repo
        diff_text = await self._client.get_diff(installation, repo, pr.number)
        reviewed, skipped = self._classify(parse_diff(diff_text))

        run: ReviewRun | None = None
        anchored = AnchorResult([], [])
        if reviewed:
            numbered = "\n".join(render_numbered([item], Masker().line) for item in reviewed)
            token = await self._token_for(installation)
            async with self._open_workspace(repo, pr.head_sha, token) as workspace:
                run = await self._runner.review(
                    pr_title=mask(pr.title),
                    numbered_diff=numbered,
                    skipped=skipped,
                    tools=workspace.tools,
                    trace=trace,
                )
            anchored = anchor(
                run.result.findings,
                reviewed,
                ignored_paths=[path for path, _ in skipped],
                max_inline=self._config.max_inline,
            )
            trace.findings(finding_records(anchored.decisions))

        summary = run.result.summary if run else ""
        payload = self._publisher.format_review(
            commit_sha=pr.head_sha,
            summary=summary,
            anchored=anchored,
            skipped=skipped,
            note=run.note if run else None,
        )
        await self._publisher.post_review(
            installation, repo, pr.number, commit_sha=pr.head_sha, payload=payload
        )
        # a complete review that found nothing says so in a comment of its own, then the eyes
        # (received) are swapped for a rocket and a thumbs up
        nothing_found = run is not None and not run.partial and not run.result.findings
        if nothing_found and await self._publisher.post_lgtm(installation, repo, pr.number):
            await self._publisher.celebrate(installation, repo, pr.number, received_id)

        outcome = Outcome.PARTIAL if run and run.partial else Outcome.DONE
        findings = len(anchored.inline) + len(anchored.unanchored)
        duration = time.monotonic() - started
        run_id = await asyncio.to_thread(
            lambda: self._store.record_run(
                trigger.key,
                steps=run.steps if run else 0,
                tokens=run.tokens if run else 0,
                duration_s=duration,
                findings=findings,
                outcome=outcome,
            )
        )
        trace.finish(
            outcome=RunOutcome.PARTIAL if run and run.partial else RunOutcome.COMPLETE,
            steps=run.steps if run else 0,
            tokens=run.tokens if run else 0,
            duration_s=duration,
            error_category="budget" if run and run.partial else None,
            error_message=run.note if run else None,
        )
        await self._register_threads(trigger, pr, run_id)
        log_run(
            logger,
            repo=repo,
            pr=pr.number,
            sha=pr.head_sha,
            mode=self._config.mode,
            steps=run.steps if run else 0,
            tokens=run.tokens if run else 0,
            duration_s=duration,
            findings=findings,
            outcome=outcome.value,
        )

    async def _register_threads(self, trigger: Trigger, pr: PullRequest, run_id: int) -> None:
        """Remember the threads the bot just opened so later commands can find them (ADR-8)."""
        bot = self._config.bot_login
        if not bot:
            logger.warning("bot login unknown; threads were not registered")
            return
        try:
            threads = await self._client.list_review_threads(
                trigger.installation_id, trigger.repo, pr.number
            )
        except (GitHubApiError, AuthError):
            logger.warning("could not list review threads", extra={"repo": trigger.repo})
            return
        known = {
            thread.thread_id
            for thread in await asyncio.to_thread(self._store.list_threads, trigger.repo, pr.number)
        }
        for thread in threads:
            if thread.is_resolved or thread.id in known:
                continue
            if not same_login(thread.author_login, bot):
                continue
            await asyncio.to_thread(
                partial(
                    self._store.add_thread,
                    thread.id,
                    run_id=run_id,
                    repo=trigger.repo,
                    pr_number=pr.number,
                    path=thread.path,
                    line=thread.line,
                )
            )

    async def report_failure(
        self, trigger: Trigger, sha: str, error: Exception, started: float
    ) -> None:
        """Record a failed run and post the single failure notice (FR-20)."""
        outcome = failure_outcome(error)
        duration = time.monotonic() - started
        logger.error(
            "review failed",
            extra={"repo": trigger.repo, "pr": trigger.pr_number, "error": type(error).__name__},
        )
        await asyncio.to_thread(
            lambda: self._store.record_run(
                trigger.key,
                steps=0,
                tokens=0,
                duration_s=duration,
                findings=0,
                outcome=outcome,
            )
        )
        log_run(
            logger,
            repo=trigger.repo,
            pr=trigger.pr_number,
            sha=sha,
            mode=self._config.mode,
            steps=0,
            tokens=0,
            duration_s=duration,
            findings=0,
            outcome=outcome.value,
        )
        await self._publisher.post_notice(
            trigger.installation_id,
            trigger.repo,
            trigger.pr_number,
            commit_sha=sha or "unknown",
            trigger_text=self._config.trigger_text,
        )
