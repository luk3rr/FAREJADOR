# Filename: test_runner_loop.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json

import pytest
from tests.llm_fakes import ScriptedLLM, call, finding, reply, submit_review

from farejador.agent.llm import ModelApiError
from farejador.agent.runner import AgentRunner, Budget, InvalidModelOutput, ReviewRun
from farejador.tools import RepoTools

DIFF = '<file path="b.py">\n    2 | + print(normalize(" x "))\n</file>'


async def _review(llm: ScriptedLLM, tools: RepoTools, title: str = "t") -> ReviewRun:
    runner = AgentRunner(llm, "test/model", Budget())
    return await runner.review(pr_title=title, numbered_diff=DIFF, skipped=[], tools=tools)


async def test_agent_reads_another_file_and_the_result_reflects_it(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [
            reply(call("read_file", {"path": "a.py"}, "c1"), tokens=120),
            reply(
                submit_review(
                    [finding("b.py", 2, message="normalize() strips only; None is not handled.")],
                    summary="One issue.",
                ),
                tokens=80,
            ),
        ]
    )
    run = await _review(llm, repo_tools, "Add b")

    assert (run.steps, run.tokens, run.partial, run.note) == (1, 200, False, None)
    assert [(f.file, f.line) for f in run.result.findings] == [("b.py", 2)]
    # the tool result from the real checkout went back to the model
    tool_message = llm.calls[1].messages[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "c1"
    assert "def normalize(user):" in tool_message["content"]
    # the first request carried the system rules, the few-shot examples and the numbered diff
    first = llm.calls[0]
    assert first.tool_choice == "auto"
    assert first.tool_names == ["read_file", "grep", "list_dir", "submit_review"]
    assert "NÃO SINALIZAR" in first.messages[0]["content"]
    assert "2 | + print" in first.messages[1]["content"]


async def test_a_clean_diff_yields_no_findings(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM([reply(submit_review([], summary="Nothing relevant."))])
    run = await _review(llm, repo_tools)
    assert run.result.findings == []
    assert run.result.summary == "Nothing relevant."
    assert (run.steps, run.partial) == (0, False)


async def test_requests_outside_the_repository_are_refused_and_the_loop_continues(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM(
        [
            reply(call("read_file", {"path": "../outside.txt"}, "c1")),
            reply(submit_review()),
        ]
    )
    run = await _review(llm, repo_tools)
    answer = llm.calls[1].messages[-1]["content"]
    assert "fora do repositório" in answer
    assert "outside secret" not in answer
    assert run.steps == 1


async def test_unknown_tools_and_bad_arguments_are_explained_to_the_model(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM(
        [
            reply(
                call("delete_everything", {}, "c1"),
                call("read_file", "{not json", "c2"),
                call("grep", "[1, 2]", "c3"),
            ),
            reply(submit_review()),
        ]
    )
    run = await _review(llm, repo_tools)
    answers = {
        m["tool_call_id"]: m["content"] for m in llm.calls[1].messages if m["role"] == "tool"
    }
    assert "ferramenta desconhecida: delete_everything" in answers["c1"]
    assert "não são um JSON válido" in answers["c2"]
    assert "devem ser um objeto JSON" in answers["c3"]
    assert run.steps == 3


async def test_several_calls_in_one_reply_run_in_order_and_each_counts(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM(
        [
            reply(
                call("list_dir", {}, "c1"),
                call("grep", {"pattern": "normalize"}, "c2"),
                call("read_file", {"path": "b.py"}, "c3"),
            ),
            reply(submit_review()),
        ]
    )
    run = await _review(llm, repo_tools)
    tool_messages = [m for m in llm.calls[1].messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2", "c3"]
    assert "a.py" in tool_messages[0]["content"]
    assert "a.py:1:def normalize" in tool_messages[1]["content"]
    assert run.steps == 3


async def test_the_assistant_turn_is_kept_with_its_tool_calls(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [reply(call("list_dir", {}, "c1"), content="let me look"), reply(submit_review())]
    )
    await _review(llm, repo_tools)
    assistant = llm.calls[1].messages[-2]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "let me look"
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "list_dir"


async def test_finishing_alongside_other_calls_returns_immediately(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM([reply(call("list_dir", {}, "c1"), submit_review([finding("b.py", 2)]))])
    run = await _review(llm, repo_tools)
    assert len(run.result.findings) == 1
    assert len(llm.calls) == 1


async def test_text_only_replies_get_a_reminder_then_a_limit(repo_tools: RepoTools) -> None:
    ok = ScriptedLLM([reply(content="thinking"), reply(content="still"), reply(submit_review())])
    run = await _review(ok, repo_tools)
    assert run.partial is False
    reminder = ok.calls[1].messages[-1]
    assert reminder["role"] == "user"
    assert "submit_review" in reminder["content"]

    stubborn = ScriptedLLM([reply(content="a"), reply(content="b"), reply(content="c")])
    with pytest.raises(InvalidModelOutput, match="did not call a tool"):
        await _review(stubborn, repo_tools)


async def test_the_reminder_counter_resets_after_a_tool_call(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [
            reply(content="a"),
            reply(content="b"),
            reply(call("list_dir", {}, "c1")),
            reply(content="c"),
            reply(content="d"),
            reply(submit_review()),
        ]
    )
    run = await _review(llm, repo_tools)
    assert run.partial is False


async def test_model_api_errors_propagate(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM([ModelApiError("model API returned HTTP 500")])
    with pytest.raises(ModelApiError):
        await _review(llm, repo_tools)


async def test_tool_results_are_json_serialisable_for_the_next_request(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM([reply(call("read_file", {"path": "a.py"}, "c1")), reply(submit_review())])
    await _review(llm, repo_tools)
    json.dumps(llm.calls[1].messages)
