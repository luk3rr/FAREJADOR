// Filename: client.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, createClient, isReviewDetail, isReviewList, isStatsOut, isStatusOut } from "../src/api/client.js";
import type { FetchLike, FetchResponseLike } from "../src/api/client.js";

const STATUS = { status: "ok", trace_available: true, retention_days: 30, reviews: 3 };

function answer(status: number, body: unknown): FetchLike {
  return async () => ({ status, json: async () => body }) satisfies FetchResponseLike;
}

async function kindOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    assert.ok(error instanceof ApiError, "must be an ApiError");
    return error.kind;
  }
  return "no error";
}

test("a good answer is returned and the request goes to /api/status", async () => {
  const seen: string[] = [];
  const client = createClient({
    fetch: async (url) => {
      seen.push(url);
      return { status: 200, json: async () => STATUS };
    },
  });
  assert.deepEqual(await client.status(), STATUS);
  assert.deepEqual(seen, ["/api/status"]);
});

test("the base url is prepended", async () => {
  const seen: string[] = [];
  const client = createClient({
    baseUrl: "https://example.org",
    fetch: async (url) => {
      seen.push(url);
      return { status: 200, json: async () => STATUS };
    },
  });
  await client.status();
  assert.deepEqual(seen, ["https://example.org/api/status"]);
});

test("each HTTP status becomes an error kind the screens can explain", async () => {
  const expected: [number, string][] = [
    [404, "not_found"],
    [422, "invalid_parameter"],
    [429, "rate_limited"],
    [503, "unavailable"],
    [500, "bad_response"],
    [403, "bad_response"],
    [302, "bad_response"],
  ];
  for (const [status, kind] of expected) {
    const client = createClient({ fetch: answer(status, { error: "x" }) });
    assert.equal(await kindOf(client.status()), kind, String(status));
  }
});

test("an answer that does not have the expected shape is rejected, never drawn", async () => {
  const wrong: unknown[] = [
    null,
    [],
    "ok",
    {},
    { ...STATUS, trace_available: "yes" },
    { ...STATUS, retention_days: "30" },
    { status: "ok" },
    { ...STATUS, reviews: null },
  ];
  for (const body of wrong) {
    const client = createClient({ fetch: answer(200, body) });
    assert.equal(await kindOf(client.status()), "bad_response", JSON.stringify(body));
  }
  assert.equal(isStatusOut(STATUS), true);
});

test("invalid JSON in a 200 answer is a network-level failure, not a crash", async () => {
  const client = createClient({
    fetch: async () => ({
      status: 200,
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
    }),
  });
  assert.equal(await kindOf(client.status()), "network");
});

test("a connection failure is a network error", async () => {
  const client = createClient({
    fetch: async () => {
      throw new TypeError("fetch failed");
    },
  });
  assert.equal(await kindOf(client.status()), "network");
});

test("a call that never answers times out", async () => {
  const client = createClient({
    timeoutMs: 20,
    fetch: (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  });
  assert.equal(await kindOf(client.status()), "timeout");
});

test("the default time limit is 10 seconds", async () => {
  const { DEFAULT_TIMEOUT_MS } = await import("../src/api/client.js");
  assert.equal(DEFAULT_TIMEOUT_MS, 10_000);
});

test("aborting from outside is reported as aborted, not as a failure to show", async () => {
  const controller = new AbortController();
  const client = createClient({
    timeoutMs: 5_000,
    fetch: (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  });
  const pending = client.status(controller.signal);
  controller.abort();
  assert.equal(await kindOf(pending), "aborted");
});

test("an already aborted signal never reaches a success", async () => {
  const controller = new AbortController();
  controller.abort();
  const client = createClient({
    fetch: (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  });
  assert.equal(await kindOf(client.status(controller.signal)), "aborted");
});

test("getJson uses the guard of the caller", async () => {
  const client = createClient({ fetch: answer(200, { n: 1 }) });
  const isN = (value: unknown): value is { n: number } => typeof value === "object" && value !== null && "n" in value;
  assert.deepEqual(await client.getJson("/api/x", isN), { n: 1 });
  assert.equal(await kindOf(client.getJson("/api/x", (v): v is never => v === 7)), "bad_response");
});


const STATS = {
  days: 7,
  since: "2026-11-15",
  until: "2026-11-21",
  capped: false,
  totals: { reviews: 6, complete: 2, partial: 3, failed: 1, failure_rate: 0.1667 },
  duration_s: { median: 10, p95: 30 },
  tokens: { mean: 1840, median: 1000 },
  by_day: [{ day: "2026-11-15", reviews: 0 }],
  findings: { inline: 6, summary: 3, dropped: 2 },
  by_model: [
    { model: "m", prompt_version: "p", reviews: 2, failed: 1, mean_tokens: null, median_duration_s: null, findings_per_review: 1.5 },
  ],
};

test("stats asks for the period and returns the validated answer", async () => {
  const seen: string[] = [];
  const client = createClient({
    fetch: async (url) => {
      seen.push(url);
      return { status: 200, json: async () => STATS };
    },
  });
  assert.deepEqual(await client.stats(7), STATS);
  await client.stats(30.9);
  assert.deepEqual(seen, ["/api/stats?days=7", "/api/stats?days=30"]);
});

test("a stats answer with a wrong shape is rejected in every field", () => {
  assert.equal(isStatsOut(STATS), true);
  const broken: unknown[] = [
    null,
    {},
    { ...STATS, days: "7" },
    { ...STATS, capped: "no" },
    { ...STATS, totals: { ...STATS.totals, failed: "1" } },
    { ...STATS, totals: null },
    { ...STATS, duration_s: { median: "10", p95: 30 } },
    { ...STATS, tokens: { mean: undefined, median: 1 } },
    { ...STATS, findings: { inline: 1, summary: 2 } },
    { ...STATS, by_day: [{ day: 5, reviews: 1 }] },
    { ...STATS, by_day: "none" },
    { ...STATS, by_model: [{ model: "m" }] },
    { ...STATS, by_model: [null] },
    { ...STATS, totals: { ...STATS.totals, reviews: Number.NaN } },
  ];
  for (const value of broken) {
    assert.equal(isStatsOut(value), false, JSON.stringify(value));
  }
});

test("a stats answer that does not match is a bad response, never drawn", async () => {
  const client = createClient({ fetch: answer(200, { ...STATS, totals: null }) });
  assert.equal(await kindOf(client.stats(7)), "bad_response");
});


const REVIEW = {
  id: 42,
  repo: "o/r",
  pr_number: 1,
  head_sha: null,
  kind: "review",
  model: "m",
  prompt_version: "p",
  app_version: "0.2.0",
  outcome: "complete",
  step_count: 3,
  tokens: 100,
  duration_s: null,
  findings_inline: 1,
  findings_summary: 0,
  findings_dropped: 0,
  error_category: null,
  started_at: "2026-11-21T12:00:00Z",
};

test("reviews sends the query as given and returns the validated page", async () => {
  const seen: string[] = [];
  const client = createClient({
    fetch: async (url) => {
      seen.push(url);
      return { status: 200, json: async () => ({ items: [REVIEW], next_cursor: null }) };
    },
  });
  const page = await client.reviews("limit=20&repo=o%2Fr");
  assert.deepEqual(seen, ["/api/reviews?limit=20&repo=o%2Fr"]);
  assert.equal(page.items.length, 1);
  assert.equal(page.next_cursor, null);
});

test("a review page with a wrong shape is rejected in every field", () => {
  assert.equal(isReviewList({ items: [REVIEW], next_cursor: "abc" }), true);
  assert.equal(isReviewList({ items: [], next_cursor: null }), true);
  const broken: unknown[] = [
    null,
    {},
    { items: [REVIEW] },
    { items: "none", next_cursor: null },
    { items: [REVIEW], next_cursor: 5 },
    { items: [null], next_cursor: null },
    { items: [{ ...REVIEW, id: "42" }], next_cursor: null },
    { items: [{ ...REVIEW, repo: 7 }], next_cursor: null },
    { items: [{ ...REVIEW, tokens: null }], next_cursor: null },
    { items: [{ ...REVIEW, head_sha: 3 }], next_cursor: null },
    { items: [{ ...REVIEW, duration_s: "1" }], next_cursor: null },
    { items: [{ ...REVIEW, error_category: 1 }], next_cursor: null },
    { items: [{ ...REVIEW, started_at: undefined }], next_cursor: null },
  ];
  for (const value of broken) {
    assert.equal(isReviewList(value), false, JSON.stringify(value));
  }
});

test("a 422 from the list is an invalid-parameter error the screen can explain", async () => {
  const client = createClient({ fetch: answer(422, { error: "invalid_parameter" }) });
  assert.equal(await kindOf(client.reviews("limit=0")), "invalid_parameter");
});


const DETAIL = {
  ...REVIEW,
  budgets: { max_steps: 15 },
  steps: [
    {
      index: 0,
      started_at: "2026-11-21T12:00:00Z",
      duration_s: 1.5,
      tokens: 10,
      input_messages: [{ role: "user", content: "hi", tool_call_id: null }],
      response: { content: null, reasoning: "r", tool_calls: [{ id: "c", name: "read_file", arguments: "{}" }] },
      tool_results: [{ call_id: "c", name: "read_file", duration_s: null, content: "x", truncated: false, original_chars: 1 }],
    },
  ],
  findings: [
    { path: "a.py", line: 1, severity: "low", category: "other", problem: "p", rationale: "", suggestion: "", suggestion_diff: null, diff_dropped: false, disposition: "inline", reason: null },
  ],
  error: null,
  truncated: false,
};

test("review asks for one id and returns the validated detail", async () => {
  const seen: string[] = [];
  const client = createClient({
    fetch: async (url) => {
      seen.push(url);
      return { status: 200, json: async () => DETAIL };
    },
  });
  assert.equal((await client.review(42)).id, 42);
  await client.review(7.9);
  assert.deepEqual(seen, ["/api/reviews/42", "/api/reviews/7"]);
});

test("a detail with a wrong shape is rejected field by field", () => {
  assert.equal(isReviewDetail(DETAIL), true);
  assert.equal(isReviewDetail({ ...DETAIL, error: { category: "budget", message: "m" } }), true);
  const step = DETAIL.steps[0]!;
  const broken: unknown[] = [
    null,
    REVIEW,
    { ...DETAIL, budgets: null },
    { ...DETAIL, steps: "none" },
    { ...DETAIL, steps: [null] },
    { ...DETAIL, steps: [{ ...step, response: null }] },
    { ...DETAIL, steps: [{ ...step, response: { ...step.response, reasoning: 5 } }] },
    { ...DETAIL, steps: [{ ...step, response: { ...step.response, tool_calls: [{ id: "c" }] } }] },
    { ...DETAIL, steps: [{ ...step, input_messages: [{ role: 1, content: "x" }] }] },
    { ...DETAIL, steps: [{ ...step, tool_results: [{ call_id: "c", name: "n", content: 1, truncated: false, original_chars: 1 }] }] },
    { ...DETAIL, steps: [{ ...step, tool_results: [{ call_id: "c", name: "n", content: "x", truncated: "no", original_chars: 1 }] }] },
    { ...DETAIL, steps: [{ ...step, index: "0" }] },
    { ...DETAIL, findings: [{ ...DETAIL.findings[0]!, line: "1" }] },
    { ...DETAIL, findings: [{ ...DETAIL.findings[0]!, diff_dropped: 0 }] },
    { ...DETAIL, findings: [{ ...DETAIL.findings[0]!, suggestion_diff: 1 }] },
    { ...DETAIL, findings: "none" },
    { ...DETAIL, error: { category: "x" } },
    { ...DETAIL, error: "boom" },
    { ...DETAIL, truncated: "false" },
    { ...DETAIL, repo: undefined },
  ];
  for (const value of broken) {
    assert.equal(isReviewDetail(value), false, JSON.stringify(value));
  }
});

test("a 404 on a review is a not-found error, the same for any reason", async () => {
  const client = createClient({ fetch: answer(404, { error: "not_found" }) });
  assert.equal(await kindOf(client.review(9999)), "not_found");
});
