# Filename: publisher.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Formats and posts reviews, notices and status comments (FR-15, FR-14, FR-20; contract C-F)."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from farejador.github.client import GitHubClient
from farejador.github.errors import AuthError, GitHubApiError
from farejador.github.models import ReviewComment
from farejador.review.filters import mask
from farejador.review.findings import (
    MAX_PROBLEM,
    MAX_RATIONALE,
    MAX_SUGGESTION,
    MAX_SUMMARY,
    Finding,
)
from farejador.review.labels import category_label, severity_label, skip_reason_label
from farejador.review.sanitizer import sanitize
from farejador.review.validator import AnchorResult

logger = logging.getLogger(__name__)

MAX_BODY = 60_000
MAX_UNANCHORED_SHOWN = 20
MAX_SKIPPED_SHOWN = 30
MAX_UNANCHORED_MESSAGE = 300
_SEVERITIES = ("high", "medium", "low")


@dataclass(frozen=True, slots=True)
class PendingThread:
    """An open Farejador thread listed in the status comment."""

    path: str | None
    line: int | None
    body: str


MAX_PENDING_SHOWN = 10
MAX_PENDING_PREVIEW = 120


@dataclass(frozen=True, slots=True)
class ReviewPayload:
    body: str
    comments: list[ReviewComment]


def _clean(text: str, max_length: int) -> str:
    """Sanitize model text, then mask secrets the model may have echoed back (FR-14, FR-19)."""
    return mask(sanitize(text, max_length=max_length))


def _preview_line(body: str) -> str:
    """The first line of the problem text of a Farejador comment (for the status comment)."""
    lines = [part.strip() for part in body.splitlines() if part.strip()]
    for index, line in enumerate(lines):
        if line == "## Problema" and index + 1 < len(lines):
            return lines[index + 1]
    if len(lines) > 1 and lines[0].startswith("**"):
        return lines[1]
    return lines[0] if lines else ""


def _collapsible(title: str, markdown: str) -> str:
    """A GitHub ``<details>`` block; blank lines let the Markdown inside render."""
    return f"<details>\n<summary><strong>{title}</strong></summary>\n\n{markdown}\n\n</details>"


def _diff_block(diff: str) -> str:
    """A ```diff fence long enough that the content cannot close it."""
    longest = max((len(run) for run in re.findall(r"`+", diff)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}diff\n{diff}\n{fence}"


def _code(text: str) -> str:
    """Safe inline-code content: no backticks and no line breaks."""
    return " ".join(text.replace("`", "'").split())


class Publisher:
    """Turns validated findings into GitHub comments and posts them."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    # -- formatting ------------------------------------------------------------------------

    def format_inline(self, finding: Finding) -> str:
        """The comment of one thread: a visible problem and two collapsible sections.

        The ``<details>`` markup is ours; the model only provides plain Markdown text, which is
        sanitized (HTML from the model is escaped) before it is placed inside.
        """
        label = (
            f"{severity_label(finding.severity.value)} · {category_label(finding.category.value)}"
        )
        parts = [f"**{label}**", "", "## Problema", "", _clean(finding.problem, MAX_PROBLEM)]

        rationale = _clean(finding.rationale, MAX_RATIONALE).strip() if finding.rationale else ""
        if rationale:
            parts += ["", _collapsible("Racional", rationale)]

        suggestion = (
            _clean(finding.suggestion, MAX_SUGGESTION).strip() if finding.suggestion else ""
        )
        body = suggestion
        if finding.suggestion_diff:
            block = _diff_block(mask(finding.suggestion_diff))
            body = f"{suggestion}\n\n{block}" if suggestion else block
        if body:
            parts += ["", _collapsible("Sugestão", body)]
        return "\n".join(parts)

    def format_review(
        self,
        *,
        commit_sha: str,
        summary: str,
        anchored: AnchorResult,
        skipped: Sequence[tuple[str, str]],
        note: str | None,
    ) -> ReviewPayload:
        all_findings = [*anchored.inline, *(item.finding for item in anchored.unanchored)]
        counts = Counter(finding.severity.value for finding in all_findings)
        breakdown = ", ".join(
            f"{severity_label(name)} {counts[name]}" for name in _SEVERITIES if counts[name]
        )
        header = f"Commit revisado: `{_code(commit_sha[:7])}` · Achados: {len(all_findings)}"
        if breakdown:
            header += f" ({breakdown})"

        lines = ["## Revisão do Farejador", "", header]
        clean_summary = _clean(summary, MAX_SUMMARY).strip()
        if clean_summary:
            lines += ["", clean_summary]
        if not all_findings:
            lines += ["", "Nenhum achado relevante."]

        if anchored.unanchored:
            lines += ["", "### Achados sem âncora no diff"]
            shown = anchored.unanchored[:MAX_UNANCHORED_SHOWN]
            for item in shown:
                message = _clean(item.finding.problem, MAX_UNANCHORED_MESSAGE)
                where = _code(f"{item.finding.file}:{item.finding.line}")
                lines.append(f"- `{where}` — {' '.join(message.split())}")
            hidden = len(anchored.unanchored) - len(shown)
            if hidden > 0:
                lines.append(f"- ... e mais {hidden}")

        if skipped:
            lines += ["", "### Arquivos ignorados"]
            for path, reason in skipped[:MAX_SKIPPED_SHOWN]:
                lines.append(f"- `{_code(path)}` — {_code(skip_reason_label(reason))}")
            if len(skipped) > MAX_SKIPPED_SHOWN:
                lines.append(f"- ... e mais {len(skipped) - MAX_SKIPPED_SHOWN}")

        if note:
            lines += ["", f"> {_clean(note, 300).strip()}"]

        body = "\n".join(lines)
        if len(body) > MAX_BODY:
            body = body[: MAX_BODY - 1].rstrip() + "…"
        comments = [
            ReviewComment(path=finding.file, line=finding.line, body=self.format_inline(finding))
            for finding in anchored.inline
        ]
        return ReviewPayload(body, comments)

    def format_status(
        self, *, resolved: int, pending: Sequence[PendingThread], trigger_text: str
    ) -> str:
        """The comment posted when a command finds threads that are still open (FR-18)."""
        lines = [
            "## Status do Farejador",
            "",
            f"Resolvidos: {resolved} · Ainda pendentes: {len(pending)}",
            "",
            "### Threads pendentes",
        ]
        for thread in pending[:MAX_PENDING_SHOWN]:
            where = _code(f"{thread.path}:{thread.line}") if thread.path else "local desconhecido"
            first_line = _preview_line(thread.body)
            preview = _clean(first_line.replace("*", ""), MAX_PENDING_PREVIEW)
            lines.append(f"- `{where}` — {' '.join(preview.split())}")
        if len(pending) > MAX_PENDING_SHOWN:
            lines.append(f"- ... e mais {len(pending) - MAX_PENDING_SHOWN}")
        lines += [
            "",
            "Corrija estes pontos (ou resolva você mesmo os threads de que discordar) e mencione "
            f"`{_code(trigger_text)}` de novo para uma nova revisão.",
        ]
        return "\n".join(lines)

    def failure_notice(self, commit_sha: str, trigger_text: str) -> str:
        return (
            f"O Farejador não conseguiu concluir a revisão automática do commit "
            f"`{_code(commit_sha[:7])}`. Ele não tentará de novo sozinho. "
            f"Mencione `{_code(trigger_text)}` em um comentário para tentar outra vez."
        )

    # -- posting ---------------------------------------------------------------------------

    async def post_review(
        self,
        installation_id: int,
        repo: str,
        pr_number: int,
        *,
        commit_sha: str,
        payload: ReviewPayload,
    ) -> int:
        return await self._client.create_review(
            installation_id,
            repo,
            pr_number,
            commit_id=commit_sha,
            body=payload.body,
            comments=payload.comments,
        )

    async def post_comment(self, installation_id: int, repo: str, pr_number: int, body: str) -> int:
        return await self._client.post_comment(installation_id, repo, pr_number, body)

    async def post_notice(
        self,
        installation_id: int,
        repo: str,
        pr_number: int,
        *,
        commit_sha: str,
        trigger_text: str,
    ) -> bool:
        """Post the failure notice once; a failure to post it is logged, never raised."""
        try:
            await self._client.post_comment(
                installation_id,
                repo,
                pr_number,
                self.failure_notice(commit_sha, trigger_text),
            )
        except (GitHubApiError, AuthError):
            logger.warning("could not post the failure notice", extra={"repo": repo})
            return False
        return True
