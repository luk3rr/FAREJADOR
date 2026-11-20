# Filename: routes.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The read-only API of the review trace (FR-9 to FR-12, FR-15, FR-18, NFR-7, NFR-8).

It is a separate FastAPI app that the webhook app mounts under ``/api``, so its error format, its
headers and its 404 never touch the webhook. Responses go through response models: a field that
is not in the contract (for example the visibility mark) cannot leave by accident.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from farejador.trace import queries
from farejador.trace.store import TraceUnavailable, open_readonly

logger = logging.getLogger(__name__)

MAX_LIMIT = 50
STATS_DEFAULT_DAYS = 30
STATS_MAX_DAYS = 365
STATS_CACHE = "public, max-age=60"
DEFAULT_LIMIT = 20
REPO_PATTERN = r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"
SUCCESS_CACHE = "public, max-age=30"
ERROR_CACHE = "no-store"


class JsonResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


class OutcomeFilter(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


# -- response models (the public contract of design.md § 2.8) ---------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewSummary(_Out):
    id: int
    repo: str
    pr_number: int
    head_sha: str | None
    kind: str
    model: str
    prompt_version: str
    app_version: str
    outcome: str
    step_count: int
    tokens: int
    duration_s: float | None
    findings_inline: int
    findings_summary: int
    findings_dropped: int
    error_category: str | None
    started_at: str


class ReviewList(_Out):
    items: list[ReviewSummary]
    next_cursor: str | None


class ToolCallOut(_Out):
    id: str
    name: str
    arguments: str


class ResponseOut(_Out):
    content: str | None
    reasoning: str | None
    tool_calls: list[ToolCallOut]


class ToolResultOut(_Out):
    call_id: str
    name: str
    duration_s: float | None
    content: str
    truncated: bool
    original_chars: int


class MessageOut(_Out):
    role: str
    content: str
    tool_call_id: str | None = None


class StepOut(_Out):
    index: int
    started_at: str
    duration_s: float | None
    tokens: int
    input_messages: list[MessageOut]
    response: ResponseOut
    tool_results: list[ToolResultOut]


class FindingOut(_Out):
    path: str
    line: int
    severity: str
    category: str
    problem: str
    rationale: str
    suggestion: str
    suggestion_diff: str | None
    diff_dropped: bool
    disposition: str
    reason: str | None


class ErrorOut(_Out):
    category: str
    message: str


class ReviewDetail(ReviewSummary):
    """The summary plus everything the trace holds."""

    budgets: dict[str, Any]
    steps: list[StepOut]
    findings: list[FindingOut]
    error: ErrorOut | None
    truncated: bool


class StatusOut(_Out):
    status: str
    trace_available: bool
    retention_days: int
    reviews: int


class StatsTotals(_Out):
    reviews: int
    complete: int
    partial: int
    failed: int
    failure_rate: float


class DurationStats(_Out):
    median: float | None
    p95: float | None


class TokenStats(_Out):
    mean: float | None
    median: float | None


class DayCount(_Out):
    day: str
    reviews: int


class FindingDestinations(_Out):
    inline: int
    summary: int
    dropped: int


class ModelRow(_Out):
    model: str
    prompt_version: str
    reviews: int
    failed: int
    mean_tokens: float | None
    median_duration_s: float | None
    findings_per_review: float


class StatsOut(_Out):
    days: int
    since: str
    until: str
    capped: bool
    totals: StatsTotals
    duration_s: DurationStats
    tokens: TokenStats
    by_day: list[DayCount]
    findings: FindingDestinations
    by_model: list[ModelRow]


class ErrorBody(_Out):
    error: str


class InvalidParameter(Exception):
    """A parameter is well formed but not acceptable (bad cursor, ``since`` after ``until``)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _error(status: int, error: str, **extra: Any) -> JSONResponse:
    return JsonResponse({"error": error, **extra}, status_code=status)


def create_api(
    trace_path: Path | str,
    *,
    retention_days: int = 30,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    """Build the API app; it opens the trace read-only for each request."""
    api = FastAPI(
        title="Farejador trace API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
        default_response_class=JsonResponse,
    )
    path = Path(trace_path)

    def connect() -> sqlite3.Connection:
        conn = open_readonly(path)
        queries.with_deadline(conn)
        return conn

    # -- errors ------------------------------------------------------------

    @api.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = [
            {"field": str(item["loc"][-1]) if item["loc"] else "request", "message": item["msg"]}
            for item in exc.errors()
        ]
        return _error(422, "invalid_parameter", detail=detail)

    @api.exception_handler(InvalidParameter)
    async def _invalid(_request: Request, exc: InvalidParameter) -> JSONResponse:
        return _error(
            422, "invalid_parameter", detail=[{"field": exc.field, "message": exc.message}]
        )

    @api.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            response = _error(405, "method_not_allowed")
            response.headers["Allow"] = "GET, HEAD"
            return response
        if exc.status_code == 404:
            return _error(404, "not_found")
        return _error(exc.status_code, "error")

    @api.exception_handler(TraceUnavailable)
    async def _unavailable(_request: Request, _exc: TraceUnavailable) -> JSONResponse:
        return _error(503, "trace_unavailable")

    @api.exception_handler(sqlite3.Error)
    async def _sqlite(_request: Request, exc: sqlite3.Error) -> JSONResponse:
        logger.error("trace query failed", extra={"error_type": type(exc).__name__})
        return _error(503, "trace_unavailable")

    @api.middleware("http")
    async def _headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        ok = 200 <= response.status_code < 300
        if "cache-control" not in response.headers:  # a route may ask for its own policy
            response.headers["Cache-Control"] = SUCCESS_CACHE if ok else ERROR_CACHE
        return response

    # -- routes ------------------------------------------------------------

    @api.head("/reviews", include_in_schema=False)
    @api.get("/reviews", response_model=ReviewList, summary="List reviews, newest first")
    def list_reviews(
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: Annotated[str | None, Query(max_length=64)] = None,
        repo: Annotated[str | None, Query(pattern=REPO_PATTERN)] = None,
        pr: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
        outcome: OutcomeFilter | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        after_id: int | None = None
        if cursor is not None:
            try:
                after_id = queries.decode_cursor(cursor)
            except queries.InvalidCursor:
                raise InvalidParameter("cursor", "invalid cursor") from None
        since, until = _utc(since), _utc(until)
        if since is not None and until is not None and since > until:
            raise InvalidParameter("since", "must not be after until")
        filters = queries.ListFilters(
            repo=repo,
            pr_number=pr,
            outcome=outcome.value if outcome else None,
            since=since,
            until=until,
        )
        conn = connect()
        try:
            items, next_id = queries.list_runs(
                conn, limit=limit, after_id=after_id, filters=filters
            )
        finally:
            conn.close()
        return {
            "items": items,
            "next_cursor": queries.encode_cursor(next_id) if next_id is not None else None,
        }

    @api.head("/reviews/{review_id}", include_in_schema=False)
    @api.get(
        "/reviews/{review_id}",
        response_model=ReviewDetail,
        summary="The full trace of one review",
    )
    def get_review(
        review_id: Annotated[int, PathParam(ge=1, le=queries.MAX_ID)],
    ) -> dict[str, Any]:
        conn = connect()
        try:
            detail = queries.get_run(conn, review_id)
        finally:
            conn.close()
        if detail is None:  # missing, private and unknown look exactly the same
            raise StarletteHTTPException(404)
        return detail

    @api.head("/stats", include_in_schema=False)
    @api.get("/stats", response_model=StatsOut, summary="Aggregates of the last N days")
    def get_stats(
        response: Response,
        days: Annotated[int, Query(ge=1, le=STATS_MAX_DAYS)] = STATS_DEFAULT_DAYS,
    ) -> dict[str, Any]:
        conn = connect()
        try:
            result = queries.stats(conn, now=clock(), days=days)
        finally:
            conn.close()
        response.headers["Cache-Control"] = STATS_CACHE
        return result

    @api.head("/status", include_in_schema=False)
    @api.get("/status", response_model=StatusOut, summary="Whether the trace is available")
    def status() -> dict[str, Any]:
        conn = connect()
        try:
            count = queries.count_public(conn)
        finally:
            conn.close()
        return {
            "status": "ok",
            "trace_available": True,
            "retention_days": retention_days,
            "reviews": count,
        }

    return api


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
