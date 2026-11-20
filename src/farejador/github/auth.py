# Filename: auth.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""GitHub App authentication behind an interface (ADR-6, FR-21)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import httpx
import jwt

from farejador.github.errors import AuthError

_JWT_TTL_S = 9 * 60
_JWT_BACKDATE_S = 60


class GitHubAuth(Protocol):
    """What the rest of the system needs from an authentication method."""

    def app_jwt(self) -> str:
        """A short-lived token that identifies the App itself."""
        ...

    async def token_for(self, installation_id: int) -> str:
        """A valid installation token, renewed transparently when it is about to expire."""
        ...

    def invalidate(self, installation_id: int) -> None:
        """Forget a cached installation token that GitHub rejected."""
        ...


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
        self._cache: dict[int, tuple[str, float]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

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
        self._cache.pop(installation_id, None)

    async def token_for(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached is not None and cached[1] - self._margin > self._clock():
            return cached[0]
        lock = self._locks.setdefault(installation_id, asyncio.Lock())
        async with lock:
            cached = self._cache.get(installation_id)
            if cached is not None and cached[1] - self._margin > self._clock():
                return cached[0]
            token, expires_at = await self._fetch(installation_id)
            self._cache[installation_id] = (token, expires_at)
            return token

    async def _fetch(self, installation_id: int) -> tuple[str, float]:
        response = await self._http.post(
            f"{self._base_url}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self.app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if response.status_code != 201:
            raise AuthError(f"could not obtain an installation token (HTTP {response.status_code})")
        data = response.json()
        try:
            token = str(data["token"])
            expires_at = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise AuthError("unexpected installation token response") from exc
        return token, expires_at.timestamp()
