# Filename: command_env.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Builds a CommandHandler on top of the first-review test environment."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import respx
from tests.factories import make_command
from tests.pipeline_env import API, REPO, Env, build_env, thread_node

from farejador.commands import CommandHandler
from farejador.models import Trigger

PERMISSION_URL = f"{API}/repos/{REPO}/collaborators/bob/permission"


@dataclass
class CmdEnv:
    env: Env
    handler: CommandHandler
    threads: list[dict[str, Any]]
    permission_route: respx.Route
    resolved_ids: list[str] = field(default_factory=list)
    failing_ids: set[str] = field(default_factory=set)

    def trigger(self, comment_id: int = 10, sender: str = "bob") -> Trigger:
        trigger = make_command(comment_id, sender=sender, pr=1)
        assert self.env.store.try_claim(trigger)
        return trigger


def build_cmd_env(
    tmp_path: Path,
    router: respx.MockRouter,
    script: Sequence[Any],
    *,
    role: str = "write",
    threads: Sequence[dict[str, Any]] = (),
    **kwargs: Any,
) -> CmdEnv:
    env = build_env(tmp_path, router, script, **kwargs)
    state = [dict(node) for node in threads]
    permission_route = router.get(PERMISSION_URL).mock(
        return_value=httpx.Response(200, json={"role_name": role, "permission": "write"})
    )
    cmd = CmdEnv(env=env, handler=None, threads=state, permission_route=permission_route)  # type: ignore[arg-type]

    def graphql(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "resolveReviewThread" in body["query"]:
            thread_id = body["variables"]["threadId"]
            if thread_id in cmd.failing_ids:
                return httpx.Response(200, json={"errors": [{"message": "cannot resolve"}]})
            cmd.resolved_ids.append(thread_id)
            for node in state:
                if node["id"] == thread_id:
                    node["isResolved"] = True
            return httpx.Response(
                200,
                json={"data": {"resolveReviewThread": {"thread": {"id": thread_id}}}},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": state,
                            }
                        }
                    }
                }
            },
        )

    env.graphql_route.mock(side_effect=graphql)
    cmd.handler = CommandHandler(
        client=env.client,
        token_for=env.token_for,
        store=env.store,
        runner=env.runner,
        publisher=env.publisher,
        open_workspace=env.open_workspace,
        review=env.pipeline,
        config=env.config,
        recorder=kwargs.get("recorder"),
    )
    return cmd


__all__ = ["CmdEnv", "build_cmd_env", "thread_node"]
