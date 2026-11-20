# Filename: store.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""SQLite state store (ADR-2, contract C-G).

The store is synchronous and guarded by a lock so it can be shared across threads;
async callers run it through ``asyncio.to_thread``.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from farejador.models import Trigger

_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE "trigger" (
        key TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        repo TEXT NOT NULL,
        pr_number INTEGER NOT NULL,
        head_sha TEXT,
        status TEXT NOT NULL,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE review_run (
        id INTEGER PRIMARY KEY,
        trigger_key TEXT NOT NULL REFERENCES "trigger"(key),
        steps INTEGER,
        tokens INTEGER,
        duration_s REAL,
        findings INTEGER,
        outcome TEXT
    );
    CREATE TABLE bot_thread (
        thread_id TEXT PRIMARY KEY,
        run_id INTEGER REFERENCES review_run(id),
        repo TEXT NOT NULL,
        pr_number INTEGER NOT NULL,
        path TEXT,
        line INTEGER,
        status TEXT NOT NULL
    );
    CREATE TABLE poll_cursor (
        key TEXT PRIMARY KEY,
        etag TEXT,
        last_seen TEXT
    );
    CREATE INDEX idx_trigger_pr ON "trigger"(repo, pr_number);
    CREATE INDEX idx_thread_pr ON bot_thread(repo, pr_number, status);
    """,
)

INTERRUPTED_ERROR = "InterruptedByRestart"


class TriggerStatus(StrEnum):
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Outcome(StrEnum):
    DONE = "done"
    PARTIAL = "partial"
    FAILED_MODEL = "failed_model"
    FAILED_GITHUB = "failed_github"
    FAILED_INTERNAL = "failed_internal"


class ThreadStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class TriggerRecord:
    key: str
    kind: str
    repo: str
    pr_number: int
    head_sha: str | None
    status: TriggerStatus
    error: str | None


@dataclass(frozen=True, slots=True)
class BotThread:
    thread_id: str
    run_id: int | None
    repo: str
    pr_number: int
    path: str | None
    line: int | None
    status: ThreadStatus


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StateStore:
    """Persistent state with atomic claiming of triggers."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> Self:
        """Open the database, creating parent folders and applying migrations."""
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        if self._path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        self._conn = conn
        self._migrate()
        return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        row = self._db().execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore is not open")
        return self._conn

    def _migrate(self) -> None:
        with self._lock:
            conn = self._db()
            current = self.schema_version
            for version, script in enumerate(_MIGRATIONS, start=1):
                if version > current:
                    conn.executescript(script)
                    conn.execute(f"PRAGMA user_version = {version}")

    # -- triggers ----------------------------------------------------------

    def try_claim(self, trigger: Trigger) -> bool:
        """Atomically register a trigger; return False when it was already claimed.

        A key whose previous trigger was ``skipped`` (for example a draft pull request that
        was not eligible yet) can be claimed again; ``done`` and ``failed`` keys cannot.
        """
        now = _now()
        with self._lock:
            try:
                self._db().execute(
                    'INSERT INTO "trigger"'
                    " (key, kind, repo, pr_number, head_sha, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        trigger.key,
                        trigger.kind.value,
                        trigger.repo,
                        trigger.pr_number,
                        trigger.head_sha,
                        TriggerStatus.CLAIMED.value,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                reclaimed = self._db().execute(
                    'UPDATE "trigger" SET status = ?, error = NULL, head_sha = ?, updated_at = ?'
                    " WHERE key = ? AND status = ?",
                    (
                        TriggerStatus.CLAIMED.value,
                        trigger.head_sha,
                        now,
                        trigger.key,
                        TriggerStatus.SKIPPED.value,
                    ),
                )
                return reclaimed.rowcount == 1
        return True

    def mark(self, key: str, status: TriggerStatus, error: str | None = None) -> None:
        with self._lock:
            self._db().execute(
                'UPDATE "trigger" SET status = ?, error = ?, updated_at = ? WHERE key = ?',
                (status.value, error, _now(), key),
            )

    def get_trigger(self, key: str) -> TriggerRecord | None:
        with self._lock:
            row = (
                self._db()
                .execute(
                    "SELECT key, kind, repo, pr_number, head_sha, status, error"
                    ' FROM "trigger" WHERE key = ?',
                    (key,),
                )
                .fetchone()
            )
        if row is None:
            return None
        return TriggerRecord(
            key=row[0],
            kind=row[1],
            repo=row[2],
            pr_number=row[3],
            head_sha=row[4],
            status=TriggerStatus(row[5]),
            error=row[6],
        )

    def fail_interrupted(self) -> int:
        """Mark triggers left claimed or running by a previous process as failed (A15)."""
        with self._lock:
            cursor = self._db().execute(
                'UPDATE "trigger" SET status = ?, error = ?, updated_at = ? WHERE status IN (?, ?)',
                (
                    TriggerStatus.FAILED.value,
                    INTERRUPTED_ERROR,
                    _now(),
                    TriggerStatus.CLAIMED.value,
                    TriggerStatus.RUNNING.value,
                ),
            )
            return cursor.rowcount

    # -- runs --------------------------------------------------------------

    def record_run(
        self,
        trigger_key: str,
        *,
        steps: int,
        tokens: int,
        duration_s: float,
        findings: int,
        outcome: Outcome,
    ) -> int:
        with self._lock:
            cursor = self._db().execute(
                "INSERT INTO review_run (trigger_key, steps, tokens, duration_s, findings, outcome)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (trigger_key, steps, tokens, duration_s, findings, outcome.value),
            )
            run_id = cursor.lastrowid
        if run_id is None:  # pragma: no cover - sqlite always sets lastrowid on INSERT
            raise RuntimeError("review_run insert returned no id")
        return run_id

    def has_review_run(self, repo: str, pr_number: int) -> bool:
        """Whether a review (finished or partial) already exists for this pull request."""
        with self._lock:
            row = (
                self._db()
                .execute(
                    'SELECT 1 FROM review_run r JOIN "trigger" t ON t.key = r.trigger_key'
                    " WHERE t.repo = ? AND t.pr_number = ? AND r.outcome IN (?, ?) LIMIT 1",
                    (repo, pr_number, Outcome.DONE.value, Outcome.PARTIAL.value),
                )
                .fetchone()
            )
        return row is not None

    # -- bot threads -------------------------------------------------------

    def add_thread(
        self,
        thread_id: str,
        *,
        run_id: int | None,
        repo: str,
        pr_number: int,
        path: str | None,
        line: int | None,
    ) -> None:
        with self._lock:
            self._db().execute(
                "INSERT OR REPLACE INTO bot_thread"
                " (thread_id, run_id, repo, pr_number, path, line, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (thread_id, run_id, repo, pr_number, path, line, ThreadStatus.OPEN.value),
            )

    def set_thread_status(self, thread_id: str, status: ThreadStatus) -> None:
        with self._lock:
            self._db().execute(
                "UPDATE bot_thread SET status = ? WHERE thread_id = ?",
                (status.value, thread_id),
            )

    def list_threads(
        self, repo: str, pr_number: int, status: ThreadStatus | None = None
    ) -> list[BotThread]:
        query = (
            "SELECT thread_id, run_id, repo, pr_number, path, line, status FROM bot_thread"
            " WHERE repo = ? AND pr_number = ?"
        )
        params: list[object] = [repo, pr_number]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        with self._lock:
            rows = self._db().execute(query + " ORDER BY thread_id", params).fetchall()
        return [
            BotThread(
                thread_id=row[0],
                run_id=row[1],
                repo=row[2],
                pr_number=row[3],
                path=row[4],
                line=row[5],
                status=ThreadStatus(row[6]),
            )
            for row in rows
        ]

    # -- polling cursors ---------------------------------------------------

    def get_cursor(self, key: str) -> tuple[str | None, str | None] | None:
        with self._lock:
            row = (
                self._db()
                .execute("SELECT etag, last_seen FROM poll_cursor WHERE key = ?", (key,))
                .fetchone()
            )
        return None if row is None else (row[0], row[1])

    def set_cursor(self, key: str, etag: str | None, last_seen: str | None) -> None:
        with self._lock:
            self._db().execute(
                "INSERT INTO poll_cursor (key, etag, last_seen) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET etag = excluded.etag,"
                " last_seen = excluded.last_seen",
                (key, etag, last_seen),
            )
