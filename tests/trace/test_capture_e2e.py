# Filename: test_capture_e2e.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""A real review and a real command leave the right trace (FR-1 to FR-8, NFR-2, NFR-6)."""

import json
import logging
import sqlite3
from pathlib import Path

import pytest
import respx
from tests.command_env import build_cmd_env, thread_node
from tests.llm_fakes import call, finding, reply, submit_review
from tests.pipeline_env import build_env
from tests.trace.helpers import SENTINEL

from farejador.agent.llm import LLMResponse, ModelApiError
from farejador.agent.prompts import PROMPT_VERSION
from farejador.agent.runner import Budget
from farejador.dispatcher import TriggerSkipped
from farejador.trace.recorder import TraceRecorder
from farejador.trace.store import TraceStore, open_readonly

DUPLICATED_AND_ANCHORED = [
    finding("b.py", 2, message="Valor None chega a normalize."),
    finding("b.py", 2, message="Valor None chega a normalize."),  # a duplicate
    finding("b.py", 3, message="Linha de contexto, não adicionada."),
    finding("ghost.py", 1, message="Arquivo que não está no diff."),
]


class Traced:
    """A real recorder over a real file, flushed on demand."""

    def __init__(self, tmp_path: Path, **budgets: int) -> None:
        self.path = tmp_path / "trace.db"
        self.store = TraceStore(self.path).open()
        self.recorder = TraceRecorder(
            self.store,
            model="test/model",
            prompt_version=PROMPT_VERSION,
            app_version="9.9.9",
            budgets={"max_steps": 15, **budgets},
        )
        self.recorder.start()

    def read(self) -> sqlite3.Connection:
        self.recorder.stop()
        return open_readonly(self.path)


async def test_a_review_leaves_ordered_steps_tools_and_findings(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    env = build_env(
        tmp_path,
        respx_mock,
        [
            reply(call("read_file", {"path": "a.py"}, "c1"), content="vou ler", tokens=120),
            reply(submit_review([finding("b.py", 2, message="normalize(None) falha.")])),
        ],
        recorder=traced.recorder,
        repo_private=False,
    )
    await env.pipeline.run(env.trigger())
    conn = traced.read()

    run = conn.execute("SELECT * FROM trace_run").fetchone()
    assert (run["kind"], run["repo"], run["pr_number"], run["head_sha"]) == (
        "review",
        "o/r",
        1,
        env.sha,
    )
    assert (run["outcome"], run["repo_public"], run["steps"]) == ("complete", 1, 1)
    assert (run["model"], run["prompt_version"], run["app_version"]) == (
        "test/model",
        PROMPT_VERSION,
        "9.9.9",
    )
    assert json.loads(run["budgets_json"])["max_steps"] == 15
    assert run["duration_s"] > 0 and run["finished_at"] is not None

    steps = conn.execute("SELECT * FROM trace_step ORDER BY idx").fetchall()
    assert [s["idx"] for s in steps] == [0, 1]
    first_inputs = json.loads(steps[0]["input_messages_json"])
    assert [m["role"] for m in first_inputs] == ["system", "user"]
    assert '<file path="b.py">' in first_inputs[1]["content"]
    assert (steps[0]["response_content"], steps[0]["tokens"]) == ("vou ler", 120)
    assert json.loads(steps[0]["tool_calls_json"])[0]["name"] == "read_file"
    assert json.loads(steps[1]["input_messages_json"]) == []  # only tool results came in
    assert json.loads(steps[1]["tool_calls_json"])[0]["name"] == "submit_review"

    results = conn.execute("SELECT * FROM trace_tool_result").fetchall()
    assert [(r["name"], r["call_id"]) for r in results] == [("read_file", "c1")]
    assert "def normalize" in results[0]["content"]

    (found,) = conn.execute("SELECT * FROM trace_finding").fetchall()
    assert (found["path"], found["line"], found["disposition"], found["reason"]) == (
        "b.py",
        2,
        "inline",
        None,
    )


async def test_every_finding_keeps_its_destination_and_reason(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review(DUPLICATED_AND_ANCHORED))],
        recorder=traced.recorder,
        repo_private=False,
    )
    await env.pipeline.run(env.trigger())
    rows = (
        traced.read()
        .execute("SELECT path, line, disposition, reason FROM trace_finding ORDER BY id")
        .fetchall()
    )
    assert [tuple(r) for r in rows] == [
        ("b.py", 2, "inline", None),
        ("b.py", 2, "dropped", "duplicate"),
        ("b.py", 3, "summary", "line_not_added"),
        ("ghost.py", 1, "summary", "file_not_in_diff"),
    ]


async def test_an_invented_suggestion_diff_is_flagged_but_the_finding_stays_inline(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    invented = finding("b.py", 2, suggestion_diff="-codigo_que_nao_existe()\n+value = 1")
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review([invented]))],
        recorder=traced.recorder,
        repo_private=False,
    )
    await env.pipeline.run(env.trigger())
    row = traced.read().execute("SELECT disposition, diff_dropped FROM trace_finding").fetchone()
    assert (row["disposition"], row["diff_dropped"]) == ("inline", 1)


async def test_the_reasoning_of_the_provider_is_stored_and_masked(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    thinking = LLMResponse(
        content=None,
        tool_calls=[submit_review([])],
        total_tokens=50,
        reasoning=f"O diff parece ok. Tenho a chave {SENTINEL} à vista.",
    )
    env = build_env(tmp_path, respx_mock, [thinking], recorder=traced.recorder, repo_private=False)
    await env.pipeline.run(env.trigger())
    reasoning = traced.read().execute("SELECT reasoning FROM trace_step").fetchone()[0]
    assert reasoning.startswith("O diff parece ok.")
    assert SENTINEL not in reasoning


async def test_a_model_failure_is_recorded_as_failed_with_its_category(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    env = build_env(
        tmp_path,
        respx_mock,
        [ModelApiError("model API returned HTTP 429")],
        recorder=traced.recorder,
        repo_private=False,
    )
    with pytest.raises(ModelApiError):
        await env.pipeline.run(env.trigger())
    run = traced.read().execute("SELECT * FROM trace_run").fetchone()
    assert (run["outcome"], run["error_category"]) == ("failed", "model_api")
    assert "HTTP 429" in run["error_message"]


async def test_a_budget_stop_is_recorded_as_partial_with_the_note(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(call("list_dir", {}, "c1")), reply(submit_review([finding("b.py", 2)]))],
        budget=Budget(max_steps=1),
        recorder=traced.recorder,
        repo_private=False,
    )
    await env.pipeline.run(env.trigger())
    run = traced.read().execute("SELECT * FROM trace_run").fetchone()
    assert (run["outcome"], run["error_category"]) == ("partial", "budget")
    assert "limite de passos" in run["error_message"]


@pytest.mark.parametrize(
    ("private", "expected"),
    [(False, 1), (True, 0), (None, None)],
    ids=["public", "private", "unknown"],
)
async def test_the_visibility_mark_comes_from_the_pull_request(
    tmp_path: Path, respx_mock: respx.MockRouter, private: bool | None, expected: int | None
) -> None:
    traced = Traced(tmp_path)
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review())],
        recorder=traced.recorder,
        repo_private=private,
    )
    await env.pipeline.run(env.trigger())
    assert traced.read().execute("SELECT repo_public FROM trace_run").fetchone()[0] == expected


async def test_a_skipped_trigger_leaves_no_trace(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    env = build_env(
        tmp_path, respx_mock, [], draft=True, recorder=traced.recorder, repo_private=False
    )
    with pytest.raises(TriggerSkipped):
        await env.pipeline.run(env.trigger())
    assert traced.read().execute("SELECT COUNT(*) FROM trace_run").fetchone()[0] == 0


async def test_a_review_with_nothing_to_review_still_leaves_a_complete_empty_trace(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    lock_diff = (
        "diff --git a/uv.lock b/uv.lock\n--- a/uv.lock\n+++ b/uv.lock\n@@ -1 +1,2 @@\n a\n+b\n"
    )
    env = build_env(
        tmp_path, respx_mock, [], diff=lock_diff, recorder=traced.recorder, repo_private=False
    )
    await env.pipeline.run(env.trigger())
    conn = traced.read()
    run = conn.execute("SELECT * FROM trace_run").fetchone()
    assert (run["outcome"], run["steps"]) == ("complete", 0)
    assert conn.execute("SELECT COUNT(*) FROM trace_step").fetchone()[0] == 0


async def test_the_published_review_is_identical_with_and_without_the_trace(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    script = [reply(submit_review(DUPLICATED_AND_ANCHORED, summary="Resumo."))]
    plain = build_env(tmp_path / "plain", respx_mock, list(script), repo_private=False)
    await plain.pipeline.run(plain.trigger())
    expected = plain.review_route.calls.last.request.content

    respx_mock.reset()
    traced = Traced(tmp_path)
    with_trace = build_env(
        tmp_path / "traced",
        respx_mock,
        list(script),
        recorder=traced.recorder,
        repo_private=False,
    )
    await with_trace.pipeline.run(with_trace.trigger())
    traced.recorder.stop()
    # The two repositories are built apart, so their commits differ (the hash depends on the
    # time): the body carries the full sha in ``commit_id`` and the short one in its heading.
    normalized = expected.replace(plain.sha.encode(), with_trace.sha.encode()).replace(
        plain.sha[:7].encode(), with_trace.sha[:7].encode()
    )
    assert with_trace.review_route.calls.last.request.content == normalized


async def test_a_broken_trace_never_changes_the_review(
    tmp_path: Path, respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    broken = TraceStore(tmp_path / "trace.db")  # never opened: every write fails
    recorder = TraceRecorder(broken, model="m", prompt_version="p", app_version="v", budgets={})
    recorder.start()
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review([finding("b.py", 2)]))],
        recorder=recorder,
        repo_private=False,
    )
    with caplog.at_level(logging.ERROR):
        await env.pipeline.run(env.trigger())
        recorder.stop()
    assert env.review_route.call_count == 1
    assert env.store.has_review_run("o/r", 1) is True
    assert any("trace write failed" in r.getMessage() for r in caplog.records)


async def test_a_command_that_reevaluates_threads_leaves_a_command_trace(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    from tests.llm_fakes import call as tool_call

    traced = Traced(tmp_path)
    verdicts = tool_call(
        "submit_verdicts", {"verdicts": [{"thread_id": "T1", "fixed": True, "confidence": 0.9}]}
    )
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [reply(verdicts), reply(submit_review())],  # all fixed, so a new review follows
        threads=[thread_node("T1")],
        recorder=traced.recorder,
        repo_private=False,
    )
    cmd.env.store.add_thread("T1", run_id=None, repo="o/r", pr_number=1, path="b.py", line=2)
    await cmd.handler.run(cmd.trigger())
    conn = traced.read()
    kinds = [r[0] for r in conn.execute("SELECT kind FROM trace_run ORDER BY id")]
    assert kinds == ["command", "review"]  # the reevaluation, then the review it triggered
    run = conn.execute("SELECT * FROM trace_run WHERE kind = 'command'").fetchone()
    assert (run["outcome"], run["repo_public"], run["steps"]) == ("complete", 1, 0)
    command_steps = conn.execute(
        "SELECT tool_calls_json FROM trace_step WHERE run_id = ?", (run["id"],)
    ).fetchall()
    assert len(command_steps) == 1
    assert json.loads(command_steps[0][0])[0]["name"] == "submit_verdicts"


async def test_a_command_failure_is_recorded_as_failed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    traced = Traced(tmp_path)
    cmd = build_cmd_env(
        tmp_path,
        respx_mock,
        [ModelApiError("model API call failed (ConnectError)")],
        threads=[thread_node("T1")],
        recorder=traced.recorder,
        repo_private=False,
    )
    cmd.env.store.add_thread("T1", run_id=None, repo="o/r", pr_number=1, path="b.py", line=2)
    with pytest.raises(ModelApiError):
        await cmd.handler.run(cmd.trigger())
    run = traced.read().execute("SELECT * FROM trace_run").fetchone()
    assert (run["kind"], run["outcome"], run["error_category"]) == (
        "command",
        "failed",
        "model_api",
    )
