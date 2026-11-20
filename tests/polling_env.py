# Filename: polling_env.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Fake GitHub and recording dispatcher for the polling source tests."""

from dataclasses import dataclass, field
from typing import Any

import httpx
import respx
from tests.factories import FakeAuth, SleepRecorder

from farejador.dispatcher import SubmitResult
from farejador.github.client import GitHubClient
from farejador.models import Trigger
from farejador.sources.polling import PollingSource
from farejador.state.store import StateStore

API = "https://api.github.com"
START = "2026-11-20T10:00:00Z"


def pr(
    number: int, *, draft: bool = False, sha: str | None = None, author: str = "alice"
) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR {number}",
        "draft": draft,
        "state": "open",
        "head": {"sha": sha or f"sha{number}"},
        "user": {"login": author},
        "html_url": f"https://github.com/o/r/pull/{number}",
    }


def comment(identifier: int, body: str, created: str, *, author: str = "alice") -> dict[str, Any]:
    return {
        "id": identifier,
        "body": body,
        "user": {"login": author},
        "created_at": created,
        "updated_at": created,
    }


@dataclass
class RecordingSubmit:
    """Behaves like the dispatcher for idempotency: claims in the store, records triggers."""

    store: StateStore
    triggers: list[Trigger] = field(default_factory=list)

    async def __call__(self, trigger: Trigger) -> SubmitResult:
        if not self.store.try_claim(trigger):
            return SubmitResult.DUPLICATE
        self.triggers.append(trigger)
        return SubmitResult.ENQUEUED

    @property
    def keys(self) -> list[str]:
        return [trigger.key for trigger in self.triggers]


@dataclass
class World:
    client: GitHubClient
    store: StateStore
    submit: RecordingSubmit
    source: PollingSource
    sleep: SleepRecorder
    router: respx.MockRouter
    repos_route: respx.Route
    prs_route: respx.Route
    comments_routes: dict[int, respx.Route]


def build_world(
    router: respx.MockRouter,
    store: StateStore,
    *,
    prs: list[dict[str, Any]],
    comments: dict[int, list[dict[str, Any]]] | None = None,
    repos: list[str] | None = None,
    bot_login: str | None = "farejador[bot]",
    interval_s: float = 60.0,
    submit: RecordingSubmit | None = None,
    started_at: str = START,
) -> World:
    router.get(f"{API}/app/installations").mock(
        return_value=httpx.Response(200, json=[{"id": 7, "account": {"login": "o"}}])
    )
    repos_route = router.get(f"{API}/installation/repositories").mock(
        return_value=httpx.Response(
            200, json={"repositories": [{"full_name": name} for name in (repos or ["o/r"])]}
        )
    )
    prs_route = router.get(f"{API}/repos/o/r/pulls").mock(
        return_value=httpx.Response(200, json=prs, headers={"ETag": '"prs-1"'})
    )
    comments_routes = {}
    for number in {item["number"] for item in prs}:
        comments_routes[number] = router.get(f"{API}/repos/o/r/issues/{number}/comments").mock(
            return_value=httpx.Response(
                200, json=(comments or {}).get(number, []), headers={"ETag": f'"c-{number}"'}
            )
        )
    client = GitHubClient(FakeAuth(), sleep=SleepRecorder())
    recorder = submit or RecordingSubmit(store)
    sleep = SleepRecorder()
    source = PollingSource(
        client=client,
        store=store,
        submit=recorder,
        bot_login=bot_login,
        interval_s=interval_s,
        sleep=sleep,
        now=lambda: started_at,
    )
    return World(
        client, store, recorder, source, sleep, router, repos_route, prs_route, comments_routes
    )
