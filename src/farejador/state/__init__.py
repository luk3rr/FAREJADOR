# Filename: __init__.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Persistent state: idempotency of triggers, runs, bot threads and polling cursors."""

from farejador.state.store import (
    BotThread,
    Outcome,
    StateStore,
    ThreadStatus,
    TriggerRecord,
    TriggerStatus,
)

__all__ = [
    "BotThread",
    "Outcome",
    "StateStore",
    "ThreadStatus",
    "TriggerRecord",
    "TriggerStatus",
]
