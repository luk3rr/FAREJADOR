# Filename: test_dispatcher.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio

from tests.factories import make_command, make_first

from farejador.dispatcher import Dispatcher, SubmitResult
from farejador.models import Trigger, TriggerKind
from farejador.state.store import StateStore, TriggerStatus


async def test_trigger_runs_once_and_is_marked_done(store: StateStore) -> None:
    seen: list[str] = []

    async def handler(trigger: Trigger) -> None:
        seen.append(trigger.key)

    dispatcher = Dispatcher(store, {TriggerKind.FIRST_REVIEW: handler}, workers=2)
    await dispatcher.start()
    first = make_first()
    assert await dispatcher.submit(first) is SubmitResult.ENQUEUED
    assert await dispatcher.submit(first) is SubmitResult.DUPLICATE
    await dispatcher.stop()

    assert seen == [first.key]
    record = store.get_trigger(first.key)
    assert record is not None
    assert record.status is TriggerStatus.DONE


async def test_routes_by_kind(store: StateStore) -> None:
    calls: list[tuple[str, str]] = []

    async def on_first(trigger: Trigger) -> None:
        calls.append(("first", trigger.key))

    async def on_command(trigger: Trigger) -> None:
        calls.append(("command", trigger.key))

    dispatcher = Dispatcher(
        store,
        {TriggerKind.FIRST_REVIEW: on_first, TriggerKind.COMMAND: on_command},
        workers=1,
    )
    await dispatcher.start()
    await dispatcher.submit(make_first(pr=1))
    await dispatcher.submit(make_command(comment_id=7))
    await dispatcher.stop()
    assert sorted(calls) == [("command", "cmd:7"), ("first", "first:o/r#1")]


async def test_handler_exception_marks_failed_with_class_name_only(store: StateStore) -> None:
    async def handler(_trigger: Trigger) -> None:
        raise ValueError("token ghp_supersecret must not be stored")

    dispatcher = Dispatcher(store, {TriggerKind.FIRST_REVIEW: handler}, workers=1)
    await dispatcher.start()
    trigger = make_first()
    await dispatcher.submit(trigger)
    await dispatcher.stop()

    record = store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.FAILED, "ValueError")


async def test_failure_does_not_stop_the_worker(store: StateStore) -> None:
    done: list[str] = []

    async def handler(trigger: Trigger) -> None:
        if trigger.pr_number == 1:
            raise RuntimeError("boom")
        done.append(trigger.key)

    dispatcher = Dispatcher(store, {TriggerKind.FIRST_REVIEW: handler}, workers=1)
    await dispatcher.start()
    await dispatcher.submit(make_first(pr=1))
    await dispatcher.submit(make_first(pr=2))
    await dispatcher.stop()
    assert done == ["first:o/r#2"]


async def test_missing_handler_marks_failed(store: StateStore) -> None:
    dispatcher = Dispatcher(store, {}, workers=1)
    await dispatcher.start()
    trigger = make_first()
    await dispatcher.submit(trigger)
    await dispatcher.stop()
    record = store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.FAILED, "NoHandler")


async def test_workers_run_in_parallel(store: StateStore) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    running = 0
    peak = 0

    async def handler(_trigger: Trigger) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        if running == 2:
            started.set()
        await release.wait()
        running -= 1

    dispatcher = Dispatcher(store, {TriggerKind.FIRST_REVIEW: handler}, workers=2)
    await dispatcher.start()
    await dispatcher.submit(make_first(pr=1))
    await dispatcher.submit(make_first(pr=2))
    await asyncio.wait_for(started.wait(), timeout=2)
    release.set()
    await dispatcher.stop()
    assert peak == 2


async def test_stop_without_drain_cancels_running_work(store: StateStore) -> None:
    gate = asyncio.Event()

    async def handler(_trigger: Trigger) -> None:
        await gate.wait()

    dispatcher = Dispatcher(store, {TriggerKind.FIRST_REVIEW: handler}, workers=1)
    await dispatcher.start()
    trigger = make_first()
    await dispatcher.submit(trigger)
    await asyncio.sleep(0.05)
    await dispatcher.stop(drain=False)
    record = store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.FAILED, "Cancelled")


async def test_a_skipped_trigger_releases_its_key_for_a_later_event(store: StateStore) -> None:
    from farejador.dispatcher import TriggerSkipped

    attempts: list[str] = []

    async def handler(trigger: Trigger) -> None:
        attempts.append(trigger.key)
        if len(attempts) == 1:
            raise TriggerSkipped("draft")

    dispatcher = Dispatcher(store, {TriggerKind.FIRST_REVIEW: handler}, workers=1)
    await dispatcher.start()
    trigger = make_first()
    assert await dispatcher.submit(trigger) is SubmitResult.ENQUEUED
    await dispatcher.stop()
    record = store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.SKIPPED, "draft")

    await dispatcher.start()
    assert await dispatcher.submit(trigger) is SubmitResult.ENQUEUED
    await dispatcher.stop()
    assert attempts == [trigger.key, trigger.key]
    final = store.get_trigger(trigger.key)
    assert final is not None
    assert final.status is TriggerStatus.DONE
    assert await dispatcher.submit(trigger) is SubmitResult.DUPLICATE
