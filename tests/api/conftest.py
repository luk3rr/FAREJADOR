# Filename: conftest.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Reuse the fixture that closes every SQLite connection a test opened."""

from tests.trace.conftest import _close_sqlite_connections  # noqa: F401
