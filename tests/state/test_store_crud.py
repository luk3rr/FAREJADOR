# Filename: test_store_crud.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from tests.factories import make_first

from farejador.state.store import Outcome, StateStore, ThreadStatus, TriggerStatus


def test_mark_updates_status_and_error(store: StateStore) -> None:
    trigger = make_first()
    store.try_claim(trigger)
    store.mark(trigger.key, TriggerStatus.FAILED, "ModelApiError")
    record = store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.FAILED, "ModelApiError")


def test_unknown_trigger_returns_none(store: StateStore) -> None:
    assert store.get_trigger("missing") is None


def test_has_review_run_only_counts_finished_reviews(store: StateStore) -> None:
    trigger = make_first(pr=3)
    store.try_claim(trigger)
    assert store.has_review_run("o/r", 3) is False
    store.record_run(
        trigger.key, steps=1, tokens=10, duration_s=0.5, findings=0, outcome=Outcome.FAILED_MODEL
    )
    assert store.has_review_run("o/r", 3) is False
    store.record_run(
        trigger.key, steps=2, tokens=20, duration_s=1.0, findings=1, outcome=Outcome.PARTIAL
    )
    assert store.has_review_run("o/r", 3) is True
    assert store.has_review_run("o/r", 4) is False
    assert store.has_review_run("other/repo", 3) is False


def test_threads_can_be_added_listed_and_resolved(store: StateStore) -> None:
    trigger = make_first()
    store.try_claim(trigger)
    run_id = store.record_run(
        trigger.key, steps=1, tokens=1, duration_s=0.1, findings=2, outcome=Outcome.DONE
    )
    store.add_thread("T1", run_id=run_id, repo="o/r", pr_number=1, path="a.py", line=3)
    store.add_thread("T2", run_id=run_id, repo="o/r", pr_number=1, path="b.py", line=9)
    store.add_thread("T3", run_id=None, repo="o/r", pr_number=2, path=None, line=None)

    assert [t.thread_id for t in store.list_threads("o/r", 1)] == ["T1", "T2"]
    store.set_thread_status("T1", ThreadStatus.RESOLVED)
    open_threads = store.list_threads("o/r", 1, ThreadStatus.OPEN)
    assert [t.thread_id for t in open_threads] == ["T2"]
    assert open_threads[0].path == "b.py"
    resolved = store.list_threads("o/r", 1, ThreadStatus.RESOLVED)
    assert [t.thread_id for t in resolved] == ["T1"]


def test_cursor_roundtrip_and_update(store: StateStore) -> None:
    assert store.get_cursor("o/r:pulls") is None
    store.set_cursor("o/r:pulls", "etag-1", None)
    assert store.get_cursor("o/r:pulls") == ("etag-1", None)
    store.set_cursor("o/r:pulls", "etag-2", "2026-11-20T10:00:00Z")
    assert store.get_cursor("o/r:pulls") == ("etag-2", "2026-11-20T10:00:00Z")


def test_skipped_triggers_can_be_claimed_again_but_done_and_failed_cannot(
    store: StateStore,
) -> None:
    trigger = make_first()
    assert store.try_claim(trigger)
    store.mark(trigger.key, TriggerStatus.SKIPPED, "draft")
    assert store.try_claim(trigger) is True
    record = store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.CLAIMED, None)
    assert store.try_claim(trigger) is False  # claimed again, so a duplicate now

    for final in (TriggerStatus.DONE, TriggerStatus.FAILED):
        store.mark(trigger.key, final, "x")
        assert store.try_claim(trigger) is False
