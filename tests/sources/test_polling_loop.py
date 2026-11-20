# Filename: test_polling_loop.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio

import httpx
import pytest
import respx
from tests.polling_env import build_world, pr

from farejador.state.store import StateStore


async def test_the_loop_polls_then_sleeps_for_the_configured_interval(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1)], interval_s=42.0)
    cycles = 0

    async def stop_after_three(delay: float) -> None:
        nonlocal cycles
        cycles += 1
        world.sleep.delays.append(delay)
        if cycles == 3:
            raise asyncio.CancelledError

    world.source._sleep = stop_after_three  # type: ignore[assignment]
    with pytest.raises(asyncio.CancelledError):
        await world.source.run()
    assert world.sleep.delays == [42.0, 42.0, 42.0]
    assert world.submit.keys == ["first:o/r#1"]


async def test_a_failing_cycle_is_logged_and_the_next_one_still_runs(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1)])
    installations = respx_mock.get("https://api.github.com/app/installations")
    installations.mock(
        side_effect=[
            httpx.Response(500, json={"message": "boom"}),
            httpx.Response(200, json=[{"id": 7, "account": {"login": "o"}}]),
        ]
    )
    cycles = 0

    async def sleep(_delay: float) -> None:
        nonlocal cycles
        cycles += 1
        if cycles == 2:
            raise asyncio.CancelledError

    world.source._sleep = sleep  # type: ignore[assignment]
    # retries inside the client are instant (SleepRecorder), so the first cycle fails fast
    world.client._max_retries = 0
    with pytest.raises(asyncio.CancelledError):
        await world.source.run()
    assert world.submit.keys == ["first:o/r#1"]
    assert installations.call_count == 2
