# Filename: test_webhook_fast_ack.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio
import logging

import pytest
from tests.webhook_env import (
    SECRET,
    client_for,
    create_app,
    drain,
    post,
    pull_request_event,
)

from farejador.dispatcher import SubmitResult
from farejador.models import Trigger


async def test_the_answer_does_not_wait_for_the_submission_to_finish() -> None:
    gate = asyncio.Event()
    submitted: list[str] = []

    async def slow_submit(trigger: Trigger) -> SubmitResult:
        await gate.wait()
        submitted.append(trigger.key)
        return SubmitResult.ENQUEUED

    app = create_app(secret=SECRET, submit=slow_submit)
    async with client_for(app) as client:
        response = await asyncio.wait_for(
            post(client, "pull_request", pull_request_event()), timeout=2
        )
        assert response.status_code == 202
        assert submitted == []  # the work has not finished, yet we already answered
        assert len(app.state.pending) == 1
        gate.set()
        await drain(app)
    assert submitted == ["first:o/r#7"]
    assert app.state.pending == set()


async def test_a_failing_submission_is_logged_and_does_not_change_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken(_trigger: Trigger) -> SubmitResult:
        raise RuntimeError("queue is broken")

    app = create_app(secret=SECRET, submit=broken)
    with caplog.at_level(logging.ERROR):
        async with client_for(app) as client:
            response = await post(client, "pull_request", pull_request_event())
        await drain(app)
    assert response.status_code == 202
    assert any("could not submit trigger" in record.message for record in caplog.records)


async def test_health_endpoint_reports_the_mode() -> None:
    app = create_app(secret=SECRET, submit=lambda _t: None, mode="both")  # type: ignore[arg-type,return-value]
    async with client_for(app) as client:
        response = await client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok", "mode": "both"})
