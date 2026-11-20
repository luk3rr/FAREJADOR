# Filename: test_first_review_e2e.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""End to end: dispatcher, pipeline, agent, workspace, publisher and state, with sentinel
secrets that must never reach the model, the comments or the logs (NFR-3, FR-19)."""

import io
import json
import logging
from pathlib import Path

import respx
from tests.factories import make_first
from tests.llm_fakes import call, finding, reply, submit_review
from tests.pipeline_env import BOT, REPO, build_env, thread_node

from farejador.agent.llm import ModelApiError
from farejador.dispatcher import Dispatcher
from farejador.log import configure_logging
from farejador.models import TriggerKind
from farejador.review.pipeline import PipelineConfig
from farejador.state.store import TriggerStatus

OPENROUTER_KEY = "sk-or-v1-SENTINELOPENROUTERKEY000"
WEBHOOK_SECRET = "whsec-sentinel-webhook-9876"
CODE_TOKEN = "ghp_" + "Z" * 36
CODE_PASSWORD = "hunter2-sentinel-pass"
ALL_SECRETS = [OPENROUTER_KEY, WEBHOOK_SECRET, CODE_TOKEN, CODE_PASSWORD]

FILES = {
    "a.py": f"def normalize(u):\n    return u\n\nPASSWORD = '{CODE_PASSWORD}'\n",
    "b.py": f"from a import normalize\nTOKEN = '{CODE_TOKEN}'\nprint(normalize(' x '))\n",
    ".env": f"API_KEY={OPENROUTER_KEY}\n",
}
DIFF = f"""\
diff --git a/b.py b/b.py
index 111..222 100644
--- a/b.py
+++ b/b.py
@@ -1,2 +1,3 @@
 from a import normalize
+TOKEN = '{CODE_TOKEN}'
 print(normalize(' x '))
diff --git a/.env b/.env
new file mode 100644
--- /dev/null
+++ b/.env
@@ -0,0 +1 @@
+API_KEY={OPENROUTER_KEY}
"""


def _everything_the_model_saw(env: object) -> str:
    return json.dumps([call_.messages for call_ in env.llm.calls], ensure_ascii=False)  # type: ignore[attr-defined]


async def test_secrets_never_reach_the_model_the_comments_or_the_logs(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", secrets=[OPENROUTER_KEY, WEBHOOK_SECRET], stream=stream)
    echoed = f"Do not hardcode TOKEN = '{CODE_TOKEN}' and password='{CODE_PASSWORD}'."
    env = build_env(
        tmp_path,
        respx_mock,
        [
            reply(call("read_file", {"path": "a.py"}, "c1")),
            reply(call("read_file", {"path": ".env"}, "c2")),
            reply(call("grep", {"pattern": "TOKEN"}, "c3")),
            reply(
                submit_review(
                    [finding("b.py", 2, message=echoed, suggestion=f"use env: {CODE_TOKEN}")],
                    summary=f"Found {CODE_TOKEN} in the diff.",
                )
            ),
        ],
        diff=DIFF,
        files=FILES,
        threads=[thread_node("T1")],
    )
    dispatcher = Dispatcher(env.store, {TriggerKind.FIRST_REVIEW: env.pipeline.run}, workers=1)
    await dispatcher.start()
    trigger = make_first(1, repo=REPO)
    await dispatcher.submit(trigger)
    await dispatcher.stop()

    record = env.store.get_trigger(trigger.key)
    assert record is not None
    assert record.status is TriggerStatus.DONE
    assert env.review_route.call_count == 1

    # 1. nothing sensitive reached the model, neither in the prompt nor in tool results
    model_view = _everything_the_model_saw(env)
    for secret in ALL_SECRETS:
        assert secret not in model_view
    assert "[MASKED]" in model_view
    assert "indisponível" in model_view  # the .env file could not be read

    # 2. what the model echoed back was masked before publishing
    posted = env.review_route.calls.last.request.content.decode()
    for secret in ALL_SECRETS:
        assert secret not in posted

    # 3. the logs contain no secret and the structured summary is there
    logs = stream.getvalue()
    for secret in ALL_SECRETS:
        assert secret not in logs
    assert '"message": "review_run"' in logs
    logging.getLogger().handlers.clear()

    # the review itself was still useful: an inline comment on the added line
    comments = json.loads(posted)["comments"]
    assert [(c["path"], c["line"]) for c in comments] == [("b.py", 2)]


async def test_a_failure_whose_error_mentions_a_secret_leaks_nothing(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", secrets=[OPENROUTER_KEY, WEBHOOK_SECRET], stream=stream)
    env = build_env(
        tmp_path,
        respx_mock,
        [ModelApiError(f"upstream rejected key {OPENROUTER_KEY}")],
        diff=DIFF,
        files=FILES,
        config=PipelineConfig(mode="webhook", bot_login=BOT),
    )
    dispatcher = Dispatcher(env.store, {TriggerKind.FIRST_REVIEW: env.pipeline.run}, workers=1)
    await dispatcher.start()
    trigger = make_first(1, repo=REPO)
    await dispatcher.submit(trigger)
    await dispatcher.stop()

    record = env.store.get_trigger(trigger.key)
    assert record is not None
    assert (record.status, record.error) == (TriggerStatus.FAILED, "ModelApiError")
    notice = env.comment_route.calls.last.request.content.decode()
    assert OPENROUTER_KEY not in notice
    assert OPENROUTER_KEY not in stream.getvalue()
    assert OPENROUTER_KEY not in json.dumps(record.error)
    logging.getLogger().handlers.clear()
