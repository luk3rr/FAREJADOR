# Filename: test_polling_etag.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import httpx
import respx
from tests.polling_env import RecordingSubmit, build_world, comment, pr

from farejador.models import TriggerKind
from farejador.state.store import StateStore


async def test_repeated_polls_send_validators_and_handle_304(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1)])
    await world.source.poll_once()

    world.prs_route.mock(return_value=httpx.Response(304))
    world.comments_routes[1].mock(return_value=httpx.Response(304))
    stats = await world.source.poll_once()

    assert world.prs_route.calls[1].request.headers["If-None-Match"] == '"prs-1"'
    assert world.comments_routes[1].calls[1].request.headers["If-None-Match"] == '"c-1"'
    assert stats.not_modified == 2
    assert stats.open_prs == 1  # the cached list is reused when GitHub answers 304
    assert stats.first_reviews == 0


async def test_a_new_comment_is_seen_even_when_the_pr_list_is_unchanged(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1)])
    await world.source.poll_once()

    world.prs_route.mock(return_value=httpx.Response(304))
    world.comments_routes[1].mock(
        return_value=httpx.Response(
            200,
            json=[comment(21, "@farejador", "2026-11-20T11:00:00Z")],
            headers={"ETag": '"c-1b"'},
        )
    )
    stats = await world.source.poll_once()
    assert stats.commands == 1
    assert world.submit.keys[-1] == "cmd:21"


async def test_cursors_survive_a_restart_so_old_commands_are_not_replayed(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    comments = {1: [comment(11, "@farejador", "2026-11-20T10:05:00Z")]}
    first = build_world(respx_mock, store, prs=[pr(1)], comments=comments)
    await first.source.poll_once()
    assert first.submit.keys.count("cmd:11") == 1

    # a new process: new PollingSource and a clean claim table, same persisted cursors
    restarted_submit = RecordingSubmit(store)
    second = build_world(
        respx_mock,
        store,
        prs=[pr(1)],
        comments=comments,
        submit=restarted_submit,
        started_at="2026-11-20T12:00:00Z",
    )
    await second.source.poll_once()
    sent = second.comments_routes[1].calls.last.request
    assert sent.url.params["since"] == "2026-11-20T10:05:00Z"
    assert sent.headers["If-None-Match"] == '"c-1"'
    assert [t for t in restarted_submit.triggers if t.kind is TriggerKind.COMMAND] == []


async def test_a_restart_does_not_resubmit_first_reviews_already_handled(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    first = build_world(respx_mock, store, prs=[pr(1)])
    await first.source.poll_once()
    assert first.submit.keys == ["first:o/r#1"]
    second = build_world(respx_mock, store, prs=[pr(1)], submit=RecordingSubmit(store))
    await second.source.poll_once()
    assert second.submit.keys == []
