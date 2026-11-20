# Filename: store.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""SQLite store of review traces, in its own file next to the state database (ADR-4).

Every free text goes through the per-run ``Sanitizer`` before it is written, so nothing unmasked
and nothing oversized can reach the file (FR-6, FR-14). The store is synchronous and guarded by a
lock; the recorder runs it from a single writer thread. Readers use ``open_readonly``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from farejador.trace.sanitize import Sanitizer

logger = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE trace_run (
    id INTEGER PRIMARY KEY,
    trigger_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    head_sha TEXT,
    repo_public INTEGER,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    app_version TEXT NOT NULL,
    budgets_json TEXT NOT NULL,
    outcome TEXT NOT NULL,
    error_category TEXT,
    error_message TEXT,
    steps INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    duration_s REAL,
    truncated INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE trace_step (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES trace_run(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    duration_s REAL,
    tokens INTEGER NOT NULL DEFAULT 0,
    input_messages_json TEXT NOT NULL,
    response_content TEXT,
    reasoning TEXT,
    tool_calls_json TEXT NOT NULL
);
CREATE TABLE trace_tool_result (
    id INTEGER PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES trace_step(id) ON DELETE CASCADE,
    call_id TEXT NOT NULL,
    name TEXT NOT NULL,
    duration_s REAL,
    content TEXT NOT NULL,
    truncated INTEGER NOT NULL DEFAULT 0,
    original_chars INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE trace_finding (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES trace_run(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    problem TEXT NOT NULL,
    rationale TEXT NOT NULL,
    suggestion TEXT NOT NULL,
    suggestion_diff TEXT,
    diff_dropped INTEGER NOT NULL DEFAULT 0,
    disposition TEXT NOT NULL,
    reason TEXT
);
CREATE INDEX idx_run_public_id ON trace_run(repo_public, id);
CREATE INDEX idx_run_repo_pr ON trace_run(repo, pr_number, id);
CREATE INDEX idx_run_started ON trace_run(started_at);
CREATE INDEX idx_step_run ON trace_step(run_id, idx);
CREATE INDEX idx_finding_run ON trace_finding(run_id);
"""

_MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)

STALE_RUNNING_SECONDS = 3600
READ_BUSY_TIMEOUT_MS = 2000


class TraceUnavailable(Exception):
    """The trace database cannot be opened or used (missing, corrupted, no permission, full)."""


class RunOutcome(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class Disposition(StrEnum):
    INLINE = "inline"
    SUMMARY = "summary"
    DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    duration_s: float
    content: str


@dataclass(frozen=True, slots=True)
class FindingRecord:
    path: str
    line: int
    severity: str
    category: str
    problem: str
    rationale: str
    suggestion: str
    suggestion_diff: str | None
    diff_dropped: bool
    disposition: Disposition
    reason: str | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def format_time(moment: datetime) -> str:
    """The one timestamp format of the file: lexicographic order equals time order."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_readonly(path: Path | str) -> sqlite3.Connection:
    """Open a connection that cannot write: ``mode=ro``, ``query_only`` and a short busy timeout."""
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {READ_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA query_only = ON")
        conn.execute("SELECT 1 FROM trace_run LIMIT 1")
    except (sqlite3.Error, OSError) as exc:
        raise TraceUnavailable(
            f"cannot open the trace for reading ({type(exc).__name__})"
        ) from None
    return conn


class TraceStore:
    """Write side of the trace database."""

    def __init__(
        self,
        path: Path | str,
        *,
        max_item_chars: int = 20_000,
        max_run_bytes: int = 2 * 1024 * 1024,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._path = str(path)
        self._max_item_chars = max_item_chars
        self._max_run_bytes = max_run_bytes
        self._clock = clock
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._sanitizers: dict[int, Sanitizer] = {}

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> Self:
        """Open the file, create it when missing and apply the migrations."""
        try:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            self._conn = conn  # kept at once so a failure below still closes it
            conn.execute("PRAGMA foreign_keys = ON")
            if self._path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()
        except (sqlite3.Error, OSError) as exc:
            self.close()
            raise TraceUnavailable(f"cannot open the trace ({type(exc).__name__})") from None
        return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
            self._sanitizers.clear()

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return int(self._db().execute("PRAGMA user_version").fetchone()[0])

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise TraceUnavailable("the trace store is not open")
        return self._conn

    def _migrate(self) -> None:
        with self._lock:
            conn = self._db()
            current = self.schema_version
            for version, script in enumerate(_MIGRATIONS, start=1):
                if version > current:
                    conn.executescript(script)
                    conn.execute(f"PRAGMA user_version = {version}")

    # -- writing -----------------------------------------------------------

    def begin_run(
        self,
        *,
        trigger_key: str,
        kind: str,
        repo: str,
        pr_number: int,
        head_sha: str | None,
        repo_public: bool | None,
        model: str,
        prompt_version: str,
        app_version: str,
        budgets: Mapping[str, Any],
    ) -> int:
        """Create a ``running`` run and return its id.

        A repository that is private or of unknown visibility downgrades all its older runs
        (FN-11): it only ever goes from public to private, never the other way around.
        """
        public = None if repo_public is None else int(repo_public)
        with self._lock:
            conn = self._db()
            cursor = conn.execute(
                "INSERT INTO trace_run (trigger_key, kind, repo, pr_number, head_sha, repo_public,"
                " model, prompt_version, app_version, budgets_json, outcome, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trigger_key,
                    kind,
                    repo,
                    pr_number,
                    head_sha,
                    public,
                    model,
                    prompt_version,
                    app_version,
                    json.dumps(dict(budgets), sort_keys=True),
                    RunOutcome.RUNNING.value,
                    format_time(self._clock()),
                ),
            )
            run_id = int(cursor.lastrowid or 0)
            if repo_public is not True:
                conn.execute(
                    "UPDATE trace_run SET repo_public = 0"
                    " WHERE repo = ? AND id <> ? AND (repo_public IS NULL OR repo_public = 1)",
                    (repo, run_id),
                )
            self._sanitizers[run_id] = Sanitizer(self._max_item_chars, self._max_run_bytes)
            return run_id

    def add_step(
        self,
        run_id: int,
        *,
        index: int,
        started_at: datetime,
        duration_s: float,
        tokens: int,
        input_messages: Sequence[Mapping[str, Any]],
        response_content: str | None,
        reasoning: str | None,
        tool_calls: Sequence[Mapping[str, str]],
        tool_results: Sequence[ToolResult],
    ) -> None:
        """Record one trip to the model with the tools it called afterwards."""
        with self._lock:
            sanitizer = self._sanitizer(run_id)
            messages = [_clean_message(message, sanitizer) for message in input_messages]
            calls = [
                {
                    "id": call.get("id", ""),
                    "name": call.get("name", ""),
                    "arguments": sanitizer.clean(call.get("arguments", "")).text,
                }
                for call in tool_calls
            ]
            conn = self._db()
            cursor = conn.execute(
                "INSERT INTO trace_step (run_id, idx, started_at, duration_s, tokens,"
                " input_messages_json, response_content, reasoning, tool_calls_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    index,
                    format_time(started_at),
                    duration_s,
                    tokens,
                    json.dumps(messages, ensure_ascii=False),
                    sanitizer.clean(response_content).text
                    if response_content is not None
                    else None,
                    sanitizer.clean(reasoning).text if reasoning is not None else None,
                    json.dumps(calls, ensure_ascii=False),
                ),
            )
            step_id = int(cursor.lastrowid or 0)
            for result in tool_results:
                cleaned = sanitizer.clean(result.content)
                conn.execute(
                    "INSERT INTO trace_tool_result (step_id, call_id, name, duration_s, content,"
                    " truncated, original_chars) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        step_id,
                        result.call_id,
                        result.name,
                        result.duration_s,
                        cleaned.text,
                        int(cleaned.truncated),
                        cleaned.original_chars,
                    ),
                )

    def add_finding(self, run_id: int, finding: FindingRecord) -> None:
        """Record what became of one finding the model returned."""
        with self._lock:
            sanitizer = self._sanitizer(run_id)
            diff = finding.suggestion_diff
            self._db().execute(
                "INSERT INTO trace_finding (run_id, path, line, severity, category, problem,"
                " rationale, suggestion, suggestion_diff, diff_dropped, disposition, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    sanitizer.clean(finding.path).text,
                    finding.line,
                    finding.severity,
                    finding.category,
                    sanitizer.clean(finding.problem).text,
                    sanitizer.clean(finding.rationale).text,
                    sanitizer.clean(finding.suggestion).text,
                    sanitizer.clean(diff).text if diff is not None else None,
                    int(finding.diff_dropped),
                    finding.disposition.value,
                    finding.reason,
                ),
            )

    def finish_run(
        self,
        run_id: int,
        *,
        outcome: RunOutcome,
        steps: int,
        tokens: int,
        duration_s: float,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._lock:
            sanitizer = self._sanitizer(run_id)
            message = sanitizer.clean(error_message).text if error_message else None
            self._db().execute(
                "UPDATE trace_run SET outcome = ?, steps = ?, tokens = ?, duration_s = ?,"
                " error_category = ?, error_message = ?, truncated = ?, finished_at = ?"
                " WHERE id = ?",
                (
                    outcome.value,
                    steps,
                    tokens,
                    duration_s,
                    error_category,
                    message,
                    int(sanitizer.truncated),
                    format_time(self._clock()),
                    run_id,
                ),
            )
            self._sanitizers.pop(run_id, None)

    # -- housekeeping ------------------------------------------------------

    def mark_stale_running(self, older_than_s: int = STALE_RUNNING_SECONDS) -> int:
        """Turn runs left ``running`` by a dead process into ``incomplete`` (FN-2)."""
        cutoff = format_time(self._clock() - timedelta(seconds=older_than_s))
        with self._lock:
            cursor = self._db().execute(
                "UPDATE trace_run SET outcome = ? WHERE outcome = ? AND started_at < ?",
                (RunOutcome.INCOMPLETE.value, RunOutcome.RUNNING.value, cutoff),
            )
            return cursor.rowcount

    def delete_runs_before(self, cutoff: datetime, limit: int) -> int:
        """Delete up to ``limit`` runs older than ``cutoff``; the children go with them."""
        with self._lock:
            cursor = self._db().execute(
                "DELETE FROM trace_run WHERE id IN"
                " (SELECT id FROM trace_run WHERE started_at < ? ORDER BY id LIMIT ?)",
                (format_time(cutoff), limit),
            )
            return cursor.rowcount

    def count_runs(self) -> int:
        with self._lock:
            return int(self._db().execute("SELECT COUNT(*) FROM trace_run").fetchone()[0])

    @property
    def clock(self) -> Callable[[], datetime]:
        return self._clock

    # -- internals ---------------------------------------------------------

    def _sanitizer(self, run_id: int) -> Sanitizer:
        sanitizer = self._sanitizers.get(run_id)
        if sanitizer is None:
            # A run reopened after a restart, or already finished: sanitize with a fresh budget.
            sanitizer = Sanitizer(self._max_item_chars, self._max_run_bytes)
            self._sanitizers[run_id] = sanitizer
        return sanitizer


def _clean_optional(sanitizer: Sanitizer, value: str | None) -> str | None:
    return None if value is None else sanitizer.clean(value).text


def _clean_message(message: Mapping[str, Any], sanitizer: Sanitizer) -> dict[str, Any]:
    """Keep the role and the text of a chat message, sanitized; drop everything else."""
    content = message.get("content")
    cleaned: dict[str, Any] = {
        "role": str(message.get("role", "")),
        "content": sanitizer.clean(content if isinstance(content, str) else None).text,
    }
    if "tool_call_id" in message:
        cleaned["tool_call_id"] = str(message["tool_call_id"])
    return cleaned
