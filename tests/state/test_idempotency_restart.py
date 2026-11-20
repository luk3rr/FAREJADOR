# Filename: test_idempotency_restart.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

from tests.factories import make_first

from farejador.dispatcher import Dispatcher, SubmitResult
from farejador.models import Trigger, TriggerKind
from farejador.state.store import StateStore


async def test_same_trigger_runs_once_across_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    calls: list[str] = []

    async def handler(trigger: Trigger) -> None:
        calls.append(trigger.key)

    trigger = make_first()

    with StateStore(path) as first_store:
        first = Dispatcher(first_store, {TriggerKind.FIRST_REVIEW: handler}, workers=1)
        await first.start()
        assert await first.submit(trigger) is SubmitResult.ENQUEUED
        await first.stop()

    with StateStore(path) as reopened:
        second = Dispatcher(reopened, {TriggerKind.FIRST_REVIEW: handler}, workers=1)
        await second.start()
        assert await second.submit(trigger) is SubmitResult.DUPLICATE
        await second.stop()

    assert calls == [trigger.key]
