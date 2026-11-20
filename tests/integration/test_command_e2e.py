# Filename: test_command_e2e.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The whole command cycle through the dispatcher: partial fix, manual resolution, fresh review,
unauthorised user and duplicate delivery (FR-16, FR-17, FR-18, US-7, US-8)."""

import json
from pathlib import Path

import httpx
import respx
from tests.command_env import build_cmd_env, thread_node
from tests.factories import make_command, make_first
from tests.llm_fakes import call, finding, reply, submit_review
from tests.pipeline_env import API, REPO

from farejador.dispatcher import Dispatcher, SubmitResult
from farejador.models import TriggerKind
from farejador.state.store import Outcome, ThreadStatus, TriggerStatus


async def test_the_full_command_cycle(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [
            reply(
                call(
                    "submit_verdicts",
                    {
                        "verdicts": [
                            {"thread_id": "T1", "fixed": True, "note": "guarded now"},
                            {"thread_id": "T2", "fixed": False, "note": "still there"},
                        ]
                    },
                )
            ),
            reply(submit_review([finding("b.py", 2, message="Fresh finding.")])),
        ],
        threads=[thread_node("T1"), thread_node("T2")],
    )
    env = cmd.env
    respx_mock.get(f"{API}/repos/{REPO}/collaborators/eve/permission").mock(
        return_value=httpx.Response(200, json={"role_name": "read", "permission": "read"})
    )

    # the PR was reviewed earlier by the first-review flow
    first = make_first(1, repo=REPO)
    env.store.try_claim(first)
    env.store.record_run(
        first.key, steps=2, tokens=900, duration_s=3.0, findings=2, outcome=Outcome.DONE
    )
    env.store.mark(first.key, TriggerStatus.DONE)
    env.store.add_thread("T1", run_id=None, repo=REPO, pr_number=1, path="b.py", line=2)
    env.store.add_thread("T2", run_id=None, repo=REPO, pr_number=1, path="b.py", line=2)

    dispatcher = Dispatcher(
        env.store,
        {
            TriggerKind.FIRST_REVIEW: env.pipeline.run,
            TriggerKind.COMMAND: cmd.handler.run,
        },
        workers=1,
        bot_login="farejador[bot]",
    )

    async def submit_and_wait(trigger):  # type: ignore[no-untyped-def]
        await dispatcher.start()
        result = await dispatcher.submit(trigger)
        await dispatcher.stop()
        return result

    # 1. bob mentions Farejador: T1 was fixed and is resolved, T2 is still pending
    assert await submit_and_wait(make_command(10, sender="bob")) is SubmitResult.ENQUEUED
    assert cmd.resolved_ids == ["T1"]
    assert env.review_route.call_count == 0
    status = json.loads(env.comment_route.calls.last.request.content)["body"]
    assert "Resolvidos: 1 · Ainda pendentes: 1" in status
    stored = {t.thread_id: t.status for t in env.store.list_threads(REPO, 1)}
    assert stored == {"T1": ThreadStatus.RESOLVED, "T2": ThreadStatus.OPEN}

    # 2. the same delivery again changes nothing
    assert await submit_and_wait(make_command(10, sender="bob")) is SubmitResult.DUPLICATE
    assert env.comment_route.call_count == 1

    # 3. a reader tries the command: nothing happens and nothing is said
    assert await submit_and_wait(make_command(11, sender="eve")) is SubmitResult.ENQUEUED
    assert env.comment_route.call_count == 1
    assert env.review_route.call_count == 0
    eve = env.store.get_trigger("cmd:11")
    assert eve is not None
    assert eve.status is TriggerStatus.DONE

    # 4. the developer resolves T2 by hand on GitHub and mentions Farejador again
    for node in cmd.threads:
        node["isResolved"] = True
    assert await submit_and_wait(make_command(12, sender="bob")) is SubmitResult.ENQUEUED

    # no open threads are left, so this time a fresh review is posted at the current head
    assert env.review_route.call_count == 1
    review = json.loads(env.review_route.calls.last.request.content)
    assert review["commit_id"] == env.sha
    assert [c["line"] for c in review["comments"]] == [2]
    assert "Fresh finding." in review["comments"][0]["body"]
    assert env.comment_route.call_count == 1  # no extra status comment
    final = {t.thread_id: t.status for t in env.store.list_threads(REPO, 1)}
    assert final == {"T1": ThreadStatus.RESOLVED, "T2": ThreadStatus.RESOLVED}
    done = env.store.get_trigger("cmd:12")
    assert done is not None
    assert done.status is TriggerStatus.DONE
    assert len(env.llm.calls) == 2  # one re-evaluation and one review conversation
