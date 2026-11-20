# Filename: test_list_threads.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from pathlib import Path

import respx
from tests.command_env import build_cmd_env, thread_node
from tests.llm_fakes import call, reply, submit_review

from farejador.review.pipeline import PipelineConfig
from farejador.state.store import ThreadStatus


def _verdicts(*items: tuple[str, bool]):  # type: ignore[no-untyped-def]
    return call(
        "submit_verdicts",
        {"verdicts": [{"thread_id": t, "fixed": f, "note": "n"} for t, f in items]},
    )


async def test_only_open_threads_created_by_the_bot_are_re_evaluated(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", False)))],
        threads=[
            thread_node("T1"),
            thread_node("T2", author="alice"),
            thread_node("T3", resolved=True),
        ],
    )
    await cmd.handler.run(cmd.trigger())
    prompt = cmd.env.llm.calls[0].messages[1]["content"]
    assert '<thread id="T1"' in prompt
    assert 'id="T2"' not in prompt
    assert 'id="T3"' not in prompt


async def test_threads_the_bot_opened_but_the_store_missed_are_added(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path, respx_mock, [reply(_verdicts(("T1", False)))], threads=[thread_node("T1")]
    )
    await cmd.handler.run(cmd.trigger())
    (stored,) = cmd.env.store.list_threads("o/r", 1)
    assert (stored.thread_id, stored.run_id, stored.path, stored.line) == ("T1", None, "b.py", 2)
    assert stored.status is ThreadStatus.OPEN


async def test_threads_resolved_on_github_are_marked_resolved_in_the_store(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(submit_review())],
        threads=[thread_node("T1", resolved=True)],
    )
    cmd.env.store.add_thread("T1", run_id=None, repo="o/r", pr_number=1, path="b.py", line=2)
    await cmd.handler.run(cmd.trigger())
    (stored,) = cmd.env.store.list_threads("o/r", 1)
    assert stored.status is ThreadStatus.RESOLVED


async def test_without_a_known_bot_login_only_stored_threads_count(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(_verdicts(("T1", False)))],
        threads=[thread_node("T1"), thread_node("T2")],
        config=PipelineConfig(bot_login=None),
    )
    cmd.env.store.add_thread("T1", run_id=None, repo="o/r", pr_number=1, path="b.py", line=2)
    await cmd.handler.run(cmd.trigger())
    prompt = cmd.env.llm.calls[0].messages[1]["content"]
    assert '<thread id="T1"' in prompt
    assert 'id="T2"' not in prompt
