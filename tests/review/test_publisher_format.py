# Filename: test_publisher_format.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from tests.factories import FakeAuth

from farejador.github.client import GitHubClient
from farejador.review.findings import Category, Finding, Severity
from farejador.review.publisher import (
    MAX_BODY,
    MAX_SKIPPED_SHOWN,
    MAX_UNANCHORED_SHOWN,
    Publisher,
)
from farejador.review.validator import AnchorResult, Unanchored

ZWSP = "​"


def _publisher() -> Publisher:
    return Publisher(GitHubClient(FakeAuth()))


def _finding(
    file: str = "a.py",
    line: int = 1,
    severity: Severity = Severity.MEDIUM,
    message: str = "Extraia uma função.",
    suggestion: str | None = None,
    rationale: str | None = None,
    diff: str | None = None,
) -> Finding:
    return Finding(
        file=file,
        line=line,
        severity=severity,
        category=Category.COMPLEXITY,
        problem=message,
        rationale=rationale,
        suggestion=suggestion,
        suggestion_diff=diff,
    )


def test_header_counts_findings_per_severity_across_inline_and_unanchored() -> None:
    anchored = AnchorResult(
        inline=[_finding(severity=Severity.HIGH), _finding(line=2, severity=Severity.LOW)],
        unanchored=[Unanchored(_finding(line=3, severity=Severity.HIGH), "line-not-added")],
    )
    payload = _publisher().format_review(
        commit_sha="abcdef1234567", summary="", anchored=anchored, skipped=[], note=None
    )
    assert "Commit revisado: `abcdef1` · Achados: 3 (alta 2, baixa 1)" in payload.body
    assert payload.body.startswith("## Revisão do Farejador")
    assert len(payload.comments) == 2


def test_no_findings_says_so_and_empty_sections_are_omitted() -> None:
    payload = _publisher().format_review(
        commit_sha="abcdef1",
        summary="All good.",
        anchored=AnchorResult([], []),
        skipped=[],
        note=None,
    )
    assert "Achados: 0" in payload.body
    assert "Nenhum achado relevante." in payload.body
    assert "All good." in payload.body
    assert "###" not in payload.body
    assert ">" not in payload.body.replace("->", "")


def test_inline_comment_follows_the_problem_rationale_suggestion_structure() -> None:
    text = _publisher().format_inline(
        _finding(
            message="A função mistura validação e persistência.",
            rationale="Mudanças em uma parte obrigam a reler a outra e elevam o risco.",
            suggestion="Separe a validação em uma função própria.",
            diff="-    valida_e_salva(dados)\n+    valida(dados)\n+    salva(dados)",
        )
    )
    assert text == (
        "**média · complexidade**\n\n"
        "## Problema\n\n"
        "A função mistura validação e persistência.\n\n"
        "<details>\n<summary><strong>Racional</strong></summary>\n\n"
        "Mudanças em uma parte obrigam a reler a outra e elevam o risco.\n\n"
        "</details>\n\n"
        "<details>\n<summary><strong>Sugestão</strong></summary>\n\n"
        "Separe a validação em uma função própria.\n\n"
        "```diff\n-    valida_e_salva(dados)\n+    valida(dados)\n+    salva(dados)\n```\n\n"
        "</details>"
    )


def test_the_collapsible_sections_are_closed_by_default() -> None:
    text = _publisher().format_inline(_finding(rationale="Porque sim.", suggestion="Faça assim."))
    assert "<details>" in text
    assert "<details open" not in text
    assert text.count("<details>") == 2
    assert text.count("</details>") == 2


def test_missing_sections_are_omitted_instead_of_left_empty() -> None:
    only_problem = _publisher().format_inline(_finding())
    assert "## Problema" in only_problem
    assert "<details>" not in only_problem
    with_rationale = _publisher().format_inline(_finding(rationale="Impacto."))
    assert "Racional" in with_rationale
    assert "Sugestão" not in with_rationale
    only_diff = _publisher().format_inline(_finding(diff="-a\n+b"))
    assert "Sugestão" in only_diff
    assert "```diff\n-a\n+b\n```" in only_diff


def test_the_diff_fence_is_longer_than_any_backtick_run_inside_it() -> None:
    diff = '-texto = """```"""\n+texto = "ok"'
    text = _publisher().format_inline(_finding(diff=diff))
    assert "````diff\n" in text
    assert text.count("````") == 2
    assert text.rstrip().endswith("</details>")


def test_the_suggestion_text_keeps_its_own_code_fences() -> None:
    text = _publisher().format_inline(_finding(suggestion="Use assim:\n```python\nx = 1\n```"))
    assert "```python" in text


def test_html_from_the_model_cannot_break_out_of_the_sections() -> None:
    text = _publisher().format_inline(
        _finding(
            message="Veja </details><script>alert(1)</script> isto",
            rationale="</details> fim e <details open> início",
            suggestion="</details><img src=x onerror=alert(1)>",
        )
    )
    assert "<script>" not in text
    assert "<img" not in text
    assert text.count("<details>") == 2
    assert text.count("</details>") == 2  # only the ones the Publisher wrote
    assert "<details open>" not in text


def test_secrets_echoed_in_the_diff_or_the_text_are_masked() -> None:
    token = "ghp_" + "a" * 36
    text = _publisher().format_inline(
        _finding(
            message=f"Remova o token {token}",
            rationale=f"O valor {token} vazaria.",
            suggestion="Use uma variável de ambiente.",
            diff=f'-TOKEN = "{token}"\n+TOKEN = os.environ["TOKEN"]',
        )
    )
    assert token not in text
    assert "«segredo-removido»" in text


def test_untrusted_text_is_sanitized_in_every_part() -> None:
    anchored = AnchorResult(
        inline=[_finding(message="Ask @alice about <script>x</script>")],
        unanchored=[Unanchored(_finding("b`.py", 3, message="See @bob"), "file-not-in-diff")],
    )
    payload = _publisher().format_review(
        commit_sha="abc1234",
        summary="Summary mentions @carol and ![x](http://evil/p.png)",
        anchored=anchored,
        skipped=[("we`ird.lock", "lock`file")],
        note="Stopped @dave",
    )
    everything = payload.body + payload.comments[0].body
    for name in ("alice", "bob", "carol", "dave"):
        assert f"@{name}" not in everything
        assert f"@{ZWSP}{name}" in everything
    assert "<script>" not in everything
    assert "http://evil" not in everything
    assert "`b'.py:3`" in payload.body
    assert "`we'ird.lock` — lock'file" in payload.body


def test_long_lists_are_capped_with_a_count_of_the_rest() -> None:
    many = [
        Unanchored(_finding("a.py", n + 1, message=f"m{n}"), "line-not-added")
        for n in range(MAX_UNANCHORED_SHOWN + 5)
    ]
    skipped = [(f"f{n}.lock", "lockfile") for n in range(MAX_SKIPPED_SHOWN + 7)]
    payload = _publisher().format_review(
        commit_sha="abc1234",
        summary="",
        anchored=AnchorResult([], many),
        skipped=skipped,
        note=None,
    )
    assert payload.body.count("line-not-added") == 0
    assert payload.body.count("\n- `a.py:") == MAX_UNANCHORED_SHOWN
    assert "- ... e mais 5" in payload.body
    assert "- ... e mais 7" in payload.body


def test_unanchored_messages_are_clipped_to_one_short_line() -> None:
    long = Unanchored(_finding(message="word " * 90 + "\nsecond line"), "line-not-added")
    payload = _publisher().format_review(
        commit_sha="abc1234", summary="", anchored=AnchorResult([], [long]), skipped=[], note=None
    )
    (line,) = [item for item in payload.body.splitlines() if item.startswith("- `a.py:1`")]
    assert len(line) < 400
    assert "second line" not in line or len(line) < 400


def test_the_whole_body_stays_under_the_github_limit() -> None:
    anchored = AnchorResult(
        [],
        [Unanchored(_finding(message="x" * 500, line=n + 1), "line-not-added") for n in range(50)],
    )
    payload = _publisher().format_review(
        commit_sha="abc1234", summary="s" * 2000, anchored=anchored, skipped=[], note="n" * 500
    )
    assert len(payload.body) <= MAX_BODY


def test_the_early_stop_note_is_quoted_at_the_end() -> None:
    payload = _publisher().format_review(
        commit_sha="abc1234",
        summary="",
        anchored=AnchorResult([], []),
        skipped=[],
        note="Revisão interrompida antes do fim: limite de passos atingido.",
    )
    assert payload.body.rstrip().endswith(
        "> Revisão interrompida antes do fim: limite de passos atingido."
    )


def test_failure_notice_is_short_safe_and_explains_how_to_retry() -> None:
    text = _publisher().failure_notice("abcdef1234567", "@farejador")
    assert "`abcdef1`" in text
    assert "não tentará de novo sozinho" in text
    assert "Mencione `@farejador`" in text
    assert "Traceback" not in text


def test_inline_label_uses_portuguese_severity_and_category() -> None:
    text = _publisher().format_inline(_finding(severity=Severity.HIGH))
    assert text.startswith("**alta · complexidade**")


def test_the_status_preview_skips_the_label_line_and_shows_the_message() -> None:
    from farejador.review.publisher import PendingThread

    status = _publisher().format_status(
        resolved=2,
        pending=[
            PendingThread("a.py", 3, "**média · complexidade**\n\nExtraia esta função."),
            PendingThread(None, None, "Comentário sem rótulo"),
        ],
        trigger_text="@farejador",
    )
    assert "Resolvidos: 2 · Ainda pendentes: 2" in status
    assert "- `a.py:3` — Extraia esta função." in status
    assert "- `local desconhecido` — Comentário sem rótulo" in status
