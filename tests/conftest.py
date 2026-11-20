# Filename: conftest.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from collections.abc import Iterator
from pathlib import Path

import pytest

from farejador.state.store import StateStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[StateStore]:
    with StateStore(tmp_path / "state.db") as opened:
        yield opened


@pytest.fixture(autouse=True)
def _close_state_stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every StateStore a test opens, including those built by helper builders."""
    opened: list[StateStore] = []
    original = StateStore.open

    def tracking_open(self: StateStore) -> StateStore:
        opened.append(self)
        return original(self)

    monkeypatch.setattr(StateStore, "open", tracking_open)
    yield
    for store in opened:
        store.close()


@pytest.fixture
def farejador_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A complete valid FAREJADOR_* environment with a real RSA key; returns the key path."""
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    for name in list(os.environ):
        if name.startswith("FAREJADOR_"):
            monkeypatch.delenv(name)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = tmp_path / "app.pem"
    pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("FAREJADOR_GITHUB_APP_ID", "123")
    monkeypatch.setenv("FAREJADOR_GITHUB_PRIVATE_KEY_PATH", str(pem))
    monkeypatch.setenv("FAREJADOR_OPENROUTER_API_KEY", "sk-or-v1-testkey0000000000")
    monkeypatch.setenv("FAREJADOR_MODEL", "test/model")
    monkeypatch.setenv("FAREJADOR_STATE_PATH", str(tmp_path / "state" / "farejador.db"))
    monkeypatch.setenv("FAREJADOR_WEBHOOK_SECRET", "whsec-test")
    return pem
