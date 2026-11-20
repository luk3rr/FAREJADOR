# Filename: test_perf.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Latency and memory of the API with 10 thousand runs (NFR-3.1, NFR-3.2, NFR-4, NFR-5)."""

import json
import sqlite3
import statistics
import time
import tracemalloc
from pathlib import Path

from tests.api_env import api_client, make_run
from tests.trace.helpers import Clock

from farejador.trace.store import TraceStore


def _bulk(tmp_path: Path, runs: int) -> Path:
    path = tmp_path / "trace.db"
    TraceStore(path).open().close()
    conn = sqlite3.connect(path)
    rows = [
        (
            f"k{i}",
            "review",
            f"o/r{i % 20}",
            i % 400 + 1,
            "a" * 40,
            1 if i % 5 else 0,
            "m",
            "p",
            "v",
            "{}",
            "complete" if i % 7 else "failed",
            3,
            1000,
            2.0,
            0,
            f"2026-11-{1 + i % 28:02d}T00:00:00Z",
        )
        for i in range(runs)
    ]
    conn.executemany(
        "INSERT INTO trace_run (trigger_key, kind, repo, pr_number, head_sha, repo_public, model,"
        " prompt_version, app_version, budgets_json, outcome, steps, tokens, duration_s, truncated,"
        " started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO trace_finding (run_id, path, line, severity, category, problem, rationale,"
        " suggestion, disposition) VALUES (?,?,?,?,?,?,?,?,?)",
        [(i, "a.py", 1, "low", "other", "p", "r", "s", "inline") for i in range(1, runs + 1, 3)],
    )
    conn.commit()
    conn.close()
    return path


async def test_the_list_is_fast_and_small_with_ten_thousand_runs(tmp_path: Path) -> None:
    path = _bulk(tmp_path, 10_000)
    timings: list[float] = []
    async with api_client(path) as client:
        for _ in range(40):
            started = time.perf_counter()
            response = await client.get("/reviews", params={"limit": 50})
            timings.append(time.perf_counter() - started)
        filtered = await client.get("/reviews", params={"repo": "o/r3", "outcome": "complete"})
    assert response.status_code == 200 and len(response.json()["items"]) == 50
    assert len(response.content) < 100_000  # NFR-3.2
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert p95 < 0.2, f"p95 {p95 * 1000:.0f} ms"
    assert filtered.status_code == 200 and filtered.json()["items"]


async def test_the_detail_of_a_heavy_run_stays_within_the_time_and_size_limits(
    tmp_path: Path,
) -> None:
    store = TraceStore(tmp_path / "trace.db", clock=Clock(), max_item_chars=100_000).open()
    run_id = make_run(store, repo="o/r", public=True, steps=15, content="x" * 100_000)
    store.close()
    timings: list[float] = []
    async with api_client(tmp_path / "trace.db") as client:
        for _ in range(20):
            started = time.perf_counter()
            response = await client.get(f"/reviews/{run_id}")
            timings.append(time.perf_counter() - started)
    assert response.status_code == 200 and len(response.json()["steps"]) == 15
    assert len(response.content) < 3_000_000  # NFR-3.2
    assert statistics.median(timings) < 0.5
    assert max(timings) < 1.0


async def test_reading_by_page_does_not_load_the_whole_table(tmp_path: Path) -> None:
    path = _bulk(tmp_path, 10_000)
    async with api_client(path) as client:
        await client.get("/reviews", params={"limit": 50})  # warm up imports and caches
        tracemalloc.start()
        await client.get("/reviews", params={"limit": 50})
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert peak < 5_000_000, f"peak {peak / 1e6:.1f} MB"
    assert json.dumps({"ok": True})
