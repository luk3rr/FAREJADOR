# Filename: webhook_env.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Helpers to drive the webhook app in-process with signed GitHub-like requests."""

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI

from farejador.dispatcher import SubmitResult
from farejador.models import Trigger
from farejador.sources.webhook import create_app

SECRET = "whsec-test-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def pull_request_event(
    action: str = "opened", *, draft: bool = False, state: str = "open", installation: bool = True
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": action,
        "number": 7,
        "pull_request": {
            "number": 7,
            "state": state,
            "draft": draft,
            "head": {"sha": "abc1234def"},
            "user": {"login": "alice"},
        },
        "repository": {"full_name": "o/r"},
        "sender": {"login": "alice"},
    }
    if installation:
        payload["installation"] = {"id": 55}
    return payload


def comment_event(
    body: str = "@farejador please re-check",
    *,
    action: str = "created",
    on_pr: bool = True,
    author: str = "bob",
    comment_id: int = 901,
) -> dict[str, Any]:
    issue: dict[str, Any] = {"number": 7}
    if on_pr:
        issue["pull_request"] = {"url": "https://api.github.com/repos/o/r/pulls/7"}
    return {
        "action": action,
        "issue": issue,
        "comment": {"id": comment_id, "body": body, "user": {"login": author}},
        "repository": {"full_name": "o/r"},
        "installation": {"id": 55},
    }


@dataclass
class Recorder:
    triggers: list[Trigger] = field(default_factory=list)
    result: SubmitResult = SubmitResult.ENQUEUED

    async def __call__(self, trigger: Trigger) -> SubmitResult:
        self.triggers.append(trigger)
        return self.result


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def post(
    client: httpx.AsyncClient,
    event: str,
    payload: dict[str, Any] | bytes,
    *,
    secret: str = SECRET,
    signature: str | None = "auto",
    extra_headers: dict[str, str] | None = None,
    delivery: str = "d-1",
) -> httpx.Response:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery}
    if signature == "auto":
        headers["X-Hub-Signature-256"] = sign(body, secret)
    elif signature is not None:
        headers["X-Hub-Signature-256"] = signature
    headers.update(extra_headers or {})
    return await client.post("/webhook", content=body, headers=headers)


async def drain(app: FastAPI) -> None:
    """Wait for the background submissions started by the app."""
    import asyncio

    while app.state.pending:
        await asyncio.gather(*list(app.state.pending))


__all__ = [
    "SECRET",
    "Recorder",
    "client_for",
    "comment_event",
    "create_app",
    "drain",
    "post",
    "pull_request_event",
    "sign",
]
