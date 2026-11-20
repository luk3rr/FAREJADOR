# Filename: test_webhook_errors.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import pytest
from tests.webhook_env import (
    SECRET,
    Recorder,
    client_for,
    create_app,
    drain,
    post,
    pull_request_event,
    sign,
)


async def _status(
    recorder: Recorder, event: str, payload: dict[str, object] | bytes, **kwargs: object
) -> tuple[int, dict[str, object]]:
    app = create_app(secret=SECRET, submit=recorder, **kwargs.pop("app", {}))  # type: ignore[arg-type]
    async with client_for(app) as client:
        response = await post(client, event, payload, **kwargs)  # type: ignore[arg-type]
    await drain(app)
    return response.status_code, response.json()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"signature": None},
        {"signature": "sha256=deadbeef"},
        {"signature": "nonsense"},
        {"secret": "the-wrong-secret"},
    ],
)
async def test_invalid_or_missing_signatures_get_401_and_nothing_runs(
    kwargs: dict[str, object],
) -> None:
    recorder = Recorder()
    status, body = await _status(recorder, "pull_request", pull_request_event(), **kwargs)
    assert (status, body) == (401, {"error": "invalid signature"})
    assert recorder.triggers == []


async def test_the_signature_is_checked_before_the_body_is_parsed() -> None:
    recorder = Recorder()
    status, _ = await _status(recorder, "pull_request", b"{not json", signature=None)
    assert status == 401  # not 400: nothing about the body is revealed to unsigned callers


async def test_a_tampered_body_is_rejected() -> None:
    recorder = Recorder()
    body = json.dumps(pull_request_event()).encode()
    status, _ = await _status(recorder, "pull_request", body + b" ", signature=sign(body))
    assert status == 401
    assert recorder.triggers == []


async def test_a_missing_event_header_is_a_400() -> None:
    recorder = Recorder()
    app = create_app(secret=SECRET, submit=recorder)
    body = json.dumps(pull_request_event()).encode()
    async with client_for(app) as client:
        response = await client.post(
            "/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)}
        )
    assert response.status_code == 400
    assert recorder.triggers == []


@pytest.mark.parametrize("body", [b"{broken", b"\xff\xfe", b"[1, 2, 3]", b'"text"', b"null"])
async def test_signed_but_malformed_json_is_a_400(body: bytes) -> None:
    recorder = Recorder()
    status, payload = await _status(recorder, "pull_request", body)
    assert (status, payload) == (400, {"error": "malformed payload"})
    assert recorder.triggers == []


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("pull_request", {"action": "opened", "installation": {"id": 1}}),
        ("pull_request", {"action": "opened", "installation": {"id": 1}, "pull_request": 5}),
        ("issue_comment", {"action": "created", "installation": {"id": 1}}),
        (
            "issue_comment",
            {
                "action": "created",
                "installation": {"id": 1},
                "issue": {"pull_request": {}},
                "comment": {"body": "@farejador"},
            },
        ),
    ],
)
async def test_payloads_missing_required_fields_are_a_400(
    event: str, payload: dict[str, object]
) -> None:
    recorder = Recorder()
    status, body = await _status(recorder, event, payload)
    assert (status, body) == (400, {"error": "malformed payload"})
    assert recorder.triggers == []


async def test_a_declared_content_length_over_the_limit_is_a_413() -> None:
    recorder = Recorder()
    status, body = await _status(
        recorder,
        "pull_request",
        pull_request_event(),
        extra_headers={"Content-Length": "6000000"},
    )
    assert (status, body) == (413, {"error": "payload too large"})
    assert recorder.triggers == []


async def test_a_body_over_the_limit_is_a_413_even_if_it_is_signed() -> None:
    recorder = Recorder()
    body = b'{"pad": "' + b"x" * 200 + b'"}'
    status, payload = await _status(recorder, "pull_request", body, app={"max_body": 100})
    assert (status, payload) == (413, {"error": "payload too large"})
