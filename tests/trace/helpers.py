# Filename: helpers.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Shared helpers of the trace tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from farejador.trace.store import (
    Disposition,
    FindingRecord,
    RunOutcome,
    ToolResult,
    TraceStore,
)

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)
SENTINEL = "sk-or-v1-SENTINELSECRETVALUE1234567890"


class Clock:
    """A clock the test can move."""

    def __init__(self, start: datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def make_store(tmp_path: Path, clock: Clock | None = None, **limits: int) -> TraceStore:
    return TraceStore(tmp_path / "trace.db", clock=clock or Clock(), **limits).open()


def begin(
    store: TraceStore,
    *,
    repo: str = "o/r",
    pr: int = 1,
    public: bool | None = True,
    key: str = "k1",
) -> int:
    return store.begin_run(
        trigger_key=key,
        kind="review",
        repo=repo,
        pr_number=pr,
        head_sha="a" * 40,
        repo_public=public,
        model="some/model",
        prompt_version="2026-11-21.2",
        app_version="0.1.0",
        budgets={"max_steps": 15, "max_tokens": 200000},
    )


def one_step(store: TraceStore, run_id: int, *, content: str = "hello", index: int = 0) -> None:
    store.add_step(
        run_id,
        index=index,
        started_at=NOW,
        duration_s=1.5,
        tokens=100,
        input_messages=[{"role": "user", "content": content}],
        response_content="ok",
        reasoning=None,
        tool_calls=[{"id": "c1", "name": "read_file", "arguments": '{"path": "a.py"}'}],
        tool_results=[ToolResult("c1", "read_file", 0.01, "file body")],
    )


def finding(**overrides: object) -> FindingRecord:
    values: dict[str, object] = {
        "path": "a.py",
        "line": 3,
        "severity": "medium",
        "category": "design",
        "problem": "Problema.",
        "rationale": "Racional.",
        "suggestion": "Sugestão.",
        "suggestion_diff": None,
        "diff_dropped": False,
        "disposition": Disposition.INLINE,
        "reason": None,
    }
    values.update(overrides)
    return FindingRecord(**values)  # type: ignore[arg-type]


def finish(store: TraceStore, run_id: int, outcome: RunOutcome = RunOutcome.COMPLETE) -> None:
    store.finish_run(run_id, outcome=outcome, steps=1, tokens=100, duration_s=2.0)
