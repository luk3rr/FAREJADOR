# Filename: test_polling_comments.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import respx
from tests.polling_env import START, build_world, comment, pr

from farejador.models import TriggerKind, TriggerSource
from farejador.state.store import StateStore


async def test_comments_that_mention_farejador_become_command_triggers(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(
        respx_mock,
        store,
        prs=[pr(1)],
        comments={
            1: [
                comment(11, "@farejador please re-check", "2026-11-20T10:05:00Z", author="bob"),
                comment(12, "just a normal comment", "2026-11-20T10:06:00Z"),
                comment(13, "Hey @FAREJADOR, again", "2026-11-20T10:07:00Z", author="carol"),
            ]
        },
    )
    stats = await world.source.poll_once()
    commands = [t for t in world.submit.triggers if t.kind is TriggerKind.COMMAND]
    assert [(t.key, t.sender_login, t.pr_number) for t in commands] == [
        ("cmd:11", "bob", 1),
        ("cmd:13", "carol", 1),
    ]
    assert commands[0].source is TriggerSource.POLLING
    assert stats.commands == 2


async def test_comments_by_the_bot_itself_are_ignored(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(
        respx_mock,
        store,
        prs=[pr(1)],
        comments={
            1: [
                comment(
                    11,
                    "Mencione `@farejador` to retry",
                    "2026-11-20T10:05:00Z",
                    author="Farejador[bot]",
                )
            ]
        },
    )
    await world.source.poll_once()
    assert [t.key for t in world.submit.triggers if t.kind is TriggerKind.COMMAND] == []


async def test_comments_older_than_the_service_start_are_not_replayed(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(
        respx_mock,
        store,
        prs=[pr(1)],
        comments={
            1: [
                comment(10, "@farejador (before we started)", "2026-11-19T09:00:00Z"),
                comment(11, "@farejador (after)", "2026-11-20T10:01:00Z"),
            ]
        },
    )
    await world.source.poll_once()
    assert [t.key for t in world.submit.triggers if t.kind is TriggerKind.COMMAND] == ["cmd:11"]


async def test_the_since_filter_is_sent_and_the_cursor_advances(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(
        respx_mock,
        store,
        prs=[pr(1)],
        comments={1: [comment(11, "@farejador", "2026-11-20T10:05:00Z")]},
    )
    await world.source.poll_once()
    first = world.comments_routes[1].calls[0].request
    assert first.url.params["since"] == START
    assert store.get_cursor("comments:o/r#1") == ('"c-1"', "2026-11-20T10:05:00Z")

    await world.source.poll_once()
    second = world.comments_routes[1].calls[1].request
    assert second.url.params["since"] == "2026-11-20T10:05:00Z"


async def test_a_reappearing_comment_is_not_processed_twice(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(
        respx_mock,
        store,
        prs=[pr(1)],
        comments={1: [comment(11, "@farejador", "2026-11-20T10:05:00Z")]},
    )
    await world.source.poll_once()
    # an edit makes GitHub return the same comment again (new ETag, same created_at)
    world.comments_routes[1].mock(
        return_value=__import__("httpx").Response(
            200,
            json=[comment(11, "@farejador (edited)", "2026-11-20T10:05:00Z")],
            headers={"ETag": '"c-1b"'},
        )
    )
    stats = await world.source.poll_once()
    assert [t.key for t in world.submit.triggers if t.kind is TriggerKind.COMMAND] == ["cmd:11"]
    assert stats.commands == 0


async def test_draft_prs_still_accept_commands(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(
        respx_mock,
        store,
        prs=[pr(1, draft=True)],
        comments={1: [comment(11, "@farejador", "2026-11-20T10:05:00Z")]},
    )
    await world.source.poll_once()
    assert world.submit.keys == ["cmd:11"]


async def test_the_request_carries_the_installation_token(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1)])
    await world.source.poll_once()
    request = world.comments_routes[1].calls[0].request
    assert request.headers["Authorization"] == "Bearer token-7-v1"
    assert json.loads("{}") == {}
