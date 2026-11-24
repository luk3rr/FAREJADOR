# Filename: test_performance.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Measured limits of the trace store (NFR-1.1, NFR-1.2). Margins are wide to avoid flakiness."""

import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from tests.trace.helpers import Clock, begin, make_store, one_step

from farejador.trace.retention import BATCH_SIZE, purge_expired

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="the time budgets are measured on the Linux server"
)


def test_writing_a_step_takes_well_under_20_ms_on_average(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    run_id = begin(store)
    started = time.perf_counter()
    for index in range(100):
        one_step(store, run_id, index=index, content="m" * 2000)
    average_ms = (time.perf_counter() - started) / 100 * 1000
    assert average_ms < 20, f"{average_ms:.1f} ms per step"


def test_no_purge_batch_holds_the_database_for_100_ms(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    for number in range(2000):
        run_id = begin(store, key=f"k{number}", pr=number + 1)
        one_step(store, run_id)
    clock.advance(days=40)
    cutoff = clock() - timedelta(days=30)

    slowest = 0.0
    while store.count_runs():
        started = time.perf_counter()
        store.delete_runs_before(cutoff, BATCH_SIZE)
        slowest = max(slowest, time.perf_counter() - started)
    assert slowest < 0.1, f"slowest batch took {slowest * 1000:.0f} ms"


def test_the_public_purge_deletes_everything_it_should(tmp_path: Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    for number in range(1200):
        begin(store, key=f"k{number}", pr=number + 1)
    clock.advance(days=40)
    assert purge_expired(store, 30, batch_size=500) == 1200


def test_the_production_batch_size_leaves_a_wide_margin_under_the_100_ms_limit() -> None:
    """500 runs took 67 ms even on a quiet machine, which flaked under load; 100 is safe."""
    assert BATCH_SIZE <= 100
