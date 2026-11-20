// Filename: overview.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/api/client.js";
import type { StatsOut } from "../src/api/types.js";
import { render } from "../src/dom/render.js";
import { findAll, textOf } from "../src/dom/vnode.js";
import { defaultPeriod, overviewView, periodOptions } from "../src/screens/overview.js";
import type { OverviewState } from "../src/screens/overview.js";
import { allText, fakeFactory } from "./fake-dom.js";
import type { FakeElement } from "./fake-dom.js";

const STATS: StatsOut = {
  days: 30,
  since: "2026-10-23",
  until: "2026-11-21",
  capped: false,
  totals: { reviews: 128, complete: 100, partial: 22, failed: 6, failure_rate: 0.0469 },
  duration_s: { median: 38, p95: 130 },
  tokens: { mean: 18400, median: 15200 },
  by_day: [
    { day: "2026-11-20", reviews: 4 },
    { day: "2026-11-21", reviews: 9 },
  ],
  findings: { inline: 62, summary: 31, dropped: 7 },
  by_model: [
    { model: "provedor/modelo-a", prompt_version: "2026-11-21.2", reviews: 74, failed: 2, mean_tokens: 16900, median_duration_s: 34, findings_per_review: 3.1 },
    { model: "provedor/modelo-b", prompt_version: "2026-11-21.2", reviews: 33, failed: 3, mean_tokens: null, median_duration_s: null, findings_per_review: 3.9 },
  ],
};

const ok = (stats: StatsOut = STATS, period = 30): OverviewState => ({ period, stats: { kind: "ok", data: stats } });
const plain = (text: string): string => text.replace(/ | /g, " ");

test("with data the four numbers, the charts and the table are on the screen", () => {
  const text = plain(textOf(overviewView(ok(), 30)));
  assert.match(text, /Revisões128no período/);
  assert.match(text, /Falhas6 4,7%2[2] parciais/);
  assert.match(text, /Duração mediana38 sp95: 2 min 10 s/);
  assert.match(text, /Tokens por revisão18,4 milmediana 15,2 mil/);
  assert.match(text, /No código 62 \(62%\)/);
  assert.match(text, /Por modelo e versão do prompt/);
  assert.match(text, /provedor\/modelo-a/);
  assert.match(text, /Últimos 30 dias/);
});

test("the model table has a semantic header and one row per model and prompt", () => {
  const view = overviewView(ok(), 30);
  const headers = findAll(view, (e) => e.tag === "th");
  assert.equal(headers.length, 7);
  assert.ok(headers.every((th) => th.attrs["scope"] === "col"));
  assert.equal(findAll(view, (e) => e.tag === "tbody").flatMap((body) => body.children).length, 2);
});

test("missing averages show a dash instead of zero", () => {
  const rows = findAll(overviewView(ok(), 30), (e) => e.tag === "tr").map(textOf);
  assert.ok(rows.some((row) => row.includes("provedor/modelo-b") && row.includes("—")));
});

test("failures are highlighted only when there are some", () => {
  const withFailures = findAll(overviewView(ok(), 30), (e) => e.attrs["class"] === "v bad");
  assert.equal(withFailures.length, 1);
  const clean = ok({ ...STATS, totals: { ...STATS.totals, failed: 0, failure_rate: 0 } });
  assert.equal(findAll(overviewView(clean, 30), (e) => e.attrs["class"] === "v bad").length, 0);
});

test("the period picker marks the active period and tells the app what to load", () => {
  const buttons = findAll(overviewView(ok(STATS, 14), 365), (e) => e.attrs["data-action"] === "set-period");
  assert.deepEqual(buttons.map((b) => b.attrs["data-value"]), ["7", "14", "30", "90", "365"]);
  assert.deepEqual(buttons.map((b) => b.attrs["aria-pressed"]), [false, true, false, false, false]);
  assert.ok(buttons.every((b) => b.tag === "button" && b.attrs["type"] === "button"));
});

test("the periods follow the retention (A-5)", () => {
  assert.deepEqual(periodOptions(null), [7, 14, 30]);
  assert.deepEqual(periodOptions(30), [7, 14, 30]);
  assert.deepEqual(periodOptions(14), [7, 14]);
  assert.deepEqual(periodOptions(3), [3]);
  assert.deepEqual(periodOptions(365), [7, 14, 30, 90, 365]);
  assert.deepEqual(periodOptions(0), [1]);
});

test("the default period is 30 days or the longest the retention allows", () => {
  assert.equal(defaultPeriod(null), 30);
  assert.equal(defaultPeriod(90), 30);
  assert.equal(defaultPeriod(14), 14);
  assert.equal(defaultPeriod(3), 3);
});

test("loading shows a live region and no numbers", () => {
  const view = overviewView({ period: 30, stats: { kind: "loading" } }, 30);
  assert.ok(findAll(view, (e) => e.attrs["role"] === "status").length >= 1);
  assert.doesNotMatch(textOf(view), /Duração mediana/);
});

test("an error shows an alert with a retry button and keeps the period picker", () => {
  const view = overviewView({ period: 7, stats: { kind: "error", error: new ApiError("unavailable", 503) } }, 30);
  assert.equal(findAll(view, (e) => e.attrs["role"] === "alert").length, 1);
  assert.equal(findAll(view, (e) => e.attrs["data-action"] === "retry").length, 1);
  assert.ok(findAll(view, (e) => e.attrs["data-action"] === "set-period").length >= 1);
});

test("no reviews in the period is an empty state, not a screen of zeros", () => {
  const empty = ok({ ...STATS, totals: { reviews: 0, complete: 0, partial: 0, failed: 0, failure_rate: 0 }, by_model: [] });
  const text = textOf(overviewView(empty, 30));
  assert.match(text, /Ainda não há revisões neste período/);
  assert.doesNotMatch(text, /Duração mediana/);
});

test("a capped period warns that the numbers are partial", () => {
  const text = textOf(overviewView(ok({ ...STATS, capped: true }), 30));
  assert.match(text, /só as primeiras/);
  assert.doesNotMatch(textOf(overviewView(ok(), 30)), /só as primeiras/);
});

test("the refresh button is always there", () => {
  for (const stats of [{ kind: "loading" } as const, { kind: "error", error: new ApiError("network") } as const, ok().stats]) {
    const view = overviewView({ period: 30, stats }, 30);
    assert.equal(findAll(view, (e) => e.attrs["data-action"] === "refresh").length, 1);
  }
});

test("hostile model and prompt names stay text everywhere on the screen", () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const stats: StatsOut = {
    ...STATS,
    by_model: [{ ...STATS.by_model[0]!, model: hostile, prompt_version: "</td><script>alert(1)</script>" }],
  };
  const view = overviewView(ok(stats), 30);
  const dom = render(view, fakeFactory) as FakeElement;
  assert.ok(allText(dom).includes(hostile));
  assert.ok(allText(dom).includes("<script>alert(1)</script>"));
  assert.equal(findAll(view, (e) => (e.tag as string) === "img" || (e.tag as string) === "script").length, 0);
});

test("the whole screen goes through the safe renderer in every state", () => {
  const states: OverviewState[] = [
    ok(),
    ok({ ...STATS, capped: true }),
    ok({ ...STATS, by_model: [], findings: { inline: 0, summary: 0, dropped: 0 } }),
    { period: 30, stats: { kind: "loading" } },
    { period: 30, stats: { kind: "error", error: new ApiError("timeout") } },
  ];
  for (const state of states) {
    for (const retention of [null, 3, 30, 365]) {
      assert.doesNotThrow(() => render(overviewView(state, retention), fakeFactory));
    }
  }
});

test("a long period with many days and models still builds quickly", () => {
  const many: StatsOut = {
    ...STATS,
    by_day: Array.from({ length: 365 }, (_, i) => ({ day: `2026-01-${String((i % 28) + 1).padStart(2, "0")}`, reviews: i % 9 })),
    by_model: Array.from({ length: 200 }, (_, i) => ({ ...STATS.by_model[0]!, model: `m/${i}` })),
  };
  const started = performance.now();
  render(overviewView(ok(many, 365), 365), fakeFactory);
  assert.ok(performance.now() - started < 100, "must stay under 100 ms");
});
