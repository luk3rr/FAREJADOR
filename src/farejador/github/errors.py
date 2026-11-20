# Filename: errors.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Errors raised by the GitHub layer (design.md, C-H)."""

from __future__ import annotations


class AuthError(Exception):
    """GitHub rejected our credentials, or a token could not be obtained."""


class GitHubApiError(Exception):
    """A GitHub request failed after the allowed retries."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status
        self.message = message
