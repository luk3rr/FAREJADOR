# Filename: conftest.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Close every SQLite connection a trace test opened, so none is left to the garbage collector."""

import contextlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _close_sqlite_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    yield
    for conn in opened:
        with contextlib.suppress(sqlite3.Error):
            conn.close()
