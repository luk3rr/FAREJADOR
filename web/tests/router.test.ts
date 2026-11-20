// Filename: router.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { formatRoute, parseFilters, parseHash } from "../src/router.js";
import type { ListFilters, Route } from "../src/router.js";

test("the empty address and the overview address open the overview", () => {
  for (const hash of ["", "#", "#/", "#/visao-geral", "#/visao-geral/", "visao-geral"]) {
    assert.deepEqual(parseHash(hash), { name: "overview" }, hash);
  }
});

test("the detail address carries the id", () => {
  assert.deepEqual(parseHash("#/revisoes/42"), { name: "detail", id: 42 });
  assert.deepEqual(parseHash("#/revisoes/42/"), { name: "detail", id: 42 });
});

test("an invalid id or an unknown address is a not-found route", () => {
  const bad = ["#/revisoes/0", "#/revisoes/-1", "#/revisoes/abc", "#/revisoes/1/extra", "#/revisoes/1.5", "#/qualquer-coisa", "#/revisoes/" + "9".repeat(20), "#/webhook"];
  for (const hash of bad) {
    assert.equal(parseHash(hash).name, "notfound", hash);
  }
});

test("a not-found route keeps a bounded copy of the path, to be shown as text", () => {
  const route = parseHash("#/" + "x".repeat(500));
  assert.equal(route.name, "notfound");
  assert.ok(route.name === "notfound" && route.path.length <= 200);
});

test("filters in the address are read", () => {
  const route = parseHash("#/revisoes?repo=luk3rr/FAREJADOR_PILOT&pr=7&resultado=failed&de=2026-11-01&ate=2026-11-30");
  assert.deepEqual(route, {
    name: "list",
    filters: { repo: "luk3rr/FAREJADOR_PILOT", pr: 7, outcome: "failed", since: "2026-11-01", until: "2026-11-30" },
    warnings: [],
  });
});

test("filters survive a round trip through the address", () => {
  const cases: ListFilters[] = [
    {},
    { repo: "o/r" },
    { pr: 12 },
    { outcome: "partial" },
    { since: "2026-02-28" },
    { repo: "a.b-c_d/e.f-g_h", pr: 2147483647, outcome: "complete", since: "2026-01-01", until: "2026-12-31" },
  ];
  for (const filters of cases) {
    const route: Route = { name: "list", filters, warnings: [] };
    assert.deepEqual(parseHash(formatRoute(route)), route, JSON.stringify(filters));
  }
});

test("routes format to the addresses of the design", () => {
  assert.equal(formatRoute({ name: "overview" }), "#/visao-geral");
  assert.equal(formatRoute({ name: "list", filters: {}, warnings: [] }), "#/revisoes");
  assert.equal(formatRoute({ name: "detail", id: 42 }), "#/revisoes/42");
  assert.equal(formatRoute({ name: "list", filters: { repo: "o/r", outcome: "failed" }, warnings: [] }), "#/revisoes?repo=o%2Fr&resultado=failed");
});

test("invalid filters are ignored with a warning, and valid ones next to them stay", () => {
  const { filters, warnings } = parseFilters("repo=no-slash&pr=0&resultado=bogus&de=2026-13-45&ate=ontem");
  assert.deepEqual(filters, {});
  assert.equal(warnings.length, 5);
  const mixed = parseFilters("repo=o/r&pr=abc");
  assert.deepEqual(mixed.filters, { repo: "o/r" });
  assert.equal(mixed.warnings.length, 1);
});

test("hostile filter values never survive", () => {
  const hostile = [
    "repo=<script>alert(1)</script>/x",
    "repo=o/r'%20OR%20'1'='1",
    "repo=../../etc/passwd",
    "repo=o/r;DROP%20TABLE",
    "pr=1;2",
    "pr=" + "9".repeat(30),
    "pr=-1",
    "pr=1e3",
    "pr=0x10",
    "resultado=complete%00",
    "de=2026-02-30",
    "de=2026-11-01T00:00:00Z",
  ];
  for (const query of hostile) {
    const { filters, warnings } = parseFilters(query);
    assert.deepEqual(filters, {}, query);
    assert.equal(warnings.length, 1, query);
  }
});

test("dates must be real calendar days, including leap years", () => {
  assert.deepEqual(parseFilters("de=2024-02-29").filters, { since: "2024-02-29" });
  assert.deepEqual(parseFilters("de=2025-02-29").filters, {});
  assert.deepEqual(parseFilters("de=2026-04-31").filters, {});
});

test("a start date after the end date is dropped with a warning", () => {
  const { filters, warnings } = parseFilters("de=2026-12-01&ate=2026-01-01");
  assert.deepEqual(filters, { until: "2026-01-01" });
  assert.equal(warnings.length, 1);
});

test("a not-found route formats back to the overview so a link never loops", () => {
  assert.equal(formatRoute({ name: "notfound", path: "x" }), "#/visao-geral");
});
