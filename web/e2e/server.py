# Filename: server.py
# Created on: November 24, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Serve the real API and the built dashboard over a throwaway trace, for the browser tests.

Nothing here touches a real service: the trace is a temporary SQLite file seeded with a few
reviews (public repositories, one private repository that must never show up).
"""

import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from farejador.api.routes import create_api
from farejador.trace.store import (
    Disposition,
    FindingRecord,
    RunOutcome,
    ToolResult,
    TraceStore,
)
from farejador.web import install_web

PORT = 8765


def _finding(
    path: str,
    line: int,
    severity: str,
    category: str,
    problem: str,
    disposition: Disposition = Disposition.INLINE,
    diff: str | None = None,
) -> FindingRecord:
    return FindingRecord(
        path=path,
        line=line,
        severity=severity,
        category=category,
        problem=problem,
        rationale="Explicação do porquê isto é um problema.",
        suggestion="Mudança sugerida.",
        suggestion_diff=diff,
        diff_dropped=False,
        disposition=disposition,
        reason=None,
    )


def _run(
    store: TraceStore,
    *,
    key: str,
    repo: str,
    pr: int,
    public: bool,
    outcome: RunOutcome,
    findings: list[FindingRecord],
    hours_ago: float,
    error: str | None = None,
) -> None:
    started = datetime.now(UTC) - timedelta(hours=hours_ago)
    run_id = store.begin_run(
        trigger_key=key,
        kind="review",
        repo=repo,
        pr_number=pr,
        head_sha="a" * 40,
        repo_public=public,
        model="e2e/model",
        prompt_version="2026-11-23.2",
        app_version="0.3.5",
        budgets={"max_steps": 15, "max_tokens": 200000},
    )
    store.add_step(
        run_id,
        index=0,
        started_at=started,
        duration_s=4.2,
        tokens=1800,
        input_messages=[{"role": "user", "content": "Revise este diff."}],
        response_content="Vou ler o arquivo.",
        reasoning="Preciso conferir o arquivo antes de opinar.",
        tool_calls=[{"id": "c1", "name": "read_file", "arguments": '{"path": "a.py"}'}],
        tool_results=[ToolResult("c1", "read_file", 0.02, "def f(): pass")],
    )
    for item in findings:
        store.add_finding(run_id, item)
    store.finish_run(
        run_id,
        outcome=outcome,
        steps=1,
        tokens=1800,
        duration_s=4.2,
        error_category="model_api" if error else None,
        error_message=error,
    )
    # Move the run back in time so the list shows a believable "when".
    store._db().execute(
        "UPDATE trace_run SET started_at = ? WHERE id = ?",
        (started.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", run_id),
    )


def seed(store: TraceStore) -> None:
    _run(
        store,
        key="k1",
        repo="acme/billing",
        pr=12,
        public=True,
        outcome=RunOutcome.COMPLETE,
        hours_ago=1,
        findings=[
            _finding("billing.py", 10, "high", "security", "Senha escrita no código."),
            _finding(
                "billing.py",
                20,
                "medium",
                "design",
                "Cadeia de condicionais por tipo.",
                diff="-    if kind == 'a':\n+    rate = RATES.get(kind, 0)",
            ),
            _finding("billing.py", 30, "low", "readability", "Número mágico.", Disposition.SUMMARY),
        ],
    )
    _run(
        store,
        key="k2",
        repo="acme/billing",
        pr=13,
        public=True,
        outcome=RunOutcome.PARTIAL,
        hours_ago=5,
        findings=[_finding("api.py", 4, "medium", "error-handling", "Exceção engolida.")],
    )
    _run(
        store,
        key="k3",
        repo="acme/web",
        pr=7,
        public=True,
        outcome=RunOutcome.FAILED,
        hours_ago=26,
        findings=[],
        error="Falha ao chamar o modelo.",
    )
    _run(
        store,
        key="k4",
        repo="luk3rr/pilot",
        pr=5,
        public=True,
        outcome=RunOutcome.COMPLETE,
        hours_ago=50,
        findings=[_finding("discount.py", 9, "high", "security", "Segredo no código.")],
    )
    _run(
        store,
        key="k5",
        repo="acme/private-secret-repo",
        pr=1,
        public=False,
        outcome=RunOutcome.COMPLETE,
        hours_ago=2,
        findings=[_finding("x.py", 1, "low", "naming", "Nome ambíguo.")],
    )


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    directory = tempfile.mkdtemp(prefix="farejador-e2e-")
    store = TraceStore(Path(directory) / "trace.db").open()
    seed(store)
    store.close()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", create_api(Path(directory) / "trace.db", app_version="0.3.5"))
    if not install_web(app):
        raise SystemExit("the dashboard is not built: run `npm run build` first")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
