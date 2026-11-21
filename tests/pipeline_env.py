# Filename: pipeline_env.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""A complete fake environment for the first-review pipeline: GitHub over respx, a real local
git checkout for the workspace, a scripted model and a real state store (M-003)."""

from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import respx
from tests.factories import FakeAuth, SleepRecorder
from tests.gitrepo import make_repo
from tests.llm_fakes import ScriptedLLM

from farejador.agent.runner import AgentRunner, Budget
from farejador.github.client import GitHubClient
from farejador.models import Trigger
from farejador.review.pipeline import FirstReview, PipelineConfig
from farejador.review.publisher import Publisher
from farejador.state.store import StateStore
from farejador.trace.recorder import Recorder
from farejador.workspace import Workspace

API = "https://api.github.com"
REPO = "o/r"
BOT = "farejador[bot]"

B_PY = "from a import normalize\nvalue = normalize(None)\nprint(normalize(' x '))\n"
DIFF_B = """\
diff --git a/b.py b/b.py
index 111..222 100644
--- a/b.py
+++ b/b.py
@@ -1,2 +1,3 @@
 from a import normalize
+value = normalize(None)
 print(normalize(' x '))
"""
DIFF_LOCK = """\
diff --git a/uv.lock b/uv.lock
index 111..222 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1 +1,2 @@
 version = 1
+new = 2
"""


def pr_json(
    sha: str,
    *,
    draft: bool = False,
    state: str = "open",
    title: str = "Add b",
    repo_private: bool | None = None,
) -> dict:  # type: ignore[type-arg]
    base = {} if repo_private is None else {"base": {"repo": {"private": repo_private}}}
    return {
        **base,
        "number": 1,
        "title": title,
        "draft": draft,
        "state": state,
        "head": {"sha": sha},
        "user": {"login": "alice"},
        "html_url": f"https://github.com/{REPO}/pull/1",
    }


def thread_node(thread_id: str, *, author: str = BOT, resolved: bool = False) -> dict:  # type: ignore[type-arg]
    return {
        "id": thread_id,
        "isResolved": resolved,
        "path": "b.py",
        "line": 2,
        "comments": {"nodes": [{"body": "smell", "author": {"login": author}}]},
    }


@dataclass
class Env:
    store: StateStore
    client: GitHubClient
    publisher: Publisher
    llm: ScriptedLLM
    pipeline: FirstReview
    sha: str
    remote: Path
    router: respx.MockRouter
    pr_route: respx.Route
    diff_route: respx.Route
    review_route: respx.Route
    comment_route: respx.Route
    reaction_route: respx.Route
    reaction_delete_route: respx.Route
    graphql_route: respx.Route
    runner: AgentRunner
    open_workspace: Callable[[str, str, str], AbstractAsyncContextManager[Workspace]]
    token_for: Callable[[int], Awaitable[str]]
    config: PipelineConfig

    def trigger(self) -> Trigger:
        from tests.factories import make_first

        trigger = make_first(1, repo=REPO)
        assert self.store.try_claim(trigger)
        return trigger


def build_env(
    tmp_path: Path,
    router: respx.MockRouter,
    script: Sequence[Any],
    *,
    draft: bool = False,
    state: str = "open",
    diff: str = DIFF_B,
    title: str = "Add b",
    threads: Sequence[dict] = (),  # type: ignore[type-arg]
    config: PipelineConfig | None = None,
    budget: Budget | None = None,
    files: dict[str, str] | None = None,
    recorder: Recorder | None = None,
    repo_private: bool | None = None,
) -> Env:
    remote = tmp_path / "remote"
    sha = make_repo(remote, files or {"a.py": "def normalize(u):\n    return u\n", "b.py": B_PY})
    store = StateStore(tmp_path / "state.db").open()

    pr_route = router.get(
        f"{API}/repos/{REPO}/pulls/1", headers={"Accept": "application/vnd.github+json"}
    ).mock(
        return_value=httpx.Response(
            200,
            json=pr_json(sha, draft=draft, state=state, title=title, repo_private=repo_private),
        )
    )
    diff_route = router.get(
        f"{API}/repos/{REPO}/pulls/1", headers={"Accept": "application/vnd.github.diff"}
    ).mock(return_value=httpx.Response(200, text=diff))
    review_route = router.post(f"{API}/repos/{REPO}/pulls/1/reviews").mock(
        return_value=httpx.Response(200, json={"id": 77})
    )
    comment_route = router.post(f"{API}/repos/{REPO}/issues/1/comments").mock(
        return_value=httpx.Response(201, json={"id": 88})
    )
    reaction_route = router.post(f"{API}/repos/{REPO}/issues/1/reactions").mock(
        return_value=httpx.Response(201, json={"id": 5})
    )
    reaction_delete_route = router.delete(f"{API}/repos/{REPO}/issues/1/reactions/5").mock(
        return_value=httpx.Response(204)
    )
    graphql_route = router.post(f"{API}/graphql").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": list(threads),
                            }
                        }
                    }
                }
            },
        )
    )

    client = GitHubClient(FakeAuth(), sleep=SleepRecorder())
    publisher = Publisher(client)
    llm = ScriptedLLM(list(script))
    runner = AgentRunner(llm, "test/model", budget or Budget())

    async def token_for(_installation_id: int) -> str:
        return "ghs_faketoken0000000000000000000"

    def open_workspace(repo: str, head: str, token: str) -> AbstractAsyncContextManager[Workspace]:
        return Workspace.open(repo, head, token, remote_url=str(remote))

    settings = config or PipelineConfig(mode="polling", bot_login=BOT)
    pipeline = FirstReview(
        client=client,
        token_for=token_for,
        store=store,
        runner=runner,
        publisher=publisher,
        open_workspace=open_workspace,
        config=settings,
        recorder=recorder,
    )
    return Env(
        store=store,
        client=client,
        publisher=publisher,
        llm=llm,
        pipeline=pipeline,
        sha=sha,
        remote=remote,
        router=router,
        pr_route=pr_route,
        diff_route=diff_route,
        review_route=review_route,
        comment_route=comment_route,
        reaction_route=reaction_route,
        reaction_delete_route=reaction_delete_route,
        graphql_route=graphql_route,
        runner=runner,
        open_workspace=open_workspace,
        token_for=token_for,
        config=settings,
    )
