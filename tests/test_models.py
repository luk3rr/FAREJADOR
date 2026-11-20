# Filename: test_models.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest
from pydantic import ValidationError
from tests.factories import make_command, make_first

from farejador.models import Trigger, TriggerKind, TriggerSource


def test_first_review_key_is_per_pull_request() -> None:
    trigger = make_first(pr=42, repo="owner/name")
    assert trigger.key == "first:owner/name#42"
    assert trigger.kind is TriggerKind.FIRST_REVIEW
    assert trigger.comment_id is None


def test_command_key_is_per_comment() -> None:
    trigger = make_command(comment_id=987)
    assert trigger.key == "cmd:987"
    assert trigger.kind is TriggerKind.COMMAND


def test_triggers_are_immutable() -> None:
    with pytest.raises(ValidationError):
        make_first().pr_number = 5  # type: ignore[misc]


def test_command_requires_comment_id() -> None:
    with pytest.raises(ValidationError, match="comment_id"):
        Trigger(
            key="cmd:1",
            kind=TriggerKind.COMMAND,
            repo="o/r",
            installation_id=1,
            pr_number=1,
            sender_login="a",
            source=TriggerSource.WEBHOOK,
        )


def test_first_review_must_not_have_comment_id() -> None:
    with pytest.raises(ValidationError, match="comment_id"):
        Trigger(
            key="first:o/r#1",
            kind=TriggerKind.FIRST_REVIEW,
            repo="o/r",
            installation_id=1,
            pr_number=1,
            comment_id=3,
            sender_login="a",
            source=TriggerSource.WEBHOOK,
        )


def test_key_must_match_kind() -> None:
    with pytest.raises(ValidationError, match="key must be"):
        Trigger(
            key="first:other/repo#1",
            kind=TriggerKind.FIRST_REVIEW,
            repo="o/r",
            installation_id=1,
            pr_number=1,
            sender_login="a",
            source=TriggerSource.POLLING,
        )


@pytest.mark.parametrize("repo", ["noslash", "a/b/c", "a b/c"])
def test_repo_must_be_owner_slash_name(repo: str) -> None:
    with pytest.raises(ValidationError):
        Trigger.first_review(
            repo=repo,
            installation_id=1,
            pr_number=1,
            sender_login="a",
            source=TriggerSource.POLLING,
        )


def _pr(**base: object) -> dict[str, object]:
    return {"number": 1, "head": {"sha": "a" * 40}, **base}


def test_the_pull_request_remembers_whether_its_repository_is_private() -> None:
    from farejador.github.models import PullRequest

    assert PullRequest.from_api(_pr(base={"repo": {"private": False}})).repo_private is False
    assert PullRequest.from_api(_pr(base={"repo": {"private": True}})).repo_private is True


@pytest.mark.parametrize(
    "base",
    [
        None,
        {},
        {"repo": None},
        {"repo": {}},
        {"repo": {"private": "yes"}},
        {"repo": {"private": 1}},
    ],
)
def test_a_missing_or_odd_privacy_flag_is_unknown_never_public(base: object) -> None:
    from farejador.github.models import PullRequest

    data = _pr() if base is None else _pr(base=base)
    assert PullRequest.from_api(data).repo_private is None
