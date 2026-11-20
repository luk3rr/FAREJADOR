# Filename: test_sanitize.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from tests.trace.helpers import SENTINEL

from farejador.review.filters import MASKED
from farejador.trace.sanitize import TRUNCATION_NOTE, Sanitizer


def test_secrets_are_masked_before_anything_else() -> None:
    cleaned = Sanitizer(1000, 10_000).clean(f"key {SENTINEL} and password = 'hunter2-admin'")
    assert SENTINEL not in cleaned.text
    assert "hunter2-admin" not in cleaned.text
    assert MASKED in cleaned.text
    assert cleaned.truncated is False


def test_an_item_over_the_limit_is_cut_with_a_marker_and_keeps_the_original_size() -> None:
    sanitizer = Sanitizer(max_item_chars=100, max_run_bytes=100_000)
    cleaned = sanitizer.clean("x" * 500)
    assert cleaned.text == "x" * 100 + TRUNCATION_NOTE.format(original=500)
    assert (cleaned.truncated, cleaned.original_chars) == (True, 500)
    assert sanitizer.truncated is True


def test_the_marker_is_never_cut_in_half_because_masking_comes_first() -> None:
    text = "a" * 95 + f" token = '{'s' * 20}' " + "b" * 50
    cleaned = Sanitizer(max_item_chars=100, max_run_bytes=100_000).clean(text)
    assert "s" * 20 not in cleaned.text
    assert "«segredo-removid" not in cleaned.text.replace(MASKED, "")


def test_the_run_ceiling_is_enforced_and_later_items_keep_nothing() -> None:
    sanitizer = Sanitizer(max_item_chars=10_000, max_run_bytes=1000)
    first = sanitizer.clean("a" * 800)
    assert first.truncated is False and sanitizer.exhausted is False
    second = sanitizer.clean("b" * 800)
    assert second.truncated is True
    assert sanitizer.exhausted is True and sanitizer.truncated is True
    third = sanitizer.clean("c" * 50)
    assert third.text == "" and third.truncated is True and third.original_chars == 50


def test_the_ceiling_counts_bytes_not_characters() -> None:
    sanitizer = Sanitizer(max_item_chars=10_000, max_run_bytes=100)
    cleaned = sanitizer.clean("ç" * 100)  # 200 bytes in utf-8
    assert cleaned.truncated is True
    assert len(cleaned.text.split("[")[0].encode("utf-8")) <= 100


def test_empty_and_missing_values_are_harmless() -> None:
    sanitizer = Sanitizer(100, 1000)
    assert sanitizer.clean(None).text == ""
    assert sanitizer.clean("").original_chars == 0
    assert sanitizer.truncated is False
