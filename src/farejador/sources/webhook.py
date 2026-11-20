# Filename: webhook.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Webhook source for server use (FR-1, NFR-1, NFR-5; design.md contract C-B).

The signature is checked on the raw bytes before anything is parsed, the answer is sent without
waiting for the review, and events are translated into the same triggers as the polling source.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from farejador.dispatcher import SubmitResult
from farejador.models import Trigger, TriggerSource

logger = logging.getLogger(__name__)

Submit = Callable[[Trigger], Awaitable[SubmitResult]]

MAX_BODY_BYTES = 5_000_000
_FIRST_REVIEW_ACTIONS = frozenset({"opened", "reopened", "ready_for_review"})


@dataclass(frozen=True, slots=True)
class Ignored:
    """A valid event that needs no work; ``reason`` is returned to GitHub for debugging."""

    reason: str


class MalformedPayload(Exception):
    """The body is JSON but does not look like the event it claims to be."""


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Check ``X-Hub-Signature-256`` in constant time over the raw body (NFR-1)."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def translate(
    event: str, payload: dict[str, Any], *, trigger_text: str, bot_login: str | None = None
) -> Trigger | Ignored:
    """Turn a GitHub event into a trigger, or explain why there is nothing to do."""
    try:
        if event == "pull_request":
            return _pull_request(payload)
        if event == "issue_comment":
            return _issue_comment(payload, trigger_text.lower(), bot_login)
    except (KeyError, TypeError, AttributeError) as exc:
        raise MalformedPayload(f"unexpected {event} payload") from exc
    return Ignored("unsupported-event")


def _installation(payload: dict[str, Any]) -> int | None:
    installation = payload.get("installation")
    return int(installation["id"]) if installation else None


def _pull_request(payload: dict[str, Any]) -> Trigger | Ignored:
    action = payload["action"]
    if action not in _FIRST_REVIEW_ACTIONS:
        return Ignored("unsupported-action")
    installation_id = _installation(payload)
    if installation_id is None:
        return Ignored("no-installation")
    pr = payload["pull_request"]
    if pr.get("state", "open") != "open":
        return Ignored("closed")
    if pr.get("draft", False):
        return Ignored("draft")
    return Trigger.first_review(
        repo=payload["repository"]["full_name"],
        installation_id=installation_id,
        pr_number=int(pr["number"]),
        sender_login=payload["sender"]["login"],
        source=TriggerSource.WEBHOOK,
        head_sha=pr["head"]["sha"],
    )


def _issue_comment(
    payload: dict[str, Any], trigger_text: str, bot_login: str | None
) -> Trigger | Ignored:
    if payload["action"] != "created":
        return Ignored("unsupported-action")
    installation_id = _installation(payload)
    if installation_id is None:
        return Ignored("no-installation")
    issue = payload["issue"]
    if "pull_request" not in issue:
        return Ignored("not-a-pr")
    comment = payload["comment"]
    author = comment["user"]["login"]
    if bot_login and author.lower() == bot_login.lower():
        return Ignored("own-event")
    if trigger_text not in (comment.get("body") or "").lower():
        return Ignored("no-command")
    return Trigger.command(
        repo=payload["repository"]["full_name"],
        installation_id=installation_id,
        pr_number=int(issue["number"]),
        comment_id=int(comment["id"]),
        sender_login=author,
        source=TriggerSource.WEBHOOK,
    )


def create_app(
    *,
    secret: str,
    submit: Submit,
    trigger_text: str = "@farejador",
    bot_login: str | None = None,
    mode: str = "webhook",
    max_body: int = MAX_BODY_BYTES,
) -> FastAPI:
    """Build the FastAPI app; ``submit`` is normally ``Dispatcher.submit``."""
    app = FastAPI(title="Farejador webhook", docs_url=None, redoc_url=None, openapi_url=None)
    pending: set[asyncio.Task[None]] = set()
    app.state.pending = pending

    async def _submit(trigger: Trigger, delivery: str) -> None:
        try:
            result = await submit(trigger)
        except Exception:
            logger.exception("could not submit trigger", extra={"delivery": delivery})
            return
        logger.info(
            "webhook trigger submitted",
            extra={"delivery": delivery, "key": trigger.key, "result": result.value},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    @app.post("/webhook")
    async def webhook(request: Request) -> JSONResponse:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_body:
            return JSONResponse({"error": "payload too large"}, status_code=413)
        body = await request.body()
        if len(body) > max_body:
            return JSONResponse({"error": "payload too large"}, status_code=413)

        if not verify_signature(secret, body, request.headers.get("x-hub-signature-256")):
            return JSONResponse({"error": "invalid signature"}, status_code=401)

        event = request.headers.get("x-github-event")
        if not event:
            return JSONResponse({"error": "missing X-GitHub-Event"}, status_code=400)
        delivery = request.headers.get("x-github-delivery", "")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise MalformedPayload("payload is not an object")
        except (json.JSONDecodeError, UnicodeDecodeError, MalformedPayload):
            return JSONResponse({"error": "malformed payload"}, status_code=400)

        if event == "ping":
            return JSONResponse({"status": "pong"}, status_code=200)
        try:
            outcome = translate(event, payload, trigger_text=trigger_text, bot_login=bot_login)
        except MalformedPayload:
            return JSONResponse({"error": "malformed payload"}, status_code=400)
        if isinstance(outcome, Ignored):
            return JSONResponse({"status": "ignored", "reason": outcome.reason}, status_code=202)

        task = asyncio.create_task(_submit(outcome, delivery))
        pending.add(task)
        task.add_done_callback(pending.discard)
        return JSONResponse({"status": "accepted"}, status_code=202)

    return app
