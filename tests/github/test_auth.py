# Filename: test_auth.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from farejador.github.auth import AppAuth
from farejador.github.errors import AuthError

BASE = "https://api.github.com"
TOKEN_URL = f"{BASE}/app/installations/55/access_tokens"


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _token_response(token: str, expires_in: int, clock: Clock) -> httpx.Response:
    from datetime import UTC, datetime

    expires = datetime.fromtimestamp(clock.now + expires_in, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return httpx.Response(201, json={"token": token, "expires_at": expires})


def test_app_jwt_is_rs256_with_short_ttl(keypair: tuple[str, str]) -> None:
    private, public = keypair
    clock = Clock(1_800_000_000)
    auth = AppAuth(123, private, clock=clock)
    token = auth.app_jwt()
    # The fake clock is far in the future, so skip the time checks done against the real clock.
    claims = jwt.decode(
        token,
        public,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == "123"
    assert claims["exp"] - claims["iat"] <= 10 * 60
    assert claims["iat"] < clock.now


def test_invalid_private_key_raises_auth_error() -> None:
    with pytest.raises(AuthError, match="private key"):
        AppAuth(1, "not a pem").app_jwt()


async def test_installation_token_is_cached(
    keypair: tuple[str, str], respx_mock: respx.MockRouter
) -> None:
    clock = Clock(1_800_000_000)
    route = respx_mock.post(TOKEN_URL).mock(return_value=_token_response("tok-1", 3600, clock))
    auth = AppAuth(1, keypair[0], clock=clock)
    assert await auth.token_for(55) == "tok-1"
    assert await auth.token_for(55) == "tok-1"
    assert route.call_count == 1
    assert route.calls.last.request.headers["Authorization"].startswith("Bearer ")


async def test_token_is_renewed_before_expiry(
    keypair: tuple[str, str], respx_mock: respx.MockRouter
) -> None:
    clock = Clock(1_800_000_000)
    route = respx_mock.post(TOKEN_URL).mock(
        side_effect=[_token_response("tok-1", 3600, clock), _token_response("tok-2", 3600, clock)]
    )
    auth = AppAuth(1, keypair[0], clock=clock, renew_margin_s=60)
    assert await auth.token_for(55) == "tok-1"
    clock.now += 3600 - 30
    assert await auth.token_for(55) == "tok-2"
    assert route.call_count == 2


async def test_invalidate_forces_a_new_token(
    keypair: tuple[str, str], respx_mock: respx.MockRouter
) -> None:
    clock = Clock(1_800_000_000)
    respx_mock.post(TOKEN_URL).mock(
        side_effect=[_token_response("tok-1", 3600, clock), _token_response("tok-2", 3600, clock)]
    )
    auth = AppAuth(1, keypair[0], clock=clock)
    assert await auth.token_for(55) == "tok-1"
    auth.invalidate(55)
    assert await auth.token_for(55) == "tok-2"


async def test_concurrent_requests_share_one_exchange(
    keypair: tuple[str, str], respx_mock: respx.MockRouter
) -> None:
    clock = Clock(1_800_000_000)
    route = respx_mock.post(TOKEN_URL).mock(return_value=_token_response("tok-1", 3600, clock))
    auth = AppAuth(1, keypair[0], clock=clock)
    tokens = await asyncio.gather(*(auth.token_for(55) for _ in range(8)))
    assert set(tokens) == {"tok-1"}
    assert route.call_count == 1


async def test_failed_exchange_raises_auth_error_without_token_text(
    keypair: tuple[str, str], respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(404, json={"message": "nope"}))
    with pytest.raises(AuthError, match="HTTP 404"):
        await AppAuth(1, keypair[0]).token_for(55)


async def test_malformed_exchange_response_raises_auth_error(
    keypair: tuple[str, str], respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(201, json={"oops": 1}))
    with pytest.raises(AuthError, match="unexpected"):
        await AppAuth(1, keypair[0]).token_for(55)
