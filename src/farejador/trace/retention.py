# Filename: retention.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Delete traces older than the retention window, in small batches (FR-13, FN-8)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from farejador.trace.store import TraceStore

logger = logging.getLogger(__name__)

# 100 runs with their children take about 10 to 16 ms; 500 took 67 ms or more (NFR-1.2).
BATCH_SIZE = 100
INTERVAL_SECONDS = 24 * 3600


def purge_expired(store: TraceStore, retention_days: int, *, batch_size: int = BATCH_SIZE) -> int:
    """Delete every run older than ``retention_days`` and return how many were removed.

    Batches keep each write short, so the writer thread is never blocked for long.
    """
    cutoff = store.clock() - timedelta(days=retention_days)
    deleted = 0
    while True:
        removed = store.delete_runs_before(cutoff, batch_size)
        deleted += removed
        if removed < batch_size:
            return deleted


def run_maintenance(store: TraceStore, retention_days: int) -> tuple[int, int]:
    """One pass: mark abandoned runs as incomplete, then purge. Returns (stale, deleted)."""
    stale = store.mark_stale_running()
    deleted = purge_expired(store, retention_days)
    return stale, deleted


async def retention_loop(
    store: TraceStore,
    retention_days: int,
    *,
    interval_s: float = INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Run the maintenance at start and then every ``interval_s``; an error never ends the loop."""
    while True:
        try:
            stale, deleted = await asyncio.to_thread(run_maintenance, store, retention_days)
            logger.info(
                "trace maintenance finished",
                extra={
                    "deleted_runs": deleted,
                    "stale_runs": stale,
                    "retention_days": retention_days,
                },
            )
        except Exception as exc:  # an error must never end the loop
            logger.error("trace maintenance failed", extra={"error_type": type(exc).__name__})
        await sleep(interval_s)
