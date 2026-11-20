# Filename: test_budgets.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import asyncio

from tests.llm_fakes import ScriptedLLM, call, finding, reply, submit_review

from farejador.agent.llm import ModelApiError
from farejador.agent.runner import WRAP_UP_MAX_TOKENS, AgentRunner, Budget
from farejador.tools import RepoTools

DIFF = '<file path="b.py">\n    2 | + x\n</file>'


async def _run(llm: ScriptedLLM, tools: RepoTools, budget: Budget, **kwargs: object):  # type: ignore[no-untyped-def]
    runner = AgentRunner(llm, "m", budget, **kwargs)  # type: ignore[arg-type]
    return await runner.review(pr_title="t", numbered_diff=DIFF, skipped=[], tools=tools)


async def test_step_limit_forces_a_final_answer_and_reports_it(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [
            reply(call("list_dir", {}, "c1")),
            reply(call("list_dir", {}, "c2")),
            reply(submit_review([finding("b.py", 2)], summary="Based on what I saw.")),
        ]
    )
    run = await _run(llm, repo_tools, Budget(max_steps=2))

    assert run.partial is True
    assert run.note == "Revisão interrompida antes do fim: limite de passos atingido."
    assert run.steps == 2
    assert [f.line for f in run.result.findings] == [2]

    wrap_up = llm.calls[2]
    assert wrap_up.tool_names == ["submit_review"]
    assert wrap_up.tool_choice == {"type": "function", "function": {"name": "submit_review"}}
    assert wrap_up.max_tokens == WRAP_UP_MAX_TOKENS
    assert "limite de passos atingido" in wrap_up.messages[-1]["content"]


async def test_extra_calls_in_a_reply_beyond_the_limit_are_not_executed(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM(
        [
            reply(
                call("list_dir", {}, "c1"), call("list_dir", {}, "c2"), call("list_dir", {}, "c3")
            ),
            reply(submit_review()),
        ]
    )
    run = await _run(llm, repo_tools, Budget(max_steps=2))
    skipped = next(m for m in llm.calls[1].messages if m.get("tool_call_id") == "c3")
    assert "orçamento de ferramentas esgotado" in skipped["content"]
    assert run.steps == 2
    assert run.partial is True


async def test_token_limit_ends_exploration(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [
            reply(call("list_dir", {}, "c1"), tokens=600),
            reply(submit_review([finding("b.py", 2)])),
        ]
    )
    run = await _run(llm, repo_tools, Budget(max_tokens=500))
    assert run.partial is True
    assert run.note == "Revisão interrompida antes do fim: limite de tokens atingido."
    assert run.tokens == 700
    assert len(llm.calls) == 2


async def test_time_limit_uses_the_clock_between_calls(repo_tools: RepoTools) -> None:
    now = [0.0]
    llm = ScriptedLLM(
        [reply(call("list_dir", {}, "c1")), reply(submit_review([finding("b.py", 2)]))],
        on_call=lambda number: now.__setitem__(0, now[0] + (100.0 if number == 1 else 0.0)),
    )
    run = await _run(llm, repo_tools, Budget(max_seconds=60), clock=lambda: now[0])
    assert run.partial is True
    assert run.note == "Revisão interrompida antes do fim: limite de tempo atingido."
    assert run.duration_s == 100.0


async def test_a_model_call_that_exceeds_the_remaining_time_triggers_the_wrap_up(
    repo_tools: RepoTools,
) -> None:
    class SlowThenFast(ScriptedLLM):
        async def complete(self, **kwargs):  # type: ignore[no-untyped-def]
            if not self.calls:
                self.calls.append(None)  # type: ignore[arg-type]
                await asyncio.sleep(5)
            return await super().complete(**kwargs)

    llm = SlowThenFast([reply(submit_review([finding("b.py", 2)]))])
    run = await _run(llm, repo_tools, Budget(max_seconds=0.05))
    assert run.partial is True
    assert run.note is not None
    assert "tempo" in run.note
    assert [f.line for f in run.result.findings] == [2]


async def test_a_failed_wrap_up_gives_an_empty_partial_result_without_raising(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM([reply(call("list_dir", {}, "c1")), ModelApiError("HTTP 500")])
    run = await _run(llm, repo_tools, Budget(max_steps=1))
    assert run.partial is True
    assert run.result.findings == []
    assert run.result.summary == ""


async def test_an_invalid_wrap_up_answer_gives_an_empty_partial_result(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM(
        [
            reply(call("list_dir", {}, "c1")),
            reply(call("submit_review", {"summary": "x", "findings": "nope"})),
        ]
    )
    run = await _run(llm, repo_tools, Budget(max_steps=1))
    assert run.partial is True
    assert run.result.findings == []


async def test_a_slow_wrap_up_times_out_into_an_empty_partial_result(repo_tools: RepoTools) -> None:
    class SlowWrapUp(ScriptedLLM):
        async def complete(self, **kwargs):  # type: ignore[no-untyped-def]
            response = await super().complete(**kwargs)
            if len(self.calls) == 2:
                await asyncio.sleep(5)
            return response

    llm = SlowWrapUp(
        [reply(call("list_dir", {}, "c1")), reply(submit_review([finding("b.py", 2)]))]
    )
    run = await _run(llm, repo_tools, Budget(max_steps=1), wrap_up_timeout_s=0.05)
    assert run.partial is True
    assert run.result.findings == []


async def test_within_budget_nothing_is_marked_partial(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM([reply(call("list_dir", {}, "c1")), reply(submit_review())])
    run = await _run(llm, repo_tools, Budget(max_steps=5, max_tokens=10_000, max_seconds=60))
    assert (run.partial, run.note, run.steps) == (False, None, 1)
