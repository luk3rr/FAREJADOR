# Filename: test_webhook_idempotency.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

from tests.webhook_env import (
    SECRET,
    client_for,
    comment_event,
    create_app,
    drain,
    post,
    pull_request_event,
)

from farejador.dispatcher import Dispatcher
from farejador.models import Trigger, TriggerKind
from farejador.state.store import StateStore


async def test_the_same_delivery_twice_runs_once_even_across_a_restart(tmp_path: Path) -> None:
    handled: list[str] = []

    async def handler(trigger: Trigger) -> None:
        handled.append(trigger.key)

    path = tmp_path / "state.db"
    for delivery in ("d-1", "d-1-redelivered"):
        with StateStore(path) as store:
            dispatcher = Dispatcher(
                store,
                {TriggerKind.FIRST_REVIEW: handler, TriggerKind.COMMAND: handler},
                workers=1,
            )
            await dispatcher.start()
            app = create_app(secret=SECRET, submit=dispatcher.submit)
            async with client_for(app) as client:
                first = await post(client, "pull_request", pull_request_event(), delivery=delivery)
                second = await post(
                    client, "pull_request", pull_request_event(), delivery=delivery + "-b"
                )
            await drain(app)
            await dispatcher.stop()
            assert (first.status_code, second.status_code) == (202, 202)
    assert handled == ["first:o/r#7"]


async def test_events_from_the_bot_never_reach_a_handler(tmp_path: Path) -> None:
    handled: list[str] = []

    async def handler(trigger: Trigger) -> None:
        handled.append(trigger.key)

    with StateStore(tmp_path / "state.db") as store:
        dispatcher = Dispatcher(
            store, {TriggerKind.COMMAND: handler}, workers=1, bot_login="farejador[bot]"
        )
        await dispatcher.start()
        app = create_app(secret=SECRET, submit=dispatcher.submit)  # the app does not know the bot
        async with client_for(app) as client:
            await post(client, "issue_comment", comment_event(author="farejador[bot]"))
            await post(client, "issue_comment", comment_event(author="alice", comment_id=902))
        await drain(app)
        await dispatcher.stop()
    assert handled == ["cmd:902"]
