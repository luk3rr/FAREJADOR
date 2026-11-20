# Filename: test_webhook_events.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest
from tests.webhook_env import (
    SECRET,
    Recorder,
    client_for,
    comment_event,
    create_app,
    drain,
    post,
    pull_request_event,
)

from farejador.models import TriggerKind, TriggerSource


def _app(recorder: Recorder, **kwargs: object):  # type: ignore[no-untyped-def]
    return create_app(secret=SECRET, submit=recorder, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("action", ["opened", "reopened", "ready_for_review"])
async def test_pull_request_events_become_first_review_triggers(action: str) -> None:
    recorder = Recorder()
    app = _app(recorder)
    async with client_for(app) as client:
        response = await post(client, "pull_request", pull_request_event(action))
    await drain(app)

    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    (trigger,) = recorder.triggers
    assert trigger.kind is TriggerKind.FIRST_REVIEW
    assert (trigger.key, trigger.installation_id, trigger.head_sha) == (
        "first:o/r#7",
        55,
        "abc1234def",
    )
    assert (trigger.sender_login, trigger.source) == ("alice", TriggerSource.WEBHOOK)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (pull_request_event("synchronize"), "unsupported-action"),
        (pull_request_event("closed"), "unsupported-action"),
        (pull_request_event("opened", draft=True), "draft"),
        (pull_request_event("opened", state="closed"), "closed"),
        (pull_request_event("opened", installation=False), "no-installation"),
    ],
)
async def test_pull_request_events_without_work_are_acknowledged_and_ignored(
    payload: dict[str, object], reason: str
) -> None:
    recorder = Recorder()
    app = _app(recorder)
    async with client_for(app) as client:
        response = await post(client, "pull_request", payload)
    await drain(app)
    assert (response.status_code, response.json()) == (
        202,
        {"status": "ignored", "reason": reason},
    )
    assert recorder.triggers == []


async def test_a_comment_that_mentions_farejador_becomes_a_command_trigger() -> None:
    recorder = Recorder()
    app = _app(recorder)
    async with client_for(app) as client:
        response = await post(client, "issue_comment", comment_event("Hey @Farejador, again"))
    await drain(app)
    assert response.json() == {"status": "accepted"}
    (trigger,) = recorder.triggers
    assert trigger.kind is TriggerKind.COMMAND
    assert (trigger.key, trigger.pr_number, trigger.sender_login) == ("cmd:901", 7, "bob")
    assert trigger.installation_id == 55


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (comment_event("no mention here"), "no-command"),
        (comment_event(on_pr=False), "not-a-pr"),
        (comment_event(action="edited"), "unsupported-action"),
        (comment_event(action="deleted"), "unsupported-action"),
    ],
)
async def test_comments_without_a_command_are_ignored(
    payload: dict[str, object], reason: str
) -> None:
    recorder = Recorder()
    app = _app(recorder)
    async with client_for(app) as client:
        response = await post(client, "issue_comment", payload)
    await drain(app)
    assert response.json() == {"status": "ignored", "reason": reason}
    assert recorder.triggers == []


async def test_comments_by_the_bot_are_ignored_when_its_login_is_known() -> None:
    recorder = Recorder()
    app = _app(recorder, bot_login="Farejador[bot]")
    async with client_for(app) as client:
        response = await post(
            client,
            "issue_comment",
            comment_event("Mention @farejador to retry", author="farejador[BOT]"),
        )
    await drain(app)
    assert response.json() == {"status": "ignored", "reason": "own-event"}
    assert recorder.triggers == []


async def test_the_trigger_text_is_configurable() -> None:
    recorder = Recorder()
    app = _app(recorder, trigger_text="/sniff")
    async with client_for(app) as client:
        await post(client, "issue_comment", comment_event("@farejador"))
        await post(client, "issue_comment", comment_event("please /sniff this", comment_id=902))
    await drain(app)
    assert [t.key for t in recorder.triggers] == ["cmd:902"]


async def test_ping_and_unknown_events() -> None:
    recorder = Recorder()
    app = _app(recorder)
    async with client_for(app) as client:
        ping = await post(client, "ping", {"zen": "Keep it logically awesome."})
        other = await post(client, "push", {"ref": "refs/heads/main"})
    assert (ping.status_code, ping.json()) == (200, {"status": "pong"})
    assert (other.status_code, other.json()) == (
        202,
        {"status": "ignored", "reason": "unsupported-event"},
    )
    assert recorder.triggers == []
