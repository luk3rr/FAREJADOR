# Filename: test_sanitizer.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest

from farejador.review.sanitizer import sanitize

ZWSP = "​"


def test_mentions_are_neutralised_but_still_readable() -> None:
    out = sanitize("Ping @alice and @org/team-x please", max_length=500)
    assert f"@{ZWSP}alice" in out
    assert f"@{ZWSP}org/team-x" in out
    assert out.replace(ZWSP, "") == "Ping @alice and @org/team-x please"


def test_emails_and_already_neutralised_mentions_are_left_alone() -> None:
    assert sanitize("mail me: a@b.com", max_length=500) == "mail me: a@b.com"
    once = sanitize("@bob", max_length=500)
    assert sanitize(once, max_length=500) == once


def test_mentions_inside_code_are_kept_intact_for_copy_and_paste() -> None:
    text = "Use `@property` here:\n```python\n@dataclass\nclass A: ...\n```\nthen @bob"
    out = sanitize(text, max_length=500)
    assert "`@property`" in out
    assert "@dataclass" in out
    assert f"@{ZWSP}bob" in out


@pytest.mark.parametrize(
    "raw",
    ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<!-- hidden -->", "</div>"],
)
def test_raw_html_is_escaped_outside_code(raw: str) -> None:
    out = sanitize(f"text {raw} more", max_length=500)
    assert "<" not in out
    assert "&lt;" in out


def test_angle_brackets_in_code_and_comparisons_survive() -> None:
    out = sanitize("if a < b then `List<String>` and\n```\n<div>ok</div>\n```", max_length=500)
    assert "a < b" in out
    assert "`List<String>`" in out
    assert "<div>ok</div>" in out


def test_images_become_plain_text() -> None:
    out = sanitize(
        "see ![diagram](https://evil.example/t.png?x=1) and ![](http://x/y.png)", max_length=500
    )
    assert "http" not in out
    assert "diagram" in out
    assert "image" in out


@pytest.mark.parametrize(
    "scheme", ["javascript:alert(1)", "data:text/html;base64,AAAA", "VBScript:x"]
)
def test_dangerous_link_targets_are_removed(scheme: str) -> None:
    out = sanitize(f"click [here]({scheme}) now", max_length=500)
    assert "here" in out
    assert scheme.lower() not in out.lower()
    assert "](" not in out


def test_normal_links_are_kept() -> None:
    text = "read [the docs](https://example.com/docs)"
    assert sanitize(text, max_length=500) == text


def test_control_and_bidi_characters_are_removed() -> None:
    out = sanitize("a\x00b\x07c‮d​e﻿\tf\ng", max_length=500)
    assert out == "abcde\tf\ng"


def test_length_is_capped_with_an_ellipsis() -> None:
    out = sanitize("x" * 100, max_length=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_unbalanced_fences_are_closed() -> None:
    out = sanitize("```python\nprint('hi')", max_length=500)
    assert out.endswith("\n```")
    assert out.count("```") == 2


def test_truncation_inside_a_fence_still_leaves_balanced_fences() -> None:
    out = sanitize("```\n" + "line\n" * 50 + "```", max_length=30)
    assert sum(1 for line in out.split("\n") if line.startswith("```")) % 2 == 0


def test_balanced_text_is_unchanged() -> None:
    text = "Plain **markdown** with `code`.\n\n- item\n- item"
    assert sanitize(text, max_length=500) == text
