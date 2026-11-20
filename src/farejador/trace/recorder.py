# Filename: recorder.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Records what the agent did, without ever slowing down or breaking a review (FR-7, ADR-6).

The agent side only drops small records into a bounded queue; one writer thread masks, truncates
and writes them (NFR-2.1, NFR-2.3). Every public method swallows its own errors: a trace problem
becomes a log line and, at most, a run marked ``incomplete``.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from farejador.trace.store import (
    FindingRecord,
    RunOutcome,
    ToolResult,
    TraceStore,
)

logger = logging.getLogger(__name__)

QUEUE_SIZE = 1000
STOP_TIMEOUT_S = 5.0
_STOP = object()
_LOG_EVERY_DROPS = 100


class RunTrace(Protocol):
    """One execution being recorded."""

    def step(
        self,
        *,
        index: int,
        started_at: datetime,
        duration_s: float,
        tokens: int,
        input_messages: Sequence[Mapping[str, Any]],
        response_content: str | None,
        reasoning: str | None,
        tool_calls: Sequence[Mapping[str, str]],
        tool_results: Sequence[ToolResult],
    ) -> None: ...

    def findings(self, findings: Sequence[FindingRecord]) -> None: ...

    def finish(
        self,
        *,
        outcome: RunOutcome,
        steps: int,
        tokens: int,
        duration_s: float,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None: ...


class Recorder(Protocol):
    """Opens a ``RunTrace`` for each execution of the agent."""

    def begin(
        self,
        *,
        trigger_key: str,
        kind: str,
        repo: str,
        pr_number: int,
        head_sha: str | None,
        repo_public: bool | None,
    ) -> RunTrace: ...


class NullRunTrace:
    """Ignores everything; used when the trace is off or unavailable."""

    def step(self, **_kwargs: Any) -> None:
        return None

    def findings(self, findings: Sequence[FindingRecord]) -> None:
        return None

    def finish(self, **_kwargs: Any) -> None:
        return None


class NullRecorder:
    def begin(self, **_kwargs: Any) -> NullRunTrace:
        return NULL_RUN


NULL_RUN = NullRunTrace()


class _ActiveRun:
    """A run in progress; its operations reach the writer thread in order."""

    def __init__(self, recorder: TraceRecorder) -> None:
        self._recorder = recorder
        self.run_id: int | None = None
        self.lost = False

    def step(
        self,
        *,
        index: int,
        started_at: datetime,
        duration_s: float,
        tokens: int,
        input_messages: Sequence[Mapping[str, Any]],
        response_content: str | None,
        reasoning: str | None,
        tool_calls: Sequence[Mapping[str, str]],
        tool_results: Sequence[ToolResult],
    ) -> None:
        try:
            # Copies: the agent keeps appending to its own lists after this call returns.
            messages = [dict(message) for message in input_messages]
            calls = [dict(call) for call in tool_calls]
            results = list(tool_results)
        except Exception:
            self._recorder._note_error(self, "copy")
            return

        def write(store: TraceStore) -> None:
            if self.run_id is not None:
                store.add_step(
                    self.run_id,
                    index=index,
                    started_at=started_at,
                    duration_s=duration_s,
                    tokens=tokens,
                    input_messages=messages,
                    response_content=response_content,
                    reasoning=reasoning,
                    tool_calls=calls,
                    tool_results=results,
                )

        self._recorder._submit(self, write)

    def findings(self, findings: Sequence[FindingRecord]) -> None:
        records = list(findings)

        def write(store: TraceStore) -> None:
            if self.run_id is not None:
                for record in records:
                    store.add_finding(self.run_id, record)

        self._recorder._submit(self, write)

    def finish(
        self,
        *,
        outcome: RunOutcome,
        steps: int,
        tokens: int,
        duration_s: float,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        def write(store: TraceStore) -> None:
            if self.run_id is None:
                return
            final = outcome
            if self.lost and outcome in (RunOutcome.COMPLETE, RunOutcome.PARTIAL):
                final = RunOutcome.INCOMPLETE  # something of this run did not reach the file
            store.finish_run(
                self.run_id,
                outcome=final,
                steps=steps,
                tokens=tokens,
                duration_s=duration_s,
                error_category=error_category,
                error_message=error_message,
            )

        self._recorder._submit(self, write)


class TraceRecorder:
    """The real recorder: a bounded queue in front of one writer thread."""

    def __init__(
        self,
        store: TraceStore,
        *,
        model: str,
        prompt_version: str,
        app_version: str,
        budgets: Mapping[str, Any],
        queue_size: int = QUEUE_SIZE,
    ) -> None:
        self._store = store
        self._model = model
        self._prompt_version = prompt_version
        self._app_version = app_version
        self._budgets = dict(budgets)
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._closed = False
        self.dropped = 0
        self.failed = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="trace-writer", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = STOP_TIMEOUT_S) -> None:
        """Flush what is queued (up to ``timeout`` seconds) and stop the writer thread."""
        self._closed = True
        thread = self._thread
        if thread is None:
            return
        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            logger.error("trace queue did not drain before shutdown")
        thread.join(timeout)
        self._thread = None

    # -- recording ---------------------------------------------------------

    def begin(
        self,
        *,
        trigger_key: str,
        kind: str,
        repo: str,
        pr_number: int,
        head_sha: str | None,
        repo_public: bool | None,
    ) -> RunTrace:
        run = _ActiveRun(self)

        def write(store: TraceStore) -> None:
            run.run_id = store.begin_run(
                trigger_key=trigger_key,
                kind=kind,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
                repo_public=repo_public,
                model=self._model,
                prompt_version=self._prompt_version,
                app_version=self._app_version,
                budgets=self._budgets,
            )

        self._submit(run, write)
        return run

    # -- internals ---------------------------------------------------------

    def _submit(self, run: _ActiveRun, operation: Callable[[TraceStore], None]) -> None:
        """Hand an operation to the writer; never blocks and never raises."""
        try:
            if self._closed:
                raise queue.Full
            self._queue.put_nowait((run, operation))
        except queue.Full:
            run.lost = True
            self.dropped += 1
            if self.dropped == 1 or self.dropped % _LOG_EVERY_DROPS == 0:
                logger.error("trace record dropped", extra={"dropped_total": self.dropped})
        except Exception:
            self._note_error(run, "submit")

    def _note_error(self, run: _ActiveRun, where: str) -> None:
        run.lost = True
        self.failed += 1
        logger.error("trace record failed", extra={"where": where})

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            run, operation = item
            try:
                operation(self._store)
            except Exception as exc:  # the writer must outlive any single bad record
                run.lost = True
                self.failed += 1
                logger.error("trace write failed", extra={"error_type": type(exc).__name__})
