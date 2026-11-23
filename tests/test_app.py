# Filename: test_app.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
import respx
from tests.factories import make_first
from tests.llm_fakes import ScriptedLLM

from farejador.app import Runtime, build_runtime
from farejador.config import Mode, Settings
from farejador.github.errors import GitHubApiError
from farejador.models import TriggerKind

API = "https://api.github.com"


def _settings(monkeypatch: pytest.MonkeyPatch, mode: str, **extra: str) -> Settings:
    monkeypatch.setenv("FAREJADOR_MODE", mode)
    for name, value in extra.items():
        monkeypatch.setenv(f"FAREJADOR_{name}", value)
    return Settings.load()


def _app_route(router: respx.MockRouter) -> respx.Route:
    return router.get(f"{API}/app").mock(
        return_value=httpx.Response(200, json={"slug": "farejador"})
    )


async def _build(settings: Settings) -> Runtime:
    return await build_runtime(settings, llm=ScriptedLLM([]), http=httpx.AsyncClient())


async def test_polling_mode_builds_only_the_poller(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    route = _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "polling"))
    try:
        assert runtime.polling is not None
        assert runtime.webhook_app is None
        assert route.call_count == 1  # the bot login came from GET /app
        assert runtime.polling._bot_login == "farejador[bot]"
    finally:
        runtime.store.close()


async def test_webhook_mode_builds_only_the_webhook_app(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "webhook"))
    try:
        assert runtime.polling is None
        assert runtime.webhook_app is not None
        transport = httpx.ASGITransport(app=runtime.webhook_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            health = await client.get("/healthz")
        assert health.json() == {"status": "ok", "mode": "webhook"}
    finally:
        runtime.store.close()


async def test_both_mode_builds_both_sources_sharing_one_dispatcher(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "both"))
    try:
        assert runtime.polling is not None
        assert runtime.webhook_app is not None
        assert runtime.settings.mode is Mode.BOTH
        assert set(runtime.dispatcher._handlers) == {TriggerKind.FIRST_REVIEW, TriggerKind.COMMAND}
        assert runtime.dispatcher._worker_count == 2
    finally:
        runtime.store.close()


async def test_a_configured_bot_login_skips_the_lookup(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    route = _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "polling", BOT_LOGIN="mine[bot]"))
    try:
        assert route.call_count == 0
        assert runtime.polling is not None
        assert runtime.polling._bot_login == "mine[bot]"
    finally:
        runtime.store.close()


async def test_a_failing_bot_lookup_stops_startup_before_anything_is_opened(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{API}/app").mock(return_value=httpx.Response(404, json={"message": "no"}))
    settings = _settings(monkeypatch, "polling")
    with pytest.raises(GitHubApiError):
        await _build(settings)
    assert not settings.state_path.exists()


async def test_configuration_values_reach_the_components(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    _app_route(respx_mock)
    settings = _settings(
        monkeypatch,
        "polling",
        WORKERS="3",
        MAX_STEPS="7",
        MAX_FILES="5",
        TRIGGER_TEXT="/sniff",
        IGNORE_GLOBS="*.snap,docs/**",
    )
    runtime = await _build(settings)
    try:
        assert runtime.dispatcher._worker_count == 3
        review = runtime.dispatcher._handlers[TriggerKind.FIRST_REVIEW].__self__  # type: ignore[attr-defined]
        assert review._config.max_files == 5
        assert review._config.trigger_text == "/sniff"
        assert review._config.ignore_globs == ("*.snap", "docs/**")
        assert review._runner._budget.max_steps == 7
        assert runtime.polling is not None
        assert runtime.polling._trigger_text == "/sniff"
    finally:
        runtime.store.close()


# -- lifecycle -------------------------------------------------------------------------------


def _bare_runtime(settings: Settings, tmp_path: Path, **kwargs: object) -> Runtime:
    from farejador.dispatcher import Dispatcher
    from farejador.state.store import StateStore

    store = StateStore(tmp_path / "life.db").open()
    dispatcher = Dispatcher(store, kwargs.pop("handlers", {}), workers=1)  # type: ignore[arg-type]
    return Runtime(settings, store, dispatcher, **kwargs)  # type: ignore[arg-type]


async def test_run_starts_the_sources_stops_on_request_and_cleans_up(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    installations = respx_mock.get(f"{API}/app/installations").mock(
        return_value=httpx.Response(200, json=[])
    )
    runtime = await _build(_settings(monkeypatch, "both"))
    assert runtime.polling is not None
    runtime.polling._interval = 0.01
    closed: list[str] = []

    async def closer() -> None:
        closed.append("closed")

    runtime.closers.append(closer)
    served: list[tuple[str, int]] = []

    async def fake_serve(app: object, host: str, port: int, stop: asyncio.Event) -> None:
        served.append((host, port))
        await stop.wait()

    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop, serve=fake_serve))
    for _ in range(200):
        if installations.call_count >= 2 and served:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert served == [("127.0.0.1", 8080)]
    assert installations.call_count >= 2  # it kept polling until told to stop
    assert closed == ["closed"]
    assert runtime.store._conn is None


async def test_a_source_that_fails_stops_the_service_and_surfaces_the_error(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "webhook"))
    runtime.polling = None

    async def broken_serve(*_args: object) -> None:
        raise RuntimeError("port already in use")

    with pytest.raises(RuntimeError, match="port already in use"):
        await asyncio.wait_for(runtime.run(serve=broken_serve), timeout=5)  # type: ignore[arg-type]
    assert runtime.store._conn is None


async def test_shutdown_cancels_reviews_that_do_not_finish_within_the_grace_period(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("farejador.app.SHUTDOWN_GRACE_S", 0.1)
    started = asyncio.Event()

    async def hang(_trigger: object) -> None:
        started.set()
        await asyncio.Event().wait()

    settings = _settings(monkeypatch, "polling")
    runtime = _bare_runtime(settings, tmp_path, handlers={TriggerKind.FIRST_REVIEW: hang})
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await asyncio.sleep(0.05)
    await runtime.dispatcher.submit(make_first(1))
    await asyncio.wait_for(started.wait(), timeout=2)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    record = runtime.store._db() if runtime.store._conn else None
    assert record is None  # the store is closed after the forced shutdown


@pytest.mark.skipif(
    sys.platform == "win32", reason="the trace store opens a POSIX-only default path"
)
async def test_the_default_dependencies_are_created_and_closed_on_shutdown(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    from farejador.agent.llm import OpenRouterClient

    _app_route(respx_mock)
    runtime = await build_runtime(_settings(monkeypatch, "polling"))
    runner = runtime.dispatcher._handlers[TriggerKind.FIRST_REVIEW].__self__  # type: ignore[attr-defined]
    assert isinstance(runner._runner._llm, OpenRouterClient)
    assert len(runtime.closers) == 2  # the HTTP client and the OpenRouter client

    assert runtime.polling is not None
    respx_mock.get(f"{API}/app/installations").mock(return_value=httpx.Response(200, json=[]))
    runtime.polling._interval = 0.01
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(runtime.run(stop), timeout=5)
    assert runtime.store._conn is None


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_the_real_http_server_serves_the_webhook_app_until_asked_to_stop(
    farejador_env: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    from farejador.app import serve_uvicorn

    respx_mock.route(host="127.0.0.1").pass_through()
    _app_route(respx_mock)
    runtime = await _build(_settings(monkeypatch, "webhook"))
    assert runtime.webhook_app is not None
    port = _free_port()
    stop = asyncio.Event()
    server = asyncio.create_task(serve_uvicorn(runtime.webhook_app, "127.0.0.1", port, stop))
    try:
        async with httpx.AsyncClient() as client:
            body: dict[str, str] = {}
            for _ in range(100):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/healthz")
                    body = response.json()
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
        assert body == {"status": "ok", "mode": "webhook"}
    finally:
        stop.set()
        await asyncio.wait_for(server, timeout=5)
        runtime.store.close()


# -- trace -----------------------------------------------------------------------------------


async def test_the_trace_is_opened_with_the_configured_values_and_closed_on_shutdown(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    path = tmp_path / "trace" / "t.db"
    runtime = await _build(
        _settings(
            monkeypatch,
            "polling",
            TRACE_PATH=str(path),
            TRACE_MAX_ITEM_CHARS="500",
            MAX_STEPS="9",
        )
    )
    try:
        assert runtime.trace_store is not None and path.exists()
        review = runtime.dispatcher._handlers[TriggerKind.FIRST_REVIEW].__self__  # type: ignore[attr-defined]
        recorder = review._recorder
        assert recorder._model == "test/model"
        assert recorder._budgets["max_steps"] == 9
        assert runtime.trace_store._max_item_chars == 500
        for closer in runtime.closers:
            await closer()
        with pytest.raises(Exception, match="not open"):
            runtime.trace_store.count_runs()
    finally:
        runtime.store.close()


async def test_the_trace_can_be_switched_off(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    path = tmp_path / "off.db"
    runtime = await _build(
        _settings(monkeypatch, "polling", TRACE_ENABLED="false", TRACE_PATH=str(path))
    )
    try:
        assert runtime.trace_store is None and not path.exists()
    finally:
        runtime.store.close()


async def test_an_unusable_trace_file_never_stops_the_service(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _app_route(respx_mock)
    broken = tmp_path / "trace.db"
    broken.write_bytes(b"this is not a sqlite database" * 50)
    runtime = await _build(_settings(monkeypatch, "polling", TRACE_PATH=str(broken)))
    try:
        assert runtime.trace_store is None
        assert runtime.polling is not None  # the service itself is up
        captured = capsys.readouterr()
        assert "trace disabled" in captured.out + captured.err
    finally:
        runtime.store.close()


async def test_running_the_service_purges_old_traces_in_the_background(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from tests.trace.helpers import begin

    from farejador.trace.store import TraceStore

    _app_route(respx_mock)
    respx_mock.get(f"{API}/app/installations").mock(return_value=httpx.Response(200, json=[]))
    old_clock = datetime.now(UTC) - timedelta(days=40)
    trace_store = TraceStore(tmp_path / "t.db", clock=lambda: old_clock).open()
    begin(trace_store)
    trace_store._clock = lambda: datetime.now(UTC)
    runtime = _bare_runtime(_settings(monkeypatch, "polling"), tmp_path, trace_store=trace_store)
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if trace_store.count_runs() == 0:
            break
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    try:
        assert trace_store.count_runs() == 0
    finally:
        trace_store.close()
        runtime.store.close()


def test_the_trace_records_the_release_version_when_the_image_sets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from farejador import __version__
    from farejador.app import app_version

    monkeypatch.delenv("FAREJADOR_APP_VERSION", raising=False)
    assert app_version() == __version__  # run from source
    monkeypatch.setenv("FAREJADOR_APP_VERSION", "")
    assert app_version() == __version__  # an empty value does not count
    monkeypatch.setenv("FAREJADOR_APP_VERSION", "0.1.2")
    assert app_version() == "0.1.2"


async def test_the_recorder_gets_the_version_of_the_release(
    farejador_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
) -> None:
    _app_route(respx_mock)
    monkeypatch.setenv("FAREJADOR_APP_VERSION", "0.3.4")
    runtime = await _build(_settings(monkeypatch, "polling", TRACE_PATH=str(tmp_path / "v.db")))
    try:
        review = runtime.dispatcher._handlers[TriggerKind.FIRST_REVIEW].__self__  # type: ignore[attr-defined]
        assert review._recorder._app_version == "0.3.4"
    finally:
        for closer in runtime.closers:
            await closer()
        runtime.store.close()
