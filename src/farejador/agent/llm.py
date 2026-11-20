# Filename: llm.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Model access behind a small interface; the adapter talks to OpenRouter (ADR-3)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx2
import openai
from openai import AsyncOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class ModelApiError(Exception):
    """The model API failed after the allowed retries."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    total_tokens: int = 0


class LLMClient(Protocol):
    """What the agent loop needs from a chat model with tool calling."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any],
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse: ...


class OpenRouterClient:
    """``LLMClient`` over the OpenAI-compatible OpenRouter API using the ``openai`` SDK."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        http_client: httpx2.AsyncClient | None = None,
        max_retries: int = 2,
        timeout_s: float = 120.0,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=max_retries,
            timeout=timeout_s,
            default_headers={"X-Title": "Farejador"},
        )

    async def aclose(self) -> None:
        await self._client.close()

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
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": list(tools),
            "tool_choice": tool_choice,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            raise ModelApiError(f"model API returned HTTP {exc.status_code}") from None
        except openai.APIError as exc:
            raise ModelApiError(f"model API call failed ({type(exc).__name__})") from None

        if not response.choices:
            raise ModelApiError("model API returned no choices")
        message = response.choices[0].message
        calls = [
            ToolCall(call.id, call.function.name, call.function.arguments or "{}")
            for call in (message.tool_calls or [])
            if call.type == "function"
        ]
        usage = response.usage.total_tokens if response.usage else None
        if usage is None:
            usage = _estimate_tokens(messages, message.content, calls)
        return LLMResponse(content=message.content, tool_calls=calls, total_tokens=usage)


def _estimate_tokens(
    messages: list[dict[str, Any]], content: str | None, calls: list[ToolCall]
) -> int:
    """Rough fallback of about 4 characters per token when the API reports no usage."""
    characters = len(json.dumps(messages, default=str)) + len(content or "")
    characters += sum(len(call.arguments) for call in calls)
    return characters // 4
