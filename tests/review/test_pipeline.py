# Filename: test_pipeline.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import json
from pathlib import Path

import respx
from tests.llm_fakes import call, finding, reply, submit_review
from tests.pipeline_env import BOT, DIFF_B, DIFF_LOCK, build_env, thread_node

from farejador.review.pipeline import PipelineConfig
from farejador.state.store import Outcome


async def test_a_review_with_inline_comment_and_summary_is_posted(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(
        tmp_path,
        respx_mock,
        [
            reply(call("read_file", {"path": "a.py"}, "c1")),
            reply(
                submit_review(
                    [finding("b.py", 2, message="normalize(None) fails; guard it.")],
                    summary="One thing to fix.",
                )
            ),
        ],
    )
    trigger = env.trigger()
    await env.pipeline.run(trigger)

    payload = json.loads(env.review_route.calls.last.request.content)
    assert payload["commit_id"] == env.sha
    assert payload["event"] == "COMMENT"
    assert "Commit revisado: `" + env.sha[:7] + "` · Achados: 1 (média 1)" in payload["body"]
    assert "One thing to fix." in payload["body"]
    assert len(payload["comments"]) == 1
    comment = payload["comments"][0]
    assert (comment["path"], comment["line"], comment["side"]) == ("b.py", 2, "RIGHT")
    assert "normalize(None) fails" in comment["body"]

    # the model saw the numbered diff and the real checkout through its tool
    first_user = env.llm.calls[0].messages[1]["content"]
    assert '<file path="b.py">' in first_user
    assert "    2 | + value = normalize(None)" in first_user
    assert "def normalize(u):" in env.llm.calls[1].messages[-1]["content"]

    record = env.store.get_trigger(trigger.key)
    assert record is not None
    assert env.store.has_review_run("o/r", 1) is True


async def test_the_head_sha_comes_from_the_pull_request_not_the_trigger(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [reply(submit_review())])
    trigger = env.trigger().model_copy(update={"head_sha": "0" * 40})
    await env.pipeline.run(trigger)
    assert json.loads(env.review_route.calls.last.request.content)["commit_id"] == env.sha


async def test_findings_without_a_valid_anchor_go_to_the_summary(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(
        tmp_path,
        respx_mock,
        [
            reply(
                submit_review(
                    [
                        finding("b.py", 3, message="Context line, not added."),
                        finding("ghost.py", 1, message="No such file."),
                    ]
                )
            )
        ],
    )
    await env.pipeline.run(env.trigger())
    payload = json.loads(env.review_route.calls.last.request.content)
    assert payload["comments"] == []
    assert "### Achados sem âncora no diff" in payload["body"]
    assert "`b.py:3` — Context line, not added." in payload["body"]
    assert "`ghost.py:1` — No such file." in payload["body"]


async def test_lockfiles_are_skipped_and_listed_but_never_sent_to_the_model(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [reply(submit_review())], diff=DIFF_B + DIFF_LOCK)
    await env.pipeline.run(env.trigger())
    prompt = env.llm.calls[0].messages[1]["content"]
    assert "uv.lock" in prompt  # only in the skipped list
    assert "new = 2" not in prompt
    assert '<file path="uv.lock">' not in prompt
    body = json.loads(env.review_route.calls.last.request.content)["body"]
    assert "### Arquivos ignorados" in body
    assert "- `uv.lock` — arquivo de lock" in body


async def test_the_file_limit_keeps_the_first_files_and_reports_the_rest(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    second = DIFF_B.replace("b.py", "c.py")
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review())],
        diff=DIFF_B + second,
        config=PipelineConfig(max_files=1, bot_login=BOT),
    )
    await env.pipeline.run(env.trigger())
    prompt = env.llm.calls[0].messages[1]["content"]
    assert '<file path="b.py">' in prompt
    assert '<file path="c.py">' not in prompt
    body = json.loads(env.review_route.calls.last.request.content)["body"]
    assert "- `c.py` — limite de arquivos por revisão" in body


async def test_files_with_only_removed_lines_are_not_reviewed(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    removal = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1,2 +1,1 @@\n keep\n-gone\n"
    env = build_env(tmp_path, respx_mock, [], diff=removal)
    await env.pipeline.run(env.trigger())
    assert env.llm.calls == []
    assert (
        "- `b.py` — sem linhas adicionadas"
        in json.loads(env.review_route.calls.last.request.content)["body"]
    )


async def test_nothing_to_review_still_publishes_a_short_review_without_calling_the_model(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [], diff=DIFF_LOCK)
    trigger = env.trigger()
    await env.pipeline.run(trigger)
    assert env.llm.calls == []
    payload = json.loads(env.review_route.calls.last.request.content)
    assert payload["comments"] == []
    assert "Nenhum achado relevante." in payload["body"]
    assert "- `uv.lock` — arquivo de lock" in payload["body"]
    assert env.store.has_review_run("o/r", 1) is True


async def test_a_partial_run_is_recorded_and_noted_in_the_review(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    from farejador.agent.runner import Budget

    env = build_env(
        tmp_path,
        respx_mock,
        [reply(call("list_dir", {}, "c1")), reply(submit_review([finding("b.py", 2)]))],
        budget=Budget(max_steps=1),
    )
    trigger = env.trigger()
    await env.pipeline.run(trigger)
    body = json.loads(env.review_route.calls.last.request.content)["body"]
    assert "> Revisão interrompida antes do fim: limite de passos atingido." in body
    outcome = env.store._db().execute("SELECT outcome FROM review_run").fetchone()[0]
    assert outcome == Outcome.PARTIAL.value


async def test_threads_opened_by_the_bot_are_registered_for_later_commands(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review([finding("b.py", 2)]))],
        threads=[
            thread_node("T1"),
            thread_node("T2", author="alice"),
            thread_node("T3", resolved=True),
        ],
    )
    await env.pipeline.run(env.trigger())
    registered = env.store.list_threads("o/r", 1)
    assert [(t.thread_id, t.path, t.line) for t in registered] == [("T1", "b.py", 2)]
    assert registered[0].run_id is not None


async def test_threads_already_known_are_not_registered_twice(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(tmp_path, respx_mock, [reply(submit_review())], threads=[thread_node("T1")])
    env.store.add_thread("T1", run_id=None, repo="o/r", pr_number=1, path="old.py", line=9)
    await env.pipeline.run(env.trigger())
    (thread,) = env.store.list_threads("o/r", 1)
    assert (thread.path, thread.line, thread.run_id) == ("old.py", 9, None)


async def test_threads_are_not_registered_when_the_bot_login_is_unknown(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    env = build_env(
        tmp_path,
        respx_mock,
        [reply(submit_review())],
        threads=[thread_node("T1")],
        config=PipelineConfig(bot_login=None),
    )
    await env.pipeline.run(env.trigger())
    assert env.store.list_threads("o/r", 1) == []
    assert env.graphql_route.call_count == 0


async def test_a_thread_listing_failure_does_not_fail_the_review(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    import httpx

    env = build_env(tmp_path, respx_mock, [reply(submit_review())])
    env.graphql_route.mock(return_value=httpx.Response(403, json={"message": "forbidden"}))
    trigger = env.trigger()
    await env.pipeline.run(trigger)
    assert env.review_route.call_count == 1
    assert env.comment_route.call_count == 0
    assert env.store.has_review_run("o/r", 1) is True


async def test_the_posted_comment_has_the_three_part_structure_with_a_verified_diff(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    good = finding(
        "b.py",
        2,
        message="O valor None chega a normalize.",
        rationale="normalize chama strip e falha com AttributeError quando recebe None.",
        suggestion="Proteja a chamada contra None.",
        suggestion_diff='-value = normalize(None)\n+value = normalize(texto or "")',
    )
    env = build_env(tmp_path, respx_mock, [reply(submit_review([good]))])
    await env.pipeline.run(env.trigger())

    (comment,) = json.loads(env.review_route.calls.last.request.content)["comments"]
    body = comment["body"]
    assert body.startswith(
        "**média · complexidade**\n\n## Problema\n\nO valor None chega a normalize."
    )
    assert "<summary><strong>Racional</strong></summary>" in body
    assert "AttributeError" in body
    assert "<summary><strong>Sugestão</strong></summary>" in body
    expected_suggestion = (
        "Proteja a chamada contra None.\n\n```diff\n"
        "-value = normalize(None)\n"
        '+value = normalize(texto or "")\n```'
    )
    assert expected_suggestion in body


async def test_an_invented_diff_is_dropped_but_the_comment_and_explanation_stay(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    invented = finding(
        "b.py",
        2,
        suggestion="Proteja a chamada contra None.",
        suggestion_diff="-codigo_que_nao_existe()\n+value = normalize(texto)",
    )
    env = build_env(tmp_path, respx_mock, [reply(submit_review([invented]))])
    await env.pipeline.run(env.trigger())
    (comment,) = json.loads(env.review_route.calls.last.request.content)["comments"]
    assert "Proteja a chamada contra None." in comment["body"]
    assert "```diff" not in comment["body"]
    assert "codigo_que_nao_existe" not in comment["body"]
