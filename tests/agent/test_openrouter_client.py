# Filename: test_openrouter_client.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The OpenAI SDK installed here talks through ``httpx2``, so requests are faked with its
``MockTransport`` instead of ``respx`` (which only patches ``httpx``)."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from farejador.agent.llm import LLMResponse, ModelApiError, OpenRouterClient

API_KEY = "sk-or-v1-supersecretkey0000"
TOOLS = [{"type": "function", "function": {"name": "list_dir", "parameters": {"type": "object"}}}]
Handler = Callable[[httpx2.Request], httpx2.Response]


def _completion(message: dict[str, object], usage: object = None) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 1,
        "model": "test/model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _client(handler: Handler) -> tuple[OpenRouterClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    return OpenRouterClient(API_KEY, http_client=http, max_retries=0), seen


async def _complete(client: OpenRouterClient, **kwargs: Any) -> LLMResponse:
    params: dict[str, Any] = {
        "model": "test/model",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": TOOLS,
        "tool_choice": "auto",
    }
    return await client.complete(**(params | kwargs))


def _json(body: object, status: int = 200) -> Handler:
    return lambda _request: httpx2.Response(status, json=body)


async def test_request_shape_and_tool_call_parsing() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "list_dir", "arguments": '{"path": "src"}'},
            }
        ],
    }
    usage = {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
    client, seen = _client(_json(_completion(message, usage)))
    response = await _complete(client, max_tokens=123)

    request = seen[-1]
    sent = json.loads(request.content)
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.headers["X-Title"] == "Farejador"
    assert sent["model"] == "test/model"
    assert sent["tools"] == TOOLS
    assert sent["tool_choice"] == "auto"
    assert sent["max_tokens"] == 123
    assert sent["temperature"] == 0.1

    assert response.content is None
    assert response.total_tokens == 50
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("call_1", "list_dir", '{"path": "src"}')
    ]


async def test_forced_tool_choice_is_sent_as_given_and_max_tokens_is_optional() -> None:
    client, seen = _client(_json(_completion({"role": "assistant", "content": "ok"})))
    forced = {"type": "function", "function": {"name": "list_dir"}}
    await _complete(client, tool_choice=forced)
    sent = json.loads(seen[-1].content)
    assert sent["tool_choice"] == forced
    assert "max_tokens" not in sent


async def test_text_reply_without_usage_gets_an_estimate() -> None:
    client, _ = _client(_json(_completion({"role": "assistant", "content": "x" * 400})))
    response = await _complete(client)
    assert response.content == "x" * 400
    assert response.tool_calls == []
    assert response.total_tokens >= 100


async def test_tool_call_without_arguments_defaults_to_an_empty_object() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "list_dir", "arguments": ""}}
        ],
    }
    client, _ = _client(_json(_completion(message)))
    response = await _complete(client)
    assert response.tool_calls[0].arguments == "{}"


async def test_http_errors_become_model_api_errors_without_leaking_details() -> None:
    client, _ = _client(_json({"error": {"message": f"bad key {API_KEY}"}}, status=401))
    with pytest.raises(ModelApiError) as info:
        await _complete(client)
    assert str(info.value) == "model API returned HTTP 401"
    assert API_KEY not in str(info.value)


async def test_server_errors_become_model_api_errors() -> None:
    client, _ = _client(_json({"error": "boom"}, status=500))
    with pytest.raises(ModelApiError, match="HTTP 500"):
        await _complete(client)


async def test_connection_failures_become_model_api_errors() -> None:
    def refuse(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    client, _ = _client(refuse)
    with pytest.raises(ModelApiError, match="APIConnectionError"):
        await _complete(client)


async def test_a_response_without_choices_is_an_error() -> None:
    body = _completion({"role": "assistant", "content": "x"})
    body["choices"] = []
    client, _ = _client(_json(body))
    with pytest.raises(ModelApiError, match="no choices"):
        await _complete(client)


async def test_the_reasoning_of_the_provider_is_captured_when_present() -> None:
    client, _ = _client(
        lambda _request: httpx2.Response(
            200,
            json=_completion(
                {"role": "assistant", "content": "ok", "reasoning": "primeiro olho o diff"}
            ),
        )
    )
    response = await _complete(client)
    assert response.reasoning == "primeiro olho o diff"


async def test_the_reasoning_content_alias_is_also_understood() -> None:
    client, _ = _client(
        lambda _request: httpx2.Response(
            200,
            json=_completion({"role": "assistant", "content": "ok", "reasoning_content": "alias"}),
        )
    )
    assert (await _complete(client)).reasoning == "alias"


@pytest.mark.parametrize("value", [None, "", "   ", 5, ["lista"]])
async def test_an_absent_or_odd_reasoning_is_none(value: object) -> None:
    message: dict[str, object] = {"role": "assistant", "content": "ok", "reasoning": value}
    client, _ = _client(lambda _request: httpx2.Response(200, json=_completion(message)))
    assert (await _complete(client)).reasoning is None


async def test_no_reasoning_field_means_no_reasoning() -> None:
    client, _ = _client(
        lambda _request: httpx2.Response(
            200, json=_completion({"role": "assistant", "content": "ok"})
        )
    )
    assert (await _complete(client)).reasoning is None


async def test_the_reasoning_effort_is_sent_only_when_configured() -> None:
    message = {"role": "assistant", "content": "ok"}
    client, seen = _client(_json(_completion(message)))
    await _complete(client)
    assert "reasoning" not in json.loads(seen[0].content)

    seen_effort: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen_effort.append(request)
        return httpx2.Response(200, json=_completion(message))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    configured = OpenRouterClient(
        API_KEY, http_client=http, max_retries=0, reasoning_effort="xhigh"
    )
    await _complete(configured)
    assert json.loads(seen_effort[0].content)["reasoning"] == {"effort": "xhigh"}
