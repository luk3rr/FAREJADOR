// Filename: client.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The client of the read-only API: a time limit on every call, errors with a kind the screens can
// explain, and a shape check on every answer (nothing is drawn from a response that does not match).

import type { ReviewDetail, ReviewList, StatsOut, StatusOut } from "./types.js";

export type ApiErrorKind =
  | "not_found"
  | "invalid_parameter"
  | "unavailable"
  | "rate_limited"
  | "timeout"
  | "network"
  | "aborted"
  | "bad_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, status: number | null = null) {
    super(kind);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

export interface FetchResponseLike {
  readonly status: number;
  json(): Promise<unknown>;
}
export type FetchLike = (url: string, init: { readonly signal: AbortSignal }) => Promise<FetchResponseLike>;

export interface ClientOptions {
  readonly fetch: FetchLike;
  readonly baseUrl?: string;
  readonly timeoutMs?: number;
}

export const DEFAULT_TIMEOUT_MS = 10_000;

export type Guard<T> = (value: unknown) => value is T;

function kindOf(status: number): ApiErrorKind {
  if (status === 404) return "not_found";
  if (status === 422) return "invalid_parameter";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  return "bad_response";
}

export function isObject(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isStatusOut(value: unknown): value is StatusOut {
  return (
    isObject(value) &&
    typeof value["status"] === "string" &&
    typeof value["trace_available"] === "boolean" &&
    typeof value["retention_days"] === "number" &&
    typeof value["reviews"] === "number" &&
    typeof value["app_version"] === "string" &&
    typeof value["started_at"] === "string"
  );
}

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isNullableNumber = (value: unknown): boolean => value === null || isNumber(value);

function allObjects(value: unknown, check: (item: Readonly<Record<string, unknown>>) => boolean): boolean {
  return Array.isArray(value) && value.every((item) => isObject(item) && check(item));
}

export function isStatsOut(value: unknown): value is StatsOut {
  if (!isObject(value)) return false;
  const { totals, duration_s: duration, tokens, findings } = value;
  return (
    isNumber(value["days"]) &&
    typeof value["since"] === "string" &&
    typeof value["until"] === "string" &&
    typeof value["capped"] === "boolean" &&
    isObject(totals) &&
    ["reviews", "complete", "partial", "failed", "failure_rate"].every((key) => isNumber(totals[key])) &&
    isObject(duration) &&
    isNullableNumber(duration["median"]) &&
    isNullableNumber(duration["p95"]) &&
    isObject(tokens) &&
    isNullableNumber(tokens["mean"]) &&
    isNullableNumber(tokens["median"]) &&
    isObject(findings) &&
    ["inline", "summary", "dropped"].every((key) => isNumber(findings[key])) &&
    allObjects(value["by_day"], (day) => typeof day["day"] === "string" && isNumber(day["reviews"])) &&
    allObjects(
      value["by_model"],
      (row) =>
        typeof row["model"] === "string" &&
        typeof row["prompt_version"] === "string" &&
        isNumber(row["reviews"]) &&
        isNumber(row["failed"]) &&
        isNullableNumber(row["mean_tokens"]) &&
        isNullableNumber(row["median_duration_s"]) &&
        isNumber(row["findings_per_review"]),
    )
  );
}

function isReviewSummary(item: Readonly<Record<string, unknown>>): boolean {
  const text = ["repo", "kind", "model", "prompt_version", "app_version", "outcome", "started_at"];
  const numbers = ["id", "pr_number", "step_count", "tokens", "findings_inline", "findings_summary", "findings_dropped"];
  return (
    text.every((key) => typeof item[key] === "string") &&
    numbers.every((key) => isNumber(item[key])) &&
    (item["head_sha"] === null || typeof item["head_sha"] === "string") &&
    (item["error_category"] === null || typeof item["error_category"] === "string") &&
    isNullableNumber(item["duration_s"])
  );
}

export function isReviewList(value: unknown): value is ReviewList {
  return (
    isObject(value) &&
    allObjects(value["items"], isReviewSummary) &&
    (value["next_cursor"] === null || typeof value["next_cursor"] === "string")
  );
}

const isNullableString = (value: unknown): boolean => value === null || typeof value === "string";

function isStep(step: Readonly<Record<string, unknown>>): boolean {
  const response = step["response"];
  return (
    isNumber(step["index"]) &&
    typeof step["started_at"] === "string" &&
    isNullableNumber(step["duration_s"]) &&
    isNumber(step["tokens"]) &&
    allObjects(step["input_messages"], (m) => typeof m["role"] === "string" && typeof m["content"] === "string" && (m["tool_call_id"] === undefined || isNullableString(m["tool_call_id"]))) &&
    isObject(response) &&
    isNullableString(response["content"]) &&
    isNullableString(response["reasoning"]) &&
    allObjects(response["tool_calls"], (c) => typeof c["id"] === "string" && typeof c["name"] === "string" && typeof c["arguments"] === "string") &&
    allObjects(
      step["tool_results"],
      (r) =>
        typeof r["call_id"] === "string" &&
        typeof r["name"] === "string" &&
        isNullableNumber(r["duration_s"]) &&
        typeof r["content"] === "string" &&
        typeof r["truncated"] === "boolean" &&
        isNumber(r["original_chars"]),
    )
  );
}

function isFinding(finding: Readonly<Record<string, unknown>>): boolean {
  const text = ["path", "severity", "category", "problem", "rationale", "suggestion", "disposition"];
  return (
    text.every((key) => typeof finding[key] === "string") &&
    isNumber(finding["line"]) &&
    isNullableString(finding["suggestion_diff"]) &&
    typeof finding["diff_dropped"] === "boolean" &&
    isNullableString(finding["reason"])
  );
}

export function isReviewDetail(value: unknown): value is ReviewDetail {
  if (!isObject(value) || !isReviewSummary(value)) return false;
  const error = value["error"];
  return (
    isObject(value["budgets"]) &&
    allObjects(value["steps"], isStep) &&
    allObjects(value["findings"], isFinding) &&
    (error === null || (isObject(error) && typeof error["category"] === "string" && typeof error["message"] === "string")) &&
    typeof value["truncated"] === "boolean"
  );
}

export interface ApiClient {
  getJson<T>(path: string, guard: Guard<T>, signal?: AbortSignal): Promise<T>;
  status(signal?: AbortSignal): Promise<StatusOut>;
  stats(days: number, signal?: AbortSignal): Promise<StatsOut>;
  reviews(query: string, signal?: AbortSignal): Promise<ReviewList>;
  review(id: number, signal?: AbortSignal): Promise<ReviewDetail>;
}

export function createClient(options: ClientOptions): ApiClient {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const baseUrl = options.baseUrl ?? "";

  async function getJson<T>(path: string, guard: Guard<T>, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) {
      throw new ApiError("aborted"); // never start a call nobody is waiting for
    }
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const onAbort = (): void => controller.abort();
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      let response: FetchResponseLike;
      let body: unknown;
      try {
        response = await options.fetch(baseUrl + path, { signal: controller.signal });
        body = response.status >= 200 && response.status < 300 ? await response.json() : null;
      } catch {
        if (timedOut) throw new ApiError("timeout");
        if (signal?.aborted) throw new ApiError("aborted");
        throw new ApiError("network");
      }
      if (response.status < 200 || response.status >= 300) {
        throw new ApiError(kindOf(response.status), response.status);
      }
      if (!guard(body)) {
        throw new ApiError("bad_response", response.status);
      }
      return body;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }

  return {
    getJson,
    status: (signal) => getJson("/api/status", isStatusOut, signal),
    review: (id, signal) => getJson(`/api/reviews/${Math.trunc(id)}`, isReviewDetail, signal),
    reviews: (query, signal) => getJson(`/api/reviews?${query}`, isReviewList, signal),
    stats: (days, signal) => getJson(`/api/stats?days=${Math.trunc(days)}`, isStatsOut, signal),
  };
}
