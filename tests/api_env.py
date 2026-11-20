# Filename: api_env.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""A trace database with public, private and unknown runs, and a client for the API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
from tests.trace.helpers import NOW, Clock, finding

from farejador.api.routes import create_api
from farejador.trace.store import (
    Disposition,
    RunOutcome,
    ToolResult,
    TraceStore,
)

PRIVATE_REPO = "acme/secret-project"
SECRET_CODE = "TOP_SECRET_PRIVATE_CODE_LINE"


@dataclass
class Seeded:
    store: TraceStore
    path: Path
    public_ids: list[int]
    private_ids: list[int]
    unknown_ids: list[int]


def make_run(
    store: TraceStore,
    *,
    repo: str,
    public: bool | None,
    pr: int = 1,
    outcome: RunOutcome = RunOutcome.COMPLETE,
    key: str = "k",
    error: tuple[str, str] | None = None,
    steps: int = 2,
    content: str = "conteúdo",
) -> int:
    run_id = store.begin_run(
        trigger_key=key,
        kind="review",
        repo=repo,
        pr_number=pr,
        head_sha="a" * 40,
        repo_public=public,
        model="test/model",
        prompt_version="2026-11-21.2",
        app_version="0.1.0",
        budgets={"max_steps": 15, "max_tokens": 200000, "max_seconds": 300, "max_files": 40},
    )
    for index in range(steps):
        store.add_step(
            run_id,
            index=index,
            started_at=NOW,
            duration_s=1.0 + index,
            tokens=100,
            input_messages=[{"role": "user", "content": f"{content} {index}"}]
            if index == 0
            else [],
            response_content="vou ler" if index == 0 else None,
            reasoning="pensando no diff" if index == 0 else None,
            tool_calls=[{"id": f"c{index}", "name": "read_file", "arguments": '{"path": "a.py"}'}],
            tool_results=[ToolResult(f"c{index}", "read_file", 0.01, f"corpo {content}")],
        )
    store.add_finding(run_id, finding(problem=f"problema {content}"))
    store.add_finding(
        run_id,
        finding(disposition=Disposition.SUMMARY, reason="line_not_added", problem="resumo"),
    )
    store.add_finding(
        run_id, finding(disposition=Disposition.DROPPED, reason="duplicate", problem="dup")
    )
    store.finish_run(
        run_id,
        outcome=outcome,
        steps=steps,
        tokens=100 * steps,
        duration_s=3.0,
        error_category=error[0] if error else None,
        error_message=error[1] if error else None,
    )
    return run_id


def seed(tmp_path: Path, clock: Clock | None = None) -> Seeded:
    clock = clock or Clock()
    store = TraceStore(tmp_path / "trace.db", clock=clock).open()
    public: list[int] = []
    private: list[int] = []
    unknown: list[int] = []
    public.append(make_run(store, repo="o/r", public=True, pr=1, key="a"))
    clock.advance(minutes=1)
    private.append(
        make_run(store, repo=PRIVATE_REPO, public=False, pr=5, key="b", content=SECRET_CODE)
    )
    clock.advance(minutes=1)
    unknown.append(
        make_run(store, repo="x/unknown", public=None, pr=6, key="c", content=SECRET_CODE)
    )
    clock.advance(minutes=1)
    public.append(
        make_run(
            store,
            repo="o/r",
            public=True,
            pr=2,
            key="d",
            outcome=RunOutcome.FAILED,
            error=("model_api", "model API returned HTTP 429"),
            steps=0,
        )
    )
    clock.advance(minutes=1)
    public.append(
        make_run(
            store,
            repo="o/other",
            public=True,
            pr=1,
            key="e",
            outcome=RunOutcome.PARTIAL,
            error=("budget", "Revisão interrompida: limite de passos atingido."),
        )
    )
    return Seeded(store, tmp_path / "trace.db", public, private, unknown)


@asynccontextmanager
async def api_client(path: Path, *, retention_days: int = 30) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_api(path, retention_days=retention_days))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


__all__ = [
    "NOW",
    "PRIVATE_REPO",
    "SECRET_CODE",
    "Seeded",
    "api_client",
    "make_run",
    "seed",
    "timedelta",
]
