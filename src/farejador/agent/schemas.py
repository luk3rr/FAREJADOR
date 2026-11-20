# Filename: schemas.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Tool definitions exposed to the model and the payloads of the final tools (contract C-D)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from farejador.review.findings import (
    MAX_DIFF,
    MAX_FINDINGS,
    MAX_PROBLEM,
    MAX_RATIONALE,
    MAX_SUGGESTION,
    MAX_SUMMARY,
    Category,
    Severity,
)

MAX_VERDICT_NOTE = 300


def _function(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


READ_FILE = _function(
    "read_file",
    "Lê um arquivo de texto do repositório, opcionalmente um intervalo de linhas.",
    {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
    },
)

GREP = _function(
    "grep",
    "Busca uma expressão regular estendida nos arquivos de texto do repositório.",
    {
        "type": "object",
        "required": ["pattern"],
        "properties": {
            "pattern": {"type": "string", "maxLength": 200},
            "path": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    },
)

LIST_DIR = _function(
    "list_dir",
    "Lista as entradas de um diretório do repositório.",
    {"type": "object", "properties": {"path": {"type": "string"}}},
)

FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["file", "line", "severity", "category", "problem", "rationale", "suggestion"],
    "properties": {
        "file": {"type": "string"},
        "line": {"type": "integer", "minimum": 1},
        "severity": {"enum": [item.value for item in Severity]},
        "category": {"enum": [item.value for item in Category]},
        "problem": {"type": "string", "maxLength": MAX_PROBLEM},
        "rationale": {"type": "string", "maxLength": MAX_RATIONALE},
        "suggestion": {"type": "string", "maxLength": MAX_SUGGESTION},
        "suggestion_diff": {"type": "string", "maxLength": MAX_DIFF},
    },
}

SUBMIT_REVIEW = _function(
    "submit_review",
    "Conclui a revisão com os achados finais, escritos em português do Brasil.",
    {
        "type": "object",
        "required": ["summary", "findings"],
        "properties": {
            "summary": {"type": "string", "maxLength": MAX_SUMMARY},
            "findings": {"type": "array", "maxItems": MAX_FINDINGS, "items": FINDING_SCHEMA},
        },
    },
)

SUBMIT_VERDICTS = _function(
    "submit_verdicts",
    "Conclui a reavaliação com um veredicto por thread aberto, com notas em português do Brasil.",
    {
        "type": "object",
        "required": ["verdicts"],
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["thread_id", "fixed"],
                    "properties": {
                        "thread_id": {"type": "string"},
                        "fixed": {"type": "boolean"},
                        "note": {"type": "string", "maxLength": MAX_VERDICT_NOTE},
                    },
                },
            }
        },
    },
)

EXPLORATION_TOOLS: tuple[dict[str, Any], ...] = (READ_FILE, GREP, LIST_DIR)
EXPLORATION_TOOL_NAMES = frozenset({"read_file", "grep", "list_dir"})


class OpenThread(BaseModel):
    """A review thread created by Farejador that is still open."""

    model_config = ConfigDict(frozen=True)

    thread_id: str
    path: str | None
    line: int | None
    body: str


class ThreadVerdict(BaseModel):
    """The model's decision about one open thread."""

    model_config = ConfigDict(frozen=True, extra="ignore", str_strip_whitespace=True)

    thread_id: str = Field(min_length=1)
    fixed: bool
    note: str = Field(default="", max_length=MAX_VERDICT_NOTE)


class VerdictsPayload(BaseModel):
    """Arguments of the ``submit_verdicts`` tool call."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    verdicts: list[ThreadVerdict]
