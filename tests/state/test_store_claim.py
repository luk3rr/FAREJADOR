# Filename: test_store_claim.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import threading
from pathlib import Path

import pytest
from tests.factories import make_command, make_first

from farejador.state.store import StateStore, TriggerStatus


def test_first_claim_wins_and_second_is_rejected(store: StateStore) -> None:
    trigger = make_first()
    assert store.try_claim(trigger) is True
    assert store.try_claim(trigger) is False
    record = store.get_trigger(trigger.key)
    assert record is not None
    assert record.status is TriggerStatus.CLAIMED
    assert record.repo == "o/r"


def test_distinct_keys_do_not_conflict(store: StateStore) -> None:
    assert store.try_claim(make_first(pr=1))
    assert store.try_claim(make_first(pr=2))
    assert store.try_claim(make_command(comment_id=5))


def test_concurrent_claims_have_exactly_one_winner(store: StateStore) -> None:
    trigger = make_first()
    results: list[bool] = []

    def claim() -> None:
        results.append(store.try_claim(trigger))

    threads = [threading.Thread(target=claim) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1


def test_migrations_set_schema_version_and_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.db"
    with StateStore(path) as first:
        assert first.schema_version == 1
    with StateStore(path) as second:
        assert second.schema_version == 1
    assert path.exists()


def test_using_a_closed_store_fails_clearly(tmp_path: Path) -> None:
    unopened = StateStore(tmp_path / "x.db")
    with pytest.raises(RuntimeError, match="not open"):
        unopened.get_trigger("k")


def test_in_memory_store_works() -> None:
    with StateStore(":memory:") as memory:
        assert memory.try_claim(make_first())
