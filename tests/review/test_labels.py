# Filename: test_labels.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import pytest
from tests.gitrepo import make_repo

from farejador.agent import prompts, schemas
from farejador.review.findings import Category, Severity
from farejador.review.labels import (
    CATEGORY_LABELS,
    SEVERITY_LABELS,
    SKIP_REASON_LABELS,
    category_label,
    severity_label,
    skip_reason_label,
)
from farejador.review.publisher import Publisher
from farejador.review.validator import AnchorResult
from farejador.tools import RepoTools, error_json


def test_every_severity_and_category_has_a_portuguese_label() -> None:
    assert set(SEVERITY_LABELS) == {item.value for item in Severity}
    assert set(CATEGORY_LABELS) == {item.value for item in Category}
    assert all((label and label.isascii() is False) or label for label in SEVERITY_LABELS.values())


@pytest.mark.parametrize(
    ("code", "expected"),
    [("high", "alta"), ("medium", "média"), ("low", "baixa"), ("unknown", "unknown")],
)
def test_severity_labels_fall_back_to_the_code(code: str, expected: str) -> None:
    assert severity_label(code) == expected


def test_category_and_skip_reason_labels() -> None:
    assert category_label("error-handling") == "tratamento de erros"
    assert category_label("whatever") == "whatever"
    assert skip_reason_label("lockfile") == "arquivo de lock"
    assert skip_reason_label("secret-bearing") == "pode conter credenciais"
    assert skip_reason_label("brand-new-reason") == "brand-new-reason"
    assert {"lockfile", "secret-bearing", "generated", "vendored", "binary", "deleted"} <= set(
        SKIP_REASON_LABELS
    )


def test_the_codes_that_are_a_technical_contract_stay_in_english() -> None:
    props = schemas.FINDING_SCHEMA["properties"]
    assert props["severity"]["enum"] == ["low", "medium", "high"]
    assert "maintainability" in props["category"]["enum"]


def test_both_system_prompts_require_portuguese_output() -> None:
    for system in (prompts.review_system_prompt(), prompts.reevaluate_system_prompt()):
        assert "português do Brasil" in system
        assert "severity e category" in system


def test_tool_descriptions_ask_for_portuguese() -> None:
    assert "português do Brasil" in schemas.SUBMIT_REVIEW["function"]["description"]
    assert "português do Brasil" in schemas.SUBMIT_VERDICTS["function"]["description"]


def test_errors_for_the_model_keep_accents_readable() -> None:
    text = error_json("arquivo não encontrado")
    assert "\\u" not in text
    assert json.loads(text) == {"error": "arquivo não encontrado"}


def test_tool_errors_reach_the_model_in_portuguese(tmp_path: object) -> None:
    from pathlib import Path

    root = Path(str(tmp_path)) / "repo"
    make_repo(root, {"a.py": "x = 1\n"})
    answer = RepoTools(root).execute("read_file", {"path": "../fora.txt"})
    assert "o caminho está fora do repositório" in answer
    assert "\\u" not in answer


def test_the_pull_request_text_is_entirely_in_portuguese() -> None:
    publisher = Publisher(client=None)  # type: ignore[arg-type]
    payload = publisher.format_review(
        commit_sha="abcdef1234",
        summary="",
        anchored=AnchorResult([], []),
        skipped=[("uv.lock", "lockfile"), ("x.bin", "binary"), ("n.txt", "some-new-reason")],
        note=None,
    )
    assert payload.body.startswith("## Revisão do Farejador")
    assert "Commit revisado: `abcdef1`" in payload.body
    assert "- `uv.lock` — arquivo de lock" in payload.body
    assert "- `x.bin` — binário" in payload.body
    assert "- `n.txt` — some-new-reason" in payload.body
    for english in ("Reviewed", "Findings", "Skipped", "lockfile"):
        assert english not in payload.body
    status = publisher.format_status(resolved=0, pending=[], trigger_text="@farejador")
    assert "Status do Farejador" in status
    assert "Threads pendentes" in status
    notice = publisher.failure_notice("abcdef1234", "@farejador")
    assert notice.startswith("O Farejador não conseguiu")
