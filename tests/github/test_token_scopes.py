# Filename: test_token_scopes.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Every use of the App gets a token narrowed to what it needs; only resolving a review thread
gets ``contents: write``, which GitHub requires for that mutation."""

import json

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from tests.factories import FakeAuth, SleepRecorder

from farejador.github.auth import (
    API_PERMISSIONS,
    CLONE_PERMISSIONS,
    RESOLVE_PERMISSIONS,
    AppAuth,
)
from farejador.github.client import GitHubClient
from farejador.github.errors import AuthError

TOKEN_URL = "https://api.github.com/app/installations/55/access_tokens"
EXPIRES = "2999-01-01T00:00:00Z"


@pytest.fixture(scope="module")
def private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_only_the_resolve_scope_can_write_contents() -> None:
    assert CLONE_PERMISSIONS == {"contents": "read", "metadata": "read"}
    assert API_PERMISSIONS["contents"] == "read"
    assert RESOLVE_PERMISSIONS["contents"] == "write"
    scopes = {"clone": CLONE_PERMISSIONS, "api": API_PERMISSIONS}
    for name, scope in scopes.items():
        assert scope["contents"] != "write", name
    assert set(RESOLVE_PERMISSIONS) <= {"contents", "pull_requests", "metadata"}


async def test_the_requested_permissions_are_sent_and_each_scope_has_its_own_token(
    private_key: str, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(201, json={"token": "tok-read", "expires_at": EXPIRES}),
            httpx.Response(201, json={"token": "tok-write", "expires_at": EXPIRES}),
        ]
    )
    auth = AppAuth(1, private_key)
    assert await auth.token_for(55, CLONE_PERMISSIONS) == "tok-read"
    assert await auth.token_for(55, CLONE_PERMISSIONS) == "tok-read"  # cached
    assert await auth.token_for(55, RESOLVE_PERMISSIONS) == "tok-write"
    assert route.call_count == 2
    sent = [json.loads(call.request.content) for call in route.calls]
    assert sent == [
        {"permissions": dict(CLONE_PERMISSIONS)},
        {"permissions": dict(RESOLVE_PERMISSIONS)},
    ]


async def test_without_permissions_no_body_is_sent_and_invalidate_clears_every_scope(
    private_key: str, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(201, json={"token": "tok", "expires_at": EXPIRES})
    )
    auth = AppAuth(1, private_key)
    await auth.token_for(55)
    assert route.calls.last.request.content == b""
    await auth.token_for(55, CLONE_PERMISSIONS)
    assert route.call_count == 2
    auth.invalidate(55)
    await auth.token_for(55)
    await auth.token_for(55, CLONE_PERMISSIONS)
    assert route.call_count == 4


async def test_a_refused_token_explains_why_without_leaking_anything(
    private_key: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            422, json={"message": "The permissions requested are not granted to this installation."}
        )
    )
    with pytest.raises(AuthError, match=r"HTTP 422.*not granted to this installation"):
        await AppAuth(1, private_key).token_for(55, RESOLVE_PERMISSIONS)


async def test_ordinary_calls_use_the_api_scope_and_resolving_uses_the_write_scope(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("https://api.github.com/repos/o/r/issues/1/comments").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    respx_mock.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(
            200, json={"data": {"resolveReviewThread": {"thread": {"id": "T"}}}}
        )
    )
    auth = FakeAuth()
    client = GitHubClient(auth, sleep=SleepRecorder())
    await client.post_comment(9, "o/r", 1, "hi")
    await client.resolve_review_thread(9, "T")
    assert auth.requested == [dict(API_PERMISSIONS), dict(RESOLVE_PERMISSIONS)]
