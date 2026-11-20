# Filename: test_polling_prs.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import respx
from tests.polling_env import build_world, pr

from farejador.models import Trigger, TriggerSource
from farejador.state.store import Outcome, StateStore, TriggerStatus


async def test_new_non_draft_prs_produce_one_first_review_trigger(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1, sha="abc"), pr(2, draft=True)])
    stats = await world.source.poll_once()

    assert world.submit.keys == ["first:o/r#1"]
    trigger = world.submit.triggers[0]
    assert (trigger.installation_id, trigger.pr_number, trigger.head_sha) == (7, 1, "abc")
    assert (trigger.sender_login, trigger.source) == ("alice", TriggerSource.POLLING)
    assert (stats.repos, stats.open_prs, stats.first_reviews) == (1, 2, 1)


async def test_the_next_cycle_without_changes_produces_nothing(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    world = build_world(respx_mock, store, prs=[pr(1)])
    await world.source.poll_once()
    stats = await world.source.poll_once()
    assert world.submit.keys == ["first:o/r#1"]
    assert stats.first_reviews == 0


async def test_prs_that_were_reviewed_or_failed_are_not_submitted_again(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    done = Trigger.first_review(
        repo="o/r", installation_id=7, pr_number=1, sender_login="a", source=TriggerSource.POLLING
    )
    failed = Trigger.first_review(
        repo="o/r", installation_id=7, pr_number=2, sender_login="a", source=TriggerSource.POLLING
    )
    store.try_claim(done)
    store.record_run(done.key, steps=1, tokens=1, duration_s=0.1, findings=0, outcome=Outcome.DONE)
    store.mark(done.key, TriggerStatus.DONE)
    store.try_claim(failed)
    store.mark(failed.key, TriggerStatus.FAILED, "ModelApiError")

    world = build_world(respx_mock, store, prs=[pr(1), pr(2), pr(3)])
    await world.source.poll_once()
    assert world.submit.keys == ["first:o/r#3"]


async def test_a_pr_with_an_existing_review_is_not_submitted_even_without_a_trigger_record(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    earlier = Trigger.command(
        repo="o/r", installation_id=7, pr_number=1, comment_id=5, sender_login="a",
        source=TriggerSource.POLLING,
    )  # fmt: skip
    store.try_claim(earlier)
    store.record_run(
        earlier.key, steps=1, tokens=1, duration_s=0.1, findings=0, outcome=Outcome.DONE
    )
    world = build_world(respx_mock, store, prs=[pr(1)])
    await world.source.poll_once()
    assert world.submit.keys == []


async def test_a_draft_that_becomes_ready_is_picked_up_on_a_later_cycle(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    import httpx

    world = build_world(respx_mock, store, prs=[pr(1, draft=True)])
    await world.source.poll_once()
    assert world.submit.keys == []

    world.prs_route.mock(
        return_value=httpx.Response(200, json=[pr(1, draft=False)], headers={"ETag": '"prs-2"'})
    )
    await world.source.poll_once()
    assert world.submit.keys == ["first:o/r#1"]


async def test_a_skipped_trigger_is_submitted_again_when_the_pr_is_still_eligible(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    skipped = Trigger.first_review(
        repo="o/r", installation_id=7, pr_number=1, sender_login="a", source=TriggerSource.POLLING
    )
    store.try_claim(skipped)
    store.mark(skipped.key, TriggerStatus.SKIPPED, "draft")
    world = build_world(respx_mock, store, prs=[pr(1)])
    await world.source.poll_once()
    assert world.submit.keys == ["first:o/r#1"]


async def test_every_repository_of_every_installation_is_polled(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    import httpx

    world = build_world(respx_mock, store, prs=[pr(1)], repos=["o/r", "o/s"])
    respx_mock.get("https://api.github.com/repos/o/s/pulls").mock(
        return_value=httpx.Response(200, json=[pr(4)], headers={"ETag": '"s"'})
    )
    respx_mock.get("https://api.github.com/repos/o/s/issues/4/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    stats = await world.source.poll_once()
    assert sorted(world.submit.keys) == ["first:o/r#1", "first:o/s#4"]
    assert stats.repos == 2


async def test_an_error_in_one_repository_does_not_stop_the_others(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    import httpx

    world = build_world(respx_mock, store, prs=[pr(1)], repos=["o/bad", "o/r"])
    respx_mock.get("https://api.github.com/repos/o/bad/pulls").mock(
        return_value=httpx.Response(403, json={"message": "forbidden"})
    )
    stats = await world.source.poll_once()
    assert world.submit.keys == ["first:o/r#1"]
    assert stats.errors == 1


async def test_a_failure_listing_repositories_is_counted_and_skipped(
    store: StateStore, respx_mock: respx.MockRouter
) -> None:
    import httpx

    world = build_world(respx_mock, store, prs=[pr(1)])
    world.repos_route.mock(return_value=httpx.Response(500, json={"message": "down"}))
    stats = await world.source.poll_once()
    assert stats.errors == 1
    assert world.submit.keys == []
