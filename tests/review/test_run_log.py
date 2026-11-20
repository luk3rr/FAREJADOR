# Filename: test_run_log.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import io
import json
import logging
from pathlib import Path

import pytest
import respx
from tests.llm_fakes import call, finding, reply, submit_review
from tests.pipeline_env import BOT, build_env

from farejador.agent.llm import ModelApiError
from farejador.log import configure_logging
from farejador.review.pipeline import PipelineConfig


def _records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


async def test_a_finished_review_emits_one_summary_record(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    env = build_env(
        tmp_path,
        respx_mock,
        [
            reply(call("list_dir", {}, "c1"), tokens=300),
            reply(submit_review([finding("b.py", 2)]), tokens=200),
        ],
        config=PipelineConfig(mode="webhook", bot_login=BOT),
    )
    await env.pipeline.run(env.trigger())

    (record,) = [r for r in _records(stream) if r["message"] == "review_run"]
    assert record["repo"] == "o/r"
    assert record["pr"] == 1
    assert record["sha"] == env.sha
    assert record["mode"] == "webhook"
    assert record["steps"] == 1
    assert record["tokens"] == 500
    assert record["findings"] == 1
    assert record["outcome"] == "done"
    assert isinstance(record["duration_s"], float)
    logging.getLogger().handlers.clear()


async def test_a_failed_review_logs_the_failure_outcome(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    env = build_env(tmp_path, respx_mock, [ModelApiError("boom")])
    with pytest.raises(ModelApiError):
        await env.pipeline.run(env.trigger())
    records = _records(stream)
    summary = [r for r in records if r["message"] == "review_run"]
    assert [r["outcome"] for r in summary] == ["failed_model"]
    assert any(r["message"] == "review failed" and r["error"] == "ModelApiError" for r in records)
    logging.getLogger().handlers.clear()
