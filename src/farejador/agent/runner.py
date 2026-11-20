# Filename: runner.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The tool-calling loop with budgets and a validated final answer (FR-10, FR-11, FR-12)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from farejador.agent import prompts
from farejador.agent.llm import LLMClient, LLMResponse, ModelApiError, ToolCall
from farejador.agent.schemas import (
    EXPLORATION_TOOL_NAMES,
    EXPLORATION_TOOLS,
    SUBMIT_REVIEW,
    SUBMIT_VERDICTS,
    OpenThread,
    ThreadVerdict,
    VerdictsPayload,
)
from farejador.review.findings import ReviewResult
from farejador.tools import RepoTools, error_json
from farejador.trace.recorder import NULL_RUN, RunTrace
from farejador.trace.store import ToolResult

logger = logging.getLogger(__name__)

MAX_TEXT_NUDGES = 2
MAX_INVALID_SUBMITS = 2
WRAP_UP_TIMEOUT_S = 30.0
WRAP_UP_MAX_TOKENS = 4000
_NUDGE = "Você deve terminar chamando {name} com a sua resposta final."


class InvalidModelOutput(Exception):
    """The model kept returning answers we cannot use."""


@dataclass(frozen=True, slots=True)
class Budget:
    """Per-run limits (NFR-6); ``max_files`` is applied before the prompt is built."""

    max_steps: int = 15
    max_tokens: int = 200_000
    max_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class ReviewRun:
    result: ReviewResult
    steps: int
    tokens: int
    duration_s: float
    partial: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class VerdictRun:
    verdicts: dict[str, ThreadVerdict]
    steps: int
    tokens: int
    duration_s: float
    partial: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class _Final:
    """How the loop recognises and validates its final tool call."""

    name: str
    schema: dict[str, Any]
    validate: Callable[[str], tuple[Any | None, str | None]]


@dataclass(frozen=True, slots=True)
class _Outcome:
    value: Any | None
    steps: int
    tokens: int
    duration_s: float
    note: str | None = None


class AgentRunner:
    """Runs the review and re-evaluation conversations against an ``LLMClient``."""

    def __init__(
        self,
        llm: LLMClient,
        model: str,
        budget: Budget | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wrap_up_timeout_s: float = WRAP_UP_TIMEOUT_S,
    ) -> None:
        self._llm = llm
        self._model = model
        self._budget = budget or Budget()
        self._clock = clock
        self._wrap_up_timeout = wrap_up_timeout_s

    # -- public modes ----------------------------------------------------------------------

    async def review(
        self,
        *,
        pr_title: str,
        numbered_diff: str,
        skipped: Sequence[tuple[str, str]],
        tools: RepoTools,
        trace: RunTrace | None = None,
    ) -> ReviewRun:
        final = _Final("submit_review", SUBMIT_REVIEW, _validate_review)
        outcome = await self._loop(
            prompts.review_system_prompt(),
            prompts.review_user_prompt(pr_title, numbered_diff, skipped),
            tools,
            final,
            trace or NULL_RUN,
        )
        result = outcome.value or ReviewResult(summary="", findings=[])
        return ReviewRun(
            result=result,
            steps=outcome.steps,
            tokens=outcome.tokens,
            duration_s=outcome.duration_s,
            partial=outcome.note is not None,
            note=outcome.note,
        )

    async def reevaluate(
        self,
        *,
        threads: Sequence[OpenThread],
        tools: RepoTools,
        trace: RunTrace | None = None,
    ) -> VerdictRun:
        expected = {thread.thread_id for thread in threads}
        final = _Final(
            "submit_verdicts", SUBMIT_VERDICTS, lambda raw: _validate_verdicts(raw, expected)
        )
        outcome = await self._loop(
            prompts.reevaluate_system_prompt(),
            prompts.reevaluate_user_prompt(threads),
            tools,
            final,
            trace or NULL_RUN,
        )
        given: dict[str, ThreadVerdict] = {}
        if outcome.value is not None:
            given = {v.thread_id: v for v in outcome.value if v.thread_id in expected}
        verdicts = {
            thread.thread_id: given.get(
                thread.thread_id, ThreadVerdict(thread_id=thread.thread_id, fixed=False)
            )
            for thread in threads
        }
        return VerdictRun(
            verdicts=verdicts,
            steps=outcome.steps,
            tokens=outcome.tokens,
            duration_s=outcome.duration_s,
            partial=outcome.note is not None,
            note=outcome.note,
        )

    # -- the loop --------------------------------------------------------------------------

    async def _loop(
        self, system: str, user: str, tools: RepoTools, final: _Final, trace: RunTrace
    ) -> _Outcome:
        start = self._clock()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        schemas = [*EXPLORATION_TOOLS, final.schema]
        steps = tokens = nudges = invalid = 0
        pending = list(messages)  # what the harness added since the last recorded step
        index = 0

        while True:
            reason = self._exhausted(steps, tokens, start)
            response: LLMResponse | None = None
            step_started = datetime.now(UTC)
            step_t0 = self._clock()
            if reason is None:
                remaining = self._budget.max_seconds - (self._clock() - start)
                try:
                    response = await asyncio.wait_for(
                        self._llm.complete(
                            model=self._model,
                            messages=messages,
                            tools=schemas,
                            tool_choice="auto",
                        ),
                        timeout=max(remaining, 0.001),
                    )
                except TimeoutError:
                    reason = "limite de tempo atingido"
            if response is None:
                return await self._wrap_up(
                    messages,
                    final,
                    reason or "orçamento esgotado",
                    steps,
                    tokens,
                    start,
                    trace=trace,
                    pending=pending,
                    index=index,
                )

            tokens += response.total_tokens
            messages.append(_assistant_message(response))
            results: list[ToolResult] = []

            if not response.tool_calls:
                nudges += 1
                self._emit(trace, index, step_started, step_t0, response, pending, results)
                if nudges > MAX_TEXT_NUDGES:
                    raise InvalidModelOutput("the model did not call a tool to finish")
                nudge = {"role": "user", "content": _NUDGE.format(name=final.name)}
                messages.append(nudge)
                pending = [nudge]
                index += 1
                continue
            nudges = 0

            for call in response.tool_calls:
                if call.name == final.name:
                    value, error = final.validate(call.arguments)
                    if error is None:
                        self._emit(trace, index, step_started, step_t0, response, pending, results)
                        duration = self._clock() - start
                        return _Outcome(value, steps, tokens, duration)
                    invalid += 1
                    if invalid > MAX_INVALID_SUBMITS:
                        self._emit(trace, index, step_started, step_t0, response, pending, results)
                        raise InvalidModelOutput(f"{final.name} was invalid too many times")
                    content = error_json(error)
                    results.append(ToolResult(call.id, call.name, 0.0, content))
                    messages.append(_tool_message(call, content))
                else:
                    tool_t0 = self._clock()
                    if steps >= self._budget.max_steps:
                        content = error_json("orçamento de ferramentas esgotado; conclua agora")
                    else:
                        steps += 1
                        content = await self._run_tool(tools, call)
                    results.append(ToolResult(call.id, call.name, self._clock() - tool_t0, content))
                    messages.append(_tool_message(call, content))
            self._emit(trace, index, step_started, step_t0, response, pending, results)
            pending = []
            index += 1

    def _emit(
        self,
        trace: RunTrace,
        index: int,
        started: datetime,
        t0: float,
        response: LLMResponse,
        pending: list[dict[str, Any]],
        results: list[ToolResult],
    ) -> None:
        _record_step(trace, index, started, self._clock() - t0, response, pending, results)

    def _exhausted(self, steps: int, tokens: int, start: float) -> str | None:
        if steps >= self._budget.max_steps:
            return "limite de passos atingido"
        if tokens >= self._budget.max_tokens:
            return "limite de tokens atingido"
        if self._clock() - start >= self._budget.max_seconds:
            return "limite de tempo atingido"
        return None

    async def _run_tool(self, tools: RepoTools, call: ToolCall) -> str:
        if call.name not in EXPLORATION_TOOL_NAMES:
            return error_json(f"ferramenta desconhecida: {call.name}")
        try:
            arguments = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            return error_json("os argumentos não são um JSON válido")
        if not isinstance(arguments, dict):
            return error_json("os argumentos devem ser um objeto JSON")
        return await asyncio.to_thread(tools.execute, call.name, arguments)

    async def _wrap_up(
        self,
        messages: list[dict[str, Any]],
        final: _Final,
        reason: str,
        steps: int,
        tokens: int,
        start: float,
        *,
        trace: RunTrace,
        pending: list[dict[str, Any]],
        index: int,
    ) -> _Outcome:
        """One last forced call asking for the final answer with what is already known."""
        note = f"Revisão interrompida antes do fim: {reason}."
        wrap_message = {
            "role": "user",
            "content": (
                f"Motivo da interrupção: {reason}. Chame {final.name} agora com o que "
                "você já sabe. Não peça mais informações."
            ),
        }
        messages.append(wrap_message)
        pending = [*pending, wrap_message]
        value: Any | None = None
        step_started = datetime.now(UTC)
        step_t0 = self._clock()
        response: LLMResponse | None = None
        try:
            response = await asyncio.wait_for(
                self._llm.complete(
                    model=self._model,
                    messages=messages,
                    tools=[final.schema],
                    tool_choice={"type": "function", "function": {"name": final.name}},
                    max_tokens=WRAP_UP_MAX_TOKENS,
                ),
                timeout=self._wrap_up_timeout,
            )
            tokens += response.total_tokens
            for call in response.tool_calls:
                if call.name == final.name:
                    candidate, error = final.validate(call.arguments)
                    if error is None:
                        value = candidate
                    break
        except (TimeoutError, ModelApiError):
            value = None
        _record_step(trace, index, step_started, self._clock() - step_t0, response, pending, [])
        return _Outcome(value, steps, tokens, self._clock() - start, note)


# -- helpers -------------------------------------------------------------------------------


def _record_step(
    trace: RunTrace,
    index: int,
    started: datetime,
    duration_s: float,
    response: LLMResponse | None,
    pending: list[dict[str, Any]],
    results: list[ToolResult],
) -> None:
    """Hand one step to the trace; the trace never raises, and a bug here must not either."""
    try:
        trace.step(
            index=index,
            started_at=started,
            duration_s=duration_s,
            tokens=response.total_tokens if response else 0,
            input_messages=pending,
            response_content=response.content if response else None,
            reasoning=response.reasoning if response else None,
            tool_calls=[
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in (response.tool_calls if response else [])
            ],
            tool_results=results,
        )
    except Exception:
        logger.error("could not record a trace step")


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": response.content}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in response.tool_calls
        ]
    return message


def _tool_message(call: ToolCall, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def _describe(error: ValidationError) -> str:
    """Field paths and messages only, so large model-written values are not echoed back."""
    lines = []
    for item in error.errors(include_input=False, include_url=False)[:5]:
        location = ".".join(str(part) for part in item["loc"]) or "arguments"
        lines.append(f"{location}: {item['msg']}")
    return "argumentos inválidos: " + "; ".join(lines)


def _validate_review(raw: str) -> tuple[ReviewResult | None, str | None]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "os argumentos não são um JSON válido"
    try:
        return ReviewResult.model_validate(data), None
    except ValidationError as exc:
        return None, _describe(exc)


def _validate_verdicts(
    raw: str, expected: set[str]
) -> tuple[list[ThreadVerdict] | None, str | None]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "os argumentos não são um JSON válido"
    try:
        payload = VerdictsPayload.model_validate(data)
    except ValidationError as exc:
        return None, _describe(exc)
    missing = sorted(expected - {verdict.thread_id for verdict in payload.verdicts})
    if missing:
        return None, "faltam veredictos para os thread ids: " + ", ".join(missing)
    return payload.verdicts, None
