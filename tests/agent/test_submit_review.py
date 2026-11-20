# Filename: test_submit_review.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest
from tests.llm_fakes import ScriptedLLM, call, finding, reply, submit_review

from farejador.agent.runner import AgentRunner, InvalidModelOutput
from farejador.tools import RepoTools

DIFF = '<file path="b.py">\n    2 | + x\n</file>'


async def _review(llm: ScriptedLLM, tools: RepoTools):  # type: ignore[no-untyped-def]
    runner = AgentRunner(llm, "m")
    return await runner.review(pr_title="t", numbered_diff=DIFF, skipped=[], tools=tools)


async def test_invalid_json_is_reported_and_the_model_can_retry(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [reply(call("submit_review", "{oops", "c1")), reply(submit_review([finding("b.py", 2)]))]
    )
    run = await _review(llm, repo_tools)
    assert len(run.result.findings) == 1
    answer = llm.calls[1].messages[-1]
    assert answer["tool_call_id"] == "c1"
    assert "não são um JSON válido" in answer["content"]


async def test_schema_errors_name_the_fields_without_echoing_long_values(
    repo_tools: RepoTools,
) -> None:
    long_message = "x" * 5000
    bad = {"summary": "s", "findings": [finding("b.py", 0, message=long_message)]}
    llm = ScriptedLLM([reply(call("submit_review", bad, "c1")), reply(submit_review())])
    await _review(llm, repo_tools)
    answer = llm.calls[1].messages[-1]["content"]
    assert "findings.0.line" in answer
    assert "findings.0.problem" in answer
    assert long_message not in answer
    assert len(answer) < 1000


async def test_up_to_two_invalid_answers_are_tolerated(repo_tools: RepoTools) -> None:
    bad = call("submit_review", {"summary": "s", "findings": "nope"})
    llm = ScriptedLLM([reply(bad), reply(bad), reply(submit_review([finding("b.py", 2)]))])
    run = await _review(llm, repo_tools)
    assert len(run.result.findings) == 1
    assert len(llm.calls) == 3


async def test_the_third_invalid_answer_is_a_failure(repo_tools: RepoTools) -> None:
    bad = call("submit_review", {"summary": "s", "findings": "nope"})
    llm = ScriptedLLM([reply(bad), reply(bad), reply(bad)])
    with pytest.raises(InvalidModelOutput, match="submit_review was invalid too many times"):
        await _review(llm, repo_tools)


async def test_extra_fields_from_the_model_are_ignored(repo_tools: RepoTools) -> None:
    payload = {
        "summary": "s",
        "confidence": 0.9,
        "findings": [finding("b.py", 2, confidence=1.0, tags=["x"])],
    }
    llm = ScriptedLLM([reply(call("submit_review", payload))])
    run = await _review(llm, repo_tools)
    assert [f.line for f in run.result.findings] == [2]


async def test_more_than_fifty_findings_are_rejected(repo_tools: RepoTools) -> None:
    many = {"summary": "s", "findings": [finding("b.py", n + 1) for n in range(51)]}
    llm = ScriptedLLM([reply(call("submit_review", many)), reply(submit_review())])
    await _review(llm, repo_tools)
    assert "findings" in llm.calls[1].messages[-1]["content"]
