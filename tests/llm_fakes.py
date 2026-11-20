# Filename: llm_fakes.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""A scripted model for agent tests: no network, fully deterministic (M-003)."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from farejador.agent.llm import LLMResponse, ToolCall


def call(name: str, arguments: dict[str, Any] | str, call_id: str | None = None) -> ToolCall:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ToolCall(call_id or f"call-{name}", name, raw)


def reply(*calls: ToolCall, content: str | None = None, tokens: int = 100) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=list(calls), total_tokens=tokens)


def finding(file: str = "a.py", line: int = 2, **overrides: Any) -> dict[str, Any]:
    """A finding in the three-part structure; ``message`` is a shortcut for ``problem``."""
    problem = overrides.pop("message", "Extraia este ramo para uma função.")
    base: dict[str, Any] = {
        "file": file,
        "line": line,
        "severity": "medium",
        "category": "complexity",
        "problem": problem,
        "rationale": "Ramos longos dificultam os testes e a leitura.",
        "suggestion": "Mova o ramo para uma função com nome claro.",
    }
    return base | overrides


def submit_review(findings: Sequence[dict[str, Any]] = (), summary: str = "ok") -> ToolCall:
    return call("submit_review", {"summary": summary, "findings": list(findings)})


@dataclass
class Recorded:
    messages: list[dict[str, Any]]
    tool_names: list[str]
    tool_choice: str | dict[str, Any]
    max_tokens: int | None


@dataclass
class ScriptedLLM:
    """Returns the scripted responses in order and records every request."""

    script: list[LLMResponse | Exception]
    on_call: Callable[[int], None] | None = None
    calls: list[Recorded] = field(default_factory=list)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any],
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        self.calls.append(
            Recorded(
                messages=[dict(message) for message in messages],
                tool_names=[tool["function"]["name"] for tool in tools],
                tool_choice=tool_choice,
                max_tokens=max_tokens,
            )
        )
        if self.on_call is not None:
            self.on_call(len(self.calls))
        if not self.script:
            raise AssertionError("the scripted model has no more responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
