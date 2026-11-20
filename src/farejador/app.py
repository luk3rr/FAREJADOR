# Filename: app.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Wires every component into a runnable service (ADR-1, ADR-5, ADR-10).

``build_runtime`` creates the shared core once; the mode decides which event sources feed it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI

from farejador.agent.llm import LLMClient, OpenRouterClient
from farejador.agent.runner import AgentRunner, Budget
from farejador.commands import CommandHandler
from farejador.config import ConfigError, Mode, Settings
from farejador.dispatcher import Dispatcher
from farejador.github.auth import AppAuth
from farejador.github.client import GitHubClient, resolve_bot_login
from farejador.log import configure_logging
from farejador.models import TriggerKind
from farejador.review.pipeline import FirstReview, PipelineConfig
from farejador.review.publisher import Publisher
from farejador.sources.polling import PollingSource
from farejador.sources.webhook import create_app
from farejador.state.store import StateStore
from farejador.workspace import Workspace

logger = logging.getLogger(__name__)

Serve = Callable[[FastAPI, str, int, asyncio.Event], Coroutine[Any, Any, None]]
Closer = Callable[[], Awaitable[None]]
SHUTDOWN_GRACE_S = 30.0


async def serve_uvicorn(app: FastAPI, host: str, port: int, stop: asyncio.Event) -> None:
    """Run the webhook app with uvicorn until ``stop`` is set or the server ends."""
    config = uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False)
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    waiting = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({serving, waiting}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        server.should_exit = True
        waiting.cancel()
        await serving


@dataclass
class Runtime:
    """The assembled service; ``run`` blocks until stopped or until a source fails."""

    settings: Settings
    store: StateStore
    dispatcher: Dispatcher
    polling: PollingSource | None = None
    webhook_app: FastAPI | None = None
    closers: list[Closer] = field(default_factory=list)

    async def run(self, stop: asyncio.Event | None = None, *, serve: Serve = serve_uvicorn) -> None:
        stop = stop or asyncio.Event()
        await self.dispatcher.start()
        sources: list[asyncio.Task[None]] = []
        if self.polling is not None:
            sources.append(asyncio.create_task(self.polling.run(), name="polling"))
        if self.webhook_app is not None:
            sources.append(
                asyncio.create_task(
                    serve(self.webhook_app, self.settings.host, self.settings.port, stop),
                    name="webhook",
                )
            )
        waiting = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait({*sources, waiting}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not waiting:
                    task.result()  # a source that ended early surfaces its error
        finally:
            stop.set()
            waiting.cancel()
            for task in sources:
                task.cancel()
            await asyncio.gather(*sources, waiting, return_exceptions=True)
            await self._shutdown()

    async def _shutdown(self) -> None:
        try:
            await asyncio.wait_for(self.dispatcher.stop(drain=True), timeout=SHUTDOWN_GRACE_S)
        except TimeoutError:
            logger.warning("shutdown grace period expired; cancelling running reviews")
            await self.dispatcher.stop(drain=False)
        for close in self.closers:
            await close()
        self.store.close()


async def build_runtime(
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    http: httpx.AsyncClient | None = None,
) -> Runtime:
    """Create the components for ``settings.mode``; tests may replace ``llm`` and ``http``."""
    configure_logging(settings.log_level, settings.secret_values())
    closers: list[Closer] = []
    owned_http = http is None
    http = http or httpx.AsyncClient(timeout=30.0)
    if owned_http:
        closers.append(http.aclose)

    private_key = settings.github_private_key_path.read_text(encoding="utf-8")
    auth = AppAuth(settings.github_app_id, private_key, http=http)
    client = GitHubClient(auth, http=http)
    bot_login = await resolve_bot_login(client, settings.bot_login)

    if llm is None:
        openrouter = OpenRouterClient(settings.openrouter_api_key.get_secret_value())
        closers.append(openrouter.aclose)
        llm = openrouter

    store = StateStore(settings.state_path).open()
    runner = AgentRunner(
        llm,
        settings.model,
        Budget(settings.max_steps, settings.max_tokens, float(settings.max_seconds)),
    )
    publisher = Publisher(client)
    config = PipelineConfig(
        mode=settings.mode.value,
        max_files=settings.max_files,
        ignore_globs=tuple(settings.ignore_globs),
        trigger_text=settings.trigger_text,
        bot_login=bot_login,
    )
    review = FirstReview(
        client=client,
        token_for=auth.token_for,
        store=store,
        runner=runner,
        publisher=publisher,
        open_workspace=Workspace.open,
        config=config,
    )
    commands = CommandHandler(
        client=client,
        token_for=auth.token_for,
        store=store,
        runner=runner,
        publisher=publisher,
        open_workspace=Workspace.open,
        review=review,
        config=config,
    )
    dispatcher = Dispatcher(
        store,
        {TriggerKind.FIRST_REVIEW: review.run, TriggerKind.COMMAND: commands.run},
        workers=settings.workers,
        bot_login=bot_login,
    )

    polling: PollingSource | None = None
    if settings.mode in (Mode.POLLING, Mode.BOTH):
        polling = PollingSource(
            client=client,
            store=store,
            submit=dispatcher.submit,
            trigger_text=settings.trigger_text,
            bot_login=bot_login,
            interval_s=float(settings.poll_interval_s),
        )
    webhook_app: FastAPI | None = None
    if settings.mode in (Mode.WEBHOOK, Mode.BOTH):
        secret = settings.webhook_secret
        if secret is None:  # Settings already enforces this; keep it explicit under ``python -O``
            raise ConfigError("FAREJADOR_WEBHOOK_SECRET is required for the webhook modes")
        webhook_app = create_app(
            secret=secret.get_secret_value(),
            submit=dispatcher.submit,
            trigger_text=settings.trigger_text,
            bot_login=bot_login,
            mode=settings.mode.value,
        )
    logger.info(
        "farejador ready",
        extra={"mode": settings.mode.value, "model": settings.model, "bot": bot_login},
    )
    return Runtime(settings, store, dispatcher, polling, webhook_app, closers)
