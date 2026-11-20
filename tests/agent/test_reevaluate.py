# Filename: test_reevaluate.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import pytest
from tests.llm_fakes import ScriptedLLM, call, reply

from farejador.agent.runner import AgentRunner, Budget, InvalidModelOutput
from farejador.agent.schemas import OpenThread
from farejador.tools import RepoTools

THREADS = [
    OpenThread(thread_id="T1", path="a.py", line=2, body="Extract this branch."),
    OpenThread(thread_id="T2", path="b.py", line=1, body="Rename this variable."),
]


def _verdicts(*items: tuple[str, bool]) -> object:
    return call(
        "submit_verdicts",
        {"verdicts": [{"thread_id": t, "fixed": f, "note": "checked"} for t, f in items]},
    )


async def _run(llm: ScriptedLLM, tools: RepoTools, budget: Budget | None = None):  # type: ignore[no-untyped-def]
    return await AgentRunner(llm, "m", budget).reevaluate(threads=THREADS, tools=tools)


async def test_each_thread_gets_the_models_verdict(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [
            reply(call("read_file", {"path": "a.py"}, "c1")),
            reply(_verdicts(("T1", True), ("T2", False))),  # type: ignore[arg-type]
        ]
    )
    run = await _run(llm, repo_tools)
    assert {k: (v.fixed, v.note) for k, v in run.verdicts.items()} == {
        "T1": (True, "checked"),
        "T2": (False, "checked"),
    }
    assert (run.steps, run.partial) == (1, False)
    first = llm.calls[0]
    assert first.tool_names == ["read_file", "grep", "list_dir", "submit_verdicts"]
    assert '<thread id="T1" location="a.py:2">' in first.messages[1]["content"]
    assert "submit_verdicts" in first.messages[0]["content"]


async def test_missing_verdicts_are_requested_again(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [
            reply(_verdicts(("T1", True))),  # type: ignore[arg-type]
            reply(_verdicts(("T1", True), ("T2", True))),  # type: ignore[arg-type]
        ]
    )
    run = await _run(llm, repo_tools)
    assert "faltam veredictos para os thread ids: T2" in llm.calls[1].messages[-1]["content"]
    assert run.verdicts["T2"].fixed is True


async def test_unknown_thread_ids_are_ignored(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM([reply(_verdicts(("T1", True), ("T2", False), ("GHOST", True)))])  # type: ignore[arg-type]
    run = await _run(llm, repo_tools)
    assert set(run.verdicts) == {"T1", "T2"}


async def test_invalid_verdicts_three_times_is_a_failure(repo_tools: RepoTools) -> None:
    bad = call("submit_verdicts", {"verdicts": [{"thread_id": "T1", "fixed": "maybe"}]})
    llm = ScriptedLLM([reply(bad), reply(bad), reply(bad)])
    with pytest.raises(InvalidModelOutput):
        await _run(llm, repo_tools)


async def test_a_partial_run_never_resolves_threads_without_a_verdict(
    repo_tools: RepoTools,
) -> None:
    llm = ScriptedLLM([reply(call("list_dir", {}, "c1")), reply(_verdicts(("T1", True)))])  # type: ignore[arg-type]
    run = await _run(llm, repo_tools, Budget(max_steps=1))
    assert run.partial is True
    assert run.note == "Revisão interrompida antes do fim: limite de passos atingido."
    # the wrap-up answer was incomplete (T2 missing), so nothing is trusted
    assert [(t, v.fixed) for t, v in sorted(run.verdicts.items())] == [("T1", False), ("T2", False)]


async def test_a_complete_wrap_up_answer_is_used(repo_tools: RepoTools) -> None:
    llm = ScriptedLLM(
        [reply(call("list_dir", {}, "c1")), reply(_verdicts(("T1", True), ("T2", False)))]  # type: ignore[arg-type]
    )
    run = await _run(llm, repo_tools, Budget(max_steps=1))
    assert run.partial is True
    assert run.verdicts["T1"].fixed is True
    assert run.verdicts["T2"].fixed is False
