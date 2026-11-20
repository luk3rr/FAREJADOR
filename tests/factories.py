# Filename: factories.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Small builders shared by the tests."""

from farejador.models import Trigger, TriggerSource


def make_first(pr: int = 1, *, sender: str = "alice", repo: str = "o/r") -> Trigger:
    return Trigger.first_review(
        repo=repo,
        installation_id=99,
        pr_number=pr,
        sender_login=sender,
        source=TriggerSource.POLLING,
    )


def make_command(comment_id: int = 10, *, sender: str = "alice", pr: int = 1) -> Trigger:
    return Trigger.command(
        repo="o/r",
        installation_id=99,
        pr_number=pr,
        comment_id=comment_id,
        sender_login=sender,
        source=TriggerSource.WEBHOOK,
    )


class FakeAuth:
    """An in-memory GitHubAuth that records invalidations and changes token after each one."""

    def __init__(self) -> None:
        self.version = 1
        self.invalidated: list[int] = []

    def app_jwt(self) -> str:
        return "app-jwt"

    async def token_for(self, installation_id: int) -> str:
        return f"token-{installation_id}-v{self.version}"

    def invalidate(self, installation_id: int) -> None:
        self.invalidated.append(installation_id)
        self.version += 1


class SleepRecorder:
    """Replaces asyncio.sleep so retry tests are instant and observable."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
