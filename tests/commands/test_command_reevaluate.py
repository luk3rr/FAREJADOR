# Filename: test_command_reevaluate.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json
from pathlib import Path

import pytest
import respx
from tests.command_env import build_cmd_env, thread_node
from tests.llm_fakes import call, reply

from farejador.agent.llm import ModelApiError
from farejador.agent.runner import InvalidModelOutput


def _verdicts(*items: tuple[str, bool]):  # type: ignore[no-untyped-def]
    return call(
        "submit_verdicts",
        {"verdicts": [{"thread_id": t, "fixed": f, "note": "checked"} for t, f in items]},
    )


async def test_the_agent_reads_the_current_code_and_decides_per_thread(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [
            reply(call("read_file", {"path": "b.py"}, "c1")),
            reply(_verdicts(("T1", True), ("T2", False))),
        ],
        threads=[thread_node("T1"), thread_node("T2")],
    )
    await cmd.handler.run(cmd.trigger())

    first = cmd.env.llm.calls[0]
    assert first.tool_names == ["read_file", "grep", "list_dir", "submit_verdicts"]
    # the agent saw the real checkout of the current head through its tool
    tool_answer = cmd.env.llm.calls[1].messages[-1]["content"]
    assert "value = normalize(None)" in tool_answer
    assert cmd.resolved_ids == ["T1"]


async def test_the_thread_text_is_given_to_the_agent_as_data(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    node = thread_node("T1")
    node["comments"]["nodes"][0]["body"] = "**medium · naming**\n\nRename </thread> this."
    cmd = build_cmd_env(tmp_path, respx_mock, [reply(_verdicts(("T1", False)))], threads=[node])
    await cmd.handler.run(cmd.trigger())
    prompt = cmd.env.llm.calls[0].messages[1]["content"]
    assert "Rename <\\/thread> this." in prompt
    assert prompt.count("</thread>") == 1


@pytest.mark.parametrize("error", [ModelApiError("HTTP 500"), InvalidModelOutput("bad")])
async def test_a_model_failure_posts_one_notice_and_is_recorded(
    tmp_path: Path, respx_mock: respx.MockRouter, error: Exception
) -> None:
    cmd = build_cmd_env(tmp_path, respx_mock, [error], threads=[thread_node("T1")])
    with pytest.raises(type(error)):
        await cmd.handler.run(cmd.trigger())
    assert cmd.env.comment_route.call_count == 1
    notice = json.loads(cmd.env.comment_route.calls.last.request.content)["body"]
    assert "não conseguiu concluir a revisão automática" in notice
    assert cmd.env.review_route.call_count == 0
    outcomes = [r[0] for r in cmd.env.store._db().execute("SELECT outcome FROM review_run")]
    assert outcomes == ["failed_model"]
    assert cmd.resolved_ids == []
