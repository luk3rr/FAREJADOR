# Filename: test_serving.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The server hands out the dashboard with strict headers, changing nothing else (FR-22, FR-23)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from tests.test_app import _app_route, _build, _settings
from tests.webhook_env import Recorder, client_for, post, pull_request_event

import farejador.web as web
from farejador.sources.webhook import create_app
from farejador.web import CONTENT_SECURITY_POLICY, SECURITY_HEADERS, install_web

INDEX = "<!doctype html><title>Farejador</title><script type=module src=/assets/main.js></script>"


def make_static(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "main.js").write_text("export const ok = true;\n")
    (root / "assets" / "styles.css").write_text("body{margin:0}\n")
    (root / "assets" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return root


def app_with_web(root: Path) -> FastAPI:
    app = create_app(secret="whsec-test-secret", submit=Recorder())
    assert install_web(app, root) is True
    return app


@asynccontextmanager
async def served(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app_with_web(make_static(tmp_path))) as client:
        yield client


def directives(policy: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *sources = part.split()
        parsed[name] = sources
    return parsed


async def test_the_page_and_the_assets_are_served_with_the_right_types(tmp_path: Path) -> None:
    async with served(tmp_path) as client:
        page = await client.get("/")
        script = await client.get("/assets/main.js")
        style = await client.get("/assets/styles.css")
        icon = await client.get("/assets/icon.png")
    assert page.status_code == 200 and page.text == INDEX
    assert page.headers["content-type"].startswith("text/html")
    assert "javascript" in script.headers["content-type"] and script.status_code == 200
    assert style.headers["content-type"].startswith("text/css")
    assert icon.headers["content-type"] == "image/png"


async def test_every_response_of_the_dashboard_carries_the_security_headers(tmp_path: Path) -> None:
    async with served(tmp_path) as client:
        responses = [
            await client.get(path) for path in ("/", "/assets/main.js", "/assets/styles.css")
        ]
    for response in responses:
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value, f"{name} on {response.url.path}"


def test_the_content_security_policy_allows_only_the_own_origin() -> None:
    parsed = directives(CONTENT_SECURITY_POLICY)
    assert parsed["default-src"] == ["'none'"]
    for name in ("script-src", "style-src", "img-src", "connect-src"):
        assert parsed[name] == ["'self'"], name
    for name in ("base-uri", "form-action", "object-src"):
        assert parsed[name] == ["'none'"], name
    assert parsed["frame-ancestors"] == ["'none'"]
    for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "*", "data:", "blob:", "http:", "https:"):
        assert forbidden not in CONTENT_SECURITY_POLICY.split(), forbidden


def test_the_other_headers_are_the_expected_ones() -> None:
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["Referrer-Policy"] == "no-referrer"
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert SECURITY_HEADERS["Cross-Origin-Opener-Policy"] == "same-origin"
    assert SECURITY_HEADERS["Cache-Control"] == "no-cache"
    assert "camera=()" in SECURITY_HEADERS["Permissions-Policy"]


async def test_files_are_revalidated_with_an_etag(tmp_path: Path) -> None:
    async with served(tmp_path) as client:
        first = await client.get("/assets/main.js")
        etag = first.headers["etag"]
        again = await client.get("/assets/main.js", headers={"If-None-Match": etag})
        page = await client.get("/")
        page_again = await client.get("/", headers={"If-None-Match": page.headers["etag"]})
    assert again.status_code == 304
    assert page_again.status_code == 304
    assert first.headers["cache-control"] == "no-cache"


async def test_head_works_and_has_no_body(tmp_path: Path) -> None:
    async with served(tmp_path) as client:
        page = await client.head("/")
        script = await client.head("/assets/main.js")
    assert page.status_code == 200 and page.content == b""
    assert script.status_code == 200 and script.content == b""
    assert page.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/", "/assets/main.js"])
async def test_nothing_can_be_written_through_the_dashboard_routes(
    tmp_path: Path, method: str, path: str
) -> None:
    async with served(tmp_path) as client:
        response = await client.request(method, path)
    assert response.status_code == 405


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../index.html",
        "/assets/%2e%2e/index.html",
        "/assets/..%2findex.html",
        "/assets/%2e%2e%2f%2e%2e%2fetc/passwd",
        "/assets//etc/passwd",
        "/assets/..\\index.html",
        "/assets/nothing.js",
        "/assets/",
    ],
)
async def test_the_assets_route_cannot_reach_outside_its_folder(tmp_path: Path, path: str) -> None:
    async with served(tmp_path) as client:
        response = await client.get(path)
    assert INDEX not in response.text
    assert "root:" not in response.text
    assert (
        response.status_code != 200
        or response.headers["content-type"].startswith("text/html") is False
    )


async def test_the_rest_of_the_service_is_exactly_as_before(tmp_path: Path) -> None:
    async with served(tmp_path) as client:
        health = await client.get("/healthz")
        unknown = await client.get("/anything-else")
        wrong_method = await client.get("/webhook")
        accepted = await post(client, "pull_request", pull_request_event())
        unsigned = await post(client, "ping", {"zen": "x"}, signature=None)
    assert health.json() == {"status": "ok", "mode": "webhook"}
    assert unknown.status_code == 404 and unknown.json() == {"detail": "Not Found"}
    assert "content-security-policy" not in unknown.headers  # the headers stay on the dashboard
    assert wrong_method.status_code == 405 and wrong_method.json() == {
        "detail": "Method Not Allowed"
    }
    assert accepted.status_code == 202 and unsigned.status_code == 401


async def test_the_dashboard_does_not_swallow_the_api(tmp_path: Path) -> None:
    from farejador.api.routes import create_api

    app = app_with_web(make_static(tmp_path))
    app.mount("/api", create_api(tmp_path / "absent.db"))
    async with client_for(app) as client:
        api = await client.get("/api/status")
        page = await client.get("/")
    assert api.status_code == 503 and api.json() == {"error": "trace_unavailable"}
    assert page.status_code == 200


def test_without_the_compiled_files_the_dashboard_is_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(secret="s", submit=Recorder())
    with caplog.at_level(logging.WARNING):
        assert install_web(app, tmp_path / "missing") is False
    assert any("dashboard not installed" in r.getMessage() for r in caplog.records)
    (tmp_path / "half").mkdir()
    (tmp_path / "half" / "index.html").write_text(INDEX)  # no assets folder
    assert install_web(app, tmp_path / "half") is False


async def test_a_service_without_the_build_still_answers_404_on_the_root(tmp_path: Path) -> None:
    app = create_app(secret="s", submit=Recorder())
    install_web(app, tmp_path / "missing")
    async with client_for(app) as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/healthz")).status_code == 200


@pytest.mark.parametrize(("mode", "expected"), [("webhook", 200), ("both", 200)])
async def test_the_modes_with_a_server_serve_the_dashboard(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
    mode: str,
    expected: int,
) -> None:
    _app_route(respx_mock)
    monkeypatch.setattr(web, "DEFAULT_STATIC_DIR", make_static(tmp_path))
    runtime = await _build(_settings(monkeypatch, mode, TRACE_PATH=str(tmp_path / "t.db")))
    try:
        assert runtime.webhook_app is not None
        async with client_for(runtime.webhook_app) as client:
            response = await client.get("/")
        assert response.status_code == expected
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    finally:
        for closer in runtime.closers:
            await closer()
        runtime.store.close()


async def test_polling_mode_has_no_dashboard_at_all(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    monkeypatch.setattr(web, "DEFAULT_STATIC_DIR", make_static(tmp_path))
    runtime = await _build(_settings(monkeypatch, "polling", TRACE_PATH=str(tmp_path / "t.db")))
    try:
        assert runtime.webhook_app is None  # no HTTP server, so no dashboard (FR-23)
    finally:
        for closer in runtime.closers:
            await closer()
        runtime.store.close()
