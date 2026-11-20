# Filename: dispatcher.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""In-process queue and workers that run triggers exactly once (ADR-1, FR-4, FR-5)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum

from farejador.models import Trigger, TriggerKind
from farejador.state.store import StateStore, TriggerStatus

logger = logging.getLogger(__name__)

Handler = Callable[[Trigger], Awaitable[None]]


class TriggerSkipped(Exception):
    """The trigger does not apply right now (draft, closed or already reviewed).

    It is not a failure: the key is released so a later event can claim it again.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SubmitResult(StrEnum):
    ENQUEUED = "enqueued"
    DUPLICATE = "duplicate"
    IGNORED_BOT = "ignored_bot"


class Dispatcher:
    """Claims triggers in the state store and runs them on a pool of async workers."""

    def __init__(
        self,
        store: StateStore,
        handlers: Mapping[TriggerKind, Handler],
        *,
        workers: int = 2,
        bot_login: str | None = None,
    ) -> None:
        self._store = store
        self._handlers = dict(handlers)
        self._worker_count = workers
        self._bot_login = bot_login.lower() if bot_login else None
        self._queue: asyncio.Queue[Trigger] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    def set_bot_login(self, login: str) -> None:
        """Set the bot login once it is known (for example after ``GET /app``)."""
        self._bot_login = login.lower()

    def _is_own_event(self, trigger: Trigger) -> bool:
        return self._bot_login is not None and trigger.sender_login.lower() == self._bot_login

    async def start(self) -> None:
        """Fail leftovers of a previous process and start the workers (A15)."""
        interrupted = await asyncio.to_thread(self._store.fail_interrupted)
        if interrupted:
            logger.warning("marked interrupted triggers as failed", extra={"count": interrupted})
        self._tasks = [
            asyncio.create_task(self._worker(), name=f"farejador-worker-{index}")
            for index in range(self._worker_count)
        ]

    async def stop(self, *, drain: bool = True) -> None:
        """Stop the workers, optionally waiting for queued triggers to finish."""
        if drain:
            await self._queue.join()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def submit(self, trigger: Trigger) -> SubmitResult:
        """Claim the trigger and queue it; duplicates and own events are dropped."""
        if self._is_own_event(trigger):
            return SubmitResult.IGNORED_BOT
        claimed = await asyncio.to_thread(self._store.try_claim, trigger)
        if not claimed:
            return SubmitResult.DUPLICATE
        await self._queue.put(trigger)
        return SubmitResult.ENQUEUED

    async def _worker(self) -> None:
        while True:
            trigger = await self._queue.get()
            try:
                await self._run(trigger)
            finally:
                self._queue.task_done()

    async def _run(self, trigger: Trigger) -> None:
        await asyncio.to_thread(self._store.mark, trigger.key, TriggerStatus.RUNNING)
        handler = self._handlers.get(trigger.kind)
        if handler is None:
            await self._fail(trigger, "NoHandler")
            return
        try:
            await handler(trigger)
        except asyncio.CancelledError:
            await asyncio.shield(self._fail(trigger, "Cancelled"))
            raise
        except TriggerSkipped as skipped:
            await asyncio.to_thread(
                self._store.mark, trigger.key, TriggerStatus.SKIPPED, skipped.reason
            )
        except Exception as exc:
            logger.exception("trigger failed", extra={"key": trigger.key})
            await self._fail(trigger, type(exc).__name__)
        else:
            await asyncio.to_thread(self._store.mark, trigger.key, TriggerStatus.DONE)

    async def _fail(self, trigger: Trigger, error: str) -> None:
        await asyncio.to_thread(self._store.mark, trigger.key, TriggerStatus.FAILED, error)
