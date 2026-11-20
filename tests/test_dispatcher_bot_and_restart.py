# Filename: test_dispatcher_bot_and_restart.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from tests.factories import make_command, make_first

from farejador.dispatcher import Dispatcher, SubmitResult
from farejador.models import Trigger, TriggerKind
from farejador.state.store import StateStore, TriggerStatus


async def test_events_from_the_bot_are_ignored_case_insensitively(store: StateStore) -> None:
    calls: list[str] = []

    async def handler(trigger: Trigger) -> None:
        calls.append(trigger.key)

    dispatcher = Dispatcher(
        store, {TriggerKind.COMMAND: handler}, workers=1, bot_login="Farejador[bot]"
    )
    await dispatcher.start()
    own = make_command(comment_id=1, sender="farejador[BOT]")
    assert await dispatcher.submit(own) is SubmitResult.IGNORED_BOT
    assert await dispatcher.submit(make_command(comment_id=2, sender="alice")) is (
        SubmitResult.ENQUEUED
    )
    await dispatcher.stop()

    assert calls == ["cmd:2"]
    assert store.get_trigger(own.key) is None


async def test_bot_login_can_be_set_after_construction(store: StateStore) -> None:
    dispatcher = Dispatcher(store, {}, workers=1)
    dispatcher.set_bot_login("Bot[bot]")
    assert await dispatcher.submit(make_first(sender="bot[bot]")) is SubmitResult.IGNORED_BOT


async def test_without_a_known_bot_login_nothing_is_filtered(store: StateStore) -> None:
    dispatcher = Dispatcher(store, {}, workers=1)
    assert await dispatcher.submit(make_first(sender="farejador[bot]")) is SubmitResult.ENQUEUED


async def test_start_marks_interrupted_triggers_as_failed(store: StateStore) -> None:
    claimed = make_first(pr=1)
    running = make_first(pr=2)
    finished = make_first(pr=3)
    for trigger in (claimed, running, finished):
        store.try_claim(trigger)
    store.mark(running.key, TriggerStatus.RUNNING)
    store.mark(finished.key, TriggerStatus.DONE)

    dispatcher = Dispatcher(store, {}, workers=1)
    await dispatcher.start()
    await dispatcher.stop()

    for trigger in (claimed, running):
        record = store.get_trigger(trigger.key)
        assert record is not None
        assert (record.status, record.error) == (TriggerStatus.FAILED, "InterruptedByRestart")
    done = store.get_trigger(finished.key)
    assert done is not None
    assert done.status is TriggerStatus.DONE
