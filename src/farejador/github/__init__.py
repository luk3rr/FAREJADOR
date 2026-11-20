# Filename: __init__.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""GitHub access: App authentication and the REST/GraphQL client."""

from farejador.github.auth import AppAuth, GitHubAuth
from farejador.github.client import Fetched, GitHubClient, resolve_bot_login
from farejador.github.errors import AuthError, GitHubApiError
from farejador.github.models import (
    Installation,
    IssueComment,
    PullRequest,
    ReviewComment,
    ReviewThread,
)

__all__ = [
    "AppAuth",
    "AuthError",
    "Fetched",
    "GitHubApiError",
    "GitHubAuth",
    "GitHubClient",
    "Installation",
    "IssueComment",
    "PullRequest",
    "ReviewComment",
    "ReviewThread",
    "resolve_bot_login",
]
