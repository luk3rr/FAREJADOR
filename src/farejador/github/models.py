# Filename: models.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Small typed views of the GitHub payloads the system uses."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict


def same_login(first: str, second: str) -> bool:
    """Whether two logins name the same account.

    GitHub writes an App's login as ``slug[bot]`` in the REST API but as plain ``slug`` in GraphQL,
    so the ``[bot]`` suffix is ignored; the comparison is also case-insensitive.
    """

    def plain(login: str) -> str:
        lowered = login.strip().lower()
        return lowered.removesuffix("[bot]")

    return plain(first) != "" and plain(first) == plain(second)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class Installation(_Model):
    id: int
    account_login: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        return cls(id=data["id"], account_login=(data.get("account") or {}).get("login", ""))


class PullRequest(_Model):
    number: int
    title: str
    draft: bool
    state: str
    head_sha: str
    author_login: str
    html_url: str
    repo_private: bool | None = None  # None when the API did not say (treated as private)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        base_repo = (data.get("base") or {}).get("repo") or {}
        private = base_repo.get("private")
        return cls(
            number=data["number"],
            title=data.get("title", ""),
            draft=bool(data.get("draft", False)),
            state=data.get("state", "open"),
            head_sha=data["head"]["sha"],
            author_login=(data.get("user") or {}).get("login", ""),
            html_url=data.get("html_url", ""),
            repo_private=private if isinstance(private, bool) else None,
        )


class IssueComment(_Model):
    id: int
    body: str
    author_login: str
    created_at: str
    updated_at: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=data["id"],
            body=data.get("body") or "",
            author_login=(data.get("user") or {}).get("login", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ReviewComment(_Model):
    """An inline comment to be created as part of a review (side is always RIGHT)."""

    path: str
    line: int
    body: str

    def to_api(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "side": "RIGHT", "body": self.body}


class ReviewThread(_Model):
    id: str
    is_resolved: bool
    path: str | None
    line: int | None
    author_login: str
    body: str

    @classmethod
    def from_graphql(cls, node: dict[str, Any]) -> Self:
        comments = (node.get("comments") or {}).get("nodes") or []
        first = comments[0] if comments else {}
        return cls(
            id=node["id"],
            is_resolved=bool(node.get("isResolved", False)),
            path=node.get("path"),
            line=node.get("line"),
            author_login=(first.get("author") or {}).get("login", ""),
            body=first.get("body") or "",
        )
