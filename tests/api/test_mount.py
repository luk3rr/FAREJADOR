# Filename: test_mount.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The API lives inside the webhook app without touching it (FR-19, NFR-6)."""

from pathlib import Path

import pytest
import respx
from tests.api_env import seed
from tests.test_app import _app_route, _build, _settings
from tests.webhook_env import Recorder, client_for, comment_event, post, pull_request_event

from farejador.api.routes import create_api
from farejador.sources.webhook import create_app


def _combined(trace_path: Path):  # type: ignore[no-untyped-def]
    app = create_app(secret="whsec-test-secret", submit=Recorder())
    app.mount("/api", create_api(trace_path))
    return app


async def test_the_api_answers_under_api_and_the_webhook_still_works(tmp_path: Path) -> None:
    seeded = seed(tmp_path)
    app = _combined(seeded.path)
    async with client_for(app) as client:
        listing = await client.get("/api/reviews")
        health = await client.get("/healthz")
        accepted = await post(client, "pull_request", pull_request_event())
        ignored = await post(client, "issue_comment", comment_event(on_pr=False))
        unsigned = await post(client, "ping", {"zen": "x"}, signature=None)
    assert listing.status_code == 200 and len(listing.json()["items"]) == 3
    assert health.json() == {"status": "ok", "mode": "webhook"}
    assert accepted.status_code == 202 and ignored.status_code == 202
    assert unsigned.status_code == 401


async def test_the_api_error_format_does_not_leak_into_the_rest_of_the_app(
    tmp_path: Path,
) -> None:
    seeded = seed(tmp_path)
    app = _combined(seeded.path)
    async with client_for(app) as client:
        outside = await client.get("/nowhere")
        inside = await client.get("/api/nowhere")
        wrong = await client.get("/webhook")
    assert outside.status_code == 404 and outside.json() == {"detail": "Not Found"}
    assert inside.status_code == 404 and inside.json() == {"error": "not_found"}
    assert wrong.status_code == 405 and wrong.json() == {"detail": "Method Not Allowed"}
    assert "x-content-type-options" not in outside.headers  # API headers stay in the API


async def test_the_webhook_app_still_exposes_no_docs(tmp_path: Path) -> None:
    app = _combined(seed(tmp_path).path)
    async with client_for(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
        assert (await client.get("/api/openapi.json")).status_code == 200


@pytest.mark.parametrize(("mode", "has_api"), [("webhook", True), ("both", True)])
async def test_the_modes_with_a_server_mount_the_api(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
    mode: str,
    has_api: bool,
) -> None:
    _app_route(respx_mock)
    seeded = seed(tmp_path / "data")
    runtime = await _build(_settings(monkeypatch, mode, TRACE_PATH=str(seeded.path)))
    try:
        assert runtime.webhook_app is not None
        async with client_for(runtime.webhook_app) as client:
            response = await client.get("/api/status")
        assert (response.status_code == 200) is has_api
        assert response.json()["reviews"] == 3
    finally:
        for closer in runtime.closers:
            await closer()
        runtime.store.close()


async def test_polling_mode_has_no_api_at_all(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "polling", TRACE_PATH=str(tmp_path / "t.db")))
    try:
        assert runtime.webhook_app is None  # no HTTP server, so no routes (FR-19)
        assert runtime.trace_store is not None  # but the trace is still recorded
    finally:
        for closer in runtime.closers:
            await closer()
        runtime.store.close()


async def test_a_webhook_service_with_the_trace_off_answers_503_on_the_api(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    runtime = await _build(
        _settings(monkeypatch, "webhook", TRACE_ENABLED="false", TRACE_PATH=str(tmp_path / "x.db"))
    )
    try:
        assert runtime.webhook_app is not None
        async with client_for(runtime.webhook_app) as client:
            response = await client.get("/api/reviews")
            health = await client.get("/healthz")
        assert response.status_code == 503 and response.json() == {"error": "trace_unavailable"}
        assert health.status_code == 200
    finally:
        runtime.store.close()
