# Filename: test_same_login.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""GitHub writes an App as ``slug[bot]`` in REST and as ``slug`` in GraphQL."""

import pytest

from farejador.github.models import same_login


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("farejadorr[bot]", "farejadorr"),
        ("farejadorr", "farejadorr[bot]"),
        ("FarejadorR[BOT]", "farejadorr"),
        ("farejadorr[bot]", "farejadorr[bot]"),
        (" farejadorr ", "farejadorr[bot]"),
    ],
)
def test_the_same_account_matches_in_either_spelling(first: str, second: str) -> None:
    assert same_login(first, second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("farejadorr[bot]", "other[bot]"),
        ("farejadorr", "farejador"),
        ("farejadorr-evil", "farejadorr[bot]"),
        ("", ""),
        ("[bot]", "[bot]"),
        ("", "farejadorr[bot]"),
    ],
)
def test_other_accounts_and_empty_logins_never_match(first: str, second: str) -> None:
    assert not same_login(first, second)
