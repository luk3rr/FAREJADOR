# Filename: auth.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""GitHub App authentication behind an interface (ADR-6, FR-21)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

import httpx
import jwt

from farejador.github.errors import AuthError

# Installation tokens are narrowed to what each use needs, so a token that clones code cannot write
# it. ``contents: write`` exists only for resolving review threads, which GitHub requires it for.
CLONE_PERMISSIONS: Mapping[str, str] = {"contents": "read", "metadata": "read"}
API_PERMISSIONS: Mapping[str, str] = {
    "contents": "read",
    "issues": "write",
    "pull_requests": "write",
    "metadata": "read",
}
RESOLVE_PERMISSIONS: Mapping[str, str] = {
    "contents": "write",
    "pull_requests": "write",
    "metadata": "read",
}

_JWT_TTL_S = 9 * 60
_JWT_BACKDATE_S = 60


class GitHubAuth(Protocol):
    """What the rest of the system needs from an authentication method."""

    def app_jwt(self) -> str:
        """A short-lived token that identifies the App itself."""
        ...

    async def token_for(
        self, installation_id: int, permissions: Mapping[str, str] | None = None
    ) -> str:
        """A valid installation token, renewed transparently when it is about to expire.

        ``permissions`` narrows the token to those permissions; None means all the App has.
        """
        ...

    def invalidate(self, installation_id: int) -> None:
        """Forget a cached installation token that GitHub rejected."""
        ...


_Key = tuple[int, tuple[tuple[str, str], ...]]


def _reason(response: httpx.Response) -> str:
    """GitHub's own explanation of a refusal; it never contains the token."""
    try:
        return str(response.json().get("message", response.reason_phrase))[:200]
    except (ValueError, AttributeError):
        return response.reason_phrase


class AppAuth:
    """Signs an App JWT (RS256) and exchanges it for cached installation tokens."""

    def __init__(
        self,
        app_id: int,
        private_key: str,
        *,
        http: httpx.AsyncClient | None = None,
        base_url: str = "https://api.github.com",
        clock: Callable[[], float] = time.time,
        renew_margin_s: float = 60.0,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._base_url = base_url.rstrip("/")
        self._clock = clock
        self._margin = renew_margin_s
        self._cache: dict[_Key, tuple[str, float]] = {}
        self._locks: dict[_Key, asyncio.Lock] = {}

    def app_jwt(self) -> str:
        now = int(self._clock())
        payload = {
            "iat": now - _JWT_BACKDATE_S,
            "exp": now + _JWT_TTL_S,
            "iss": str(self._app_id),
        }
        try:
            return jwt.encode(payload, self._private_key, algorithm="RS256")
        except (ValueError, TypeError, jwt.PyJWTError) as exc:
            raise AuthError("could not sign the GitHub App JWT; check the private key") from exc

    def invalidate(self, installation_id: int) -> None:
        for key in [key for key in self._cache if key[0] == installation_id]:
            del self._cache[key]

    async def token_for(
        self, installation_id: int, permissions: Mapping[str, str] | None = None
    ) -> str:
        key: _Key = (installation_id, tuple(sorted((permissions or {}).items())))
        cached = self._cache.get(key)
        if cached is not None and cached[1] - self._margin > self._clock():
            return cached[0]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached is not None and cached[1] - self._margin > self._clock():
                return cached[0]
            token, expires_at = await self._fetch(installation_id, permissions)
            self._cache[key] = (token, expires_at)
            return token

    async def _fetch(
        self, installation_id: int, permissions: Mapping[str, str] | None
    ) -> tuple[str, float]:
        response = await self._http.post(
            f"{self._base_url}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self.app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"permissions": dict(permissions)} if permissions else None,
        )
        if response.status_code != 201:
            raise AuthError(
                f"could not obtain an installation token (HTTP {response.status_code}): "
                f"{_reason(response)}"
            )
        data = response.json()
        try:
            token = str(data["token"])
            expires_at = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise AuthError("unexpected installation token response") from exc
        return token, expires_at.timestamp()
