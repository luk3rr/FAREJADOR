# Filename: test_mask.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest

from farejador.review.filters import MASKED, Masker, mask

PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc123\nsecondline\n-----END RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "a" * 36,
        "github_pat_" + "B" * 30,
        "sk-or-v1-" + "c" * 20,
        "AKIA" + "A" * 16,
        "xoxb-1234567890-abcdef",
        "Authorization: Bearer abcdefghijklmnop",
    ],
)
def test_known_token_shapes_are_masked(secret: str) -> None:
    masked = mask(f"x = '{secret}' # trailing")
    assert MASKED in masked
    assert secret.split()[-1] not in masked
    assert "# trailing" in masked


def test_private_key_blocks_are_masked_line_by_line() -> None:
    masked = mask(f"before\n{PEM}\nafter")
    assert masked.split("\n") == ["before", MASKED, MASKED, MASKED, MASKED, "after"]
    assert len(masked.split("\n")) == len(f"before\n{PEM}\nafter".split("\n"))


def test_single_line_private_key_marker_does_not_leak_state() -> None:
    masker = Masker()
    one_line = "-----BEGIN PRIVATE KEY----- abc -----END PRIVATE KEY-----"
    assert masker.line(one_line) == MASKED
    assert masker.line("normal code") == "normal code"


def test_unterminated_key_masks_until_the_end() -> None:
    masker = Masker()
    assert masker.line("-----BEGIN PRIVATE KEY-----") == MASKED
    assert masker.line("still secret") == MASKED


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        ('password = "hunter2hunter2"', "password = "),
        ("API_KEY: 'abcdef123456'", "API_KEY: "),
        ("db_password='correct horse'", "db_password="),
        ("token = abcdefghijkl123456", "token = "),
        ('"client_secret": "s3cr3t-value"', '"client_secret": '),
    ],
)
def test_assignments_keep_the_key_name_and_hide_the_value(line: str, kept: str) -> None:
    masked = mask(line)
    assert masked.startswith(kept)
    assert MASKED in masked


@pytest.mark.parametrize(
    "line",
    [
        "password = hash_password(raw)",
        "token = request.headers.get('x')",
        "api_key = os.environ['KEY']",
        "password = ''",
        "secret = None",
        "def get_token(user):",
    ],
)
def test_ordinary_code_is_not_masked(line: str) -> None:
    assert mask(line) == line


def test_url_credentials_are_masked_but_host_is_kept() -> None:
    masked = mask("git clone https://user:s3cretpass@github.com/o/r.git")
    assert masked == f"git clone https://user:{MASKED}@github.com/o/r.git"


def test_masking_never_changes_the_number_of_lines() -> None:
    text = "a\n\n" + PEM + "\npassword = 'abcdefgh'\n\nend\n"
    assert len(mask(text).split("\n")) == len(text.split("\n"))


def test_the_marker_does_not_look_like_python_or_json_syntax() -> None:
    """A "[MASKED]" placeholder was read as a list and made the model invent a TypeError."""
    assert not any(char in MASKED for char in "[]{}()<>\"'")
    assert mask('password = "hunter2-admin"') == f"password = {MASKED}"
    assert mask('password = "hunter2-admin"').isprintable()
