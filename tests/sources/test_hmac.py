# Filename: test_hmac.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import hmac

import pytest
from tests.webhook_env import SECRET, sign

from farejador.sources.webhook import verify_signature

BODY = b'{"action": "opened"}'


def test_a_correct_signature_is_accepted() -> None:
    assert verify_signature(SECRET, BODY, sign(BODY)) is True


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "sha256=",
        "sha256=deadbeef",
        "sha1=" + sign(BODY).removeprefix("sha256="),
        sign(BODY).removeprefix("sha256="),
        sign(BODY).upper(),
        sign(BODY) + "00",
    ],
)
def test_missing_or_malformed_signatures_are_rejected(header: str | None) -> None:
    assert verify_signature(SECRET, BODY, header) is False


def test_a_signature_made_with_another_secret_is_rejected() -> None:
    assert verify_signature(SECRET, BODY, sign(BODY, "other-secret")) is False


def test_a_tampered_body_is_rejected() -> None:
    assert verify_signature(SECRET, BODY + b" ", sign(BODY)) is False


def test_the_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr("farejador.sources.webhook.hmac.compare_digest", spy)
    verify_signature(SECRET, BODY, sign(BODY))
    assert len(calls) == 1
