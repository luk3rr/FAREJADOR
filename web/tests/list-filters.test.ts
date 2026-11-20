// Filename: list-filters.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { formatRoute, parseHash } from "../src/router.js";
import { PAGE_SIZE, apiQuery, filtersFromForm, hasFilters } from "../src/screens/list-filters.js";

const EMPTY = { repo: "", pr: "", since: "", until: "", outcome: "" } as const;

test("an empty form means no filters and no warnings", () => {
  assert.deepEqual(filtersFromForm(EMPTY), { filters: {}, warnings: [] });
  assert.deepEqual(filtersFromForm({ ...EMPTY, repo: "  ", pr: "\t" }), { filters: {}, warnings: [] });
});

test("a filled form becomes validated filters, with spaces trimmed", () => {
  const { filters, warnings } = filtersFromForm({ repo: " luk3rr/FAREJADOR_PILOT ", pr: " 7 ", since: "2026-11-01", until: "2026-11-30", outcome: "failed" });
  assert.deepEqual(filters, { repo: "luk3rr/FAREJADOR_PILOT", pr: 7, outcome: "failed", since: "2026-11-01", until: "2026-11-30" });
  assert.deepEqual(warnings, []);
});

test("invalid fields are dropped with a warning and the valid ones stay", () => {
  const { filters, warnings } = filtersFromForm({ repo: "no-slash", pr: "abc", since: "2026-02-30", until: "2026-11-30", outcome: "partial" });
  assert.deepEqual(filters, { outcome: "partial", until: "2026-11-30" });
  assert.equal(warnings.length, 3);
});

test("what the form produces survives the address: form → address → filters", () => {
  const cases = [
    { ...EMPTY, repo: "o/r" },
    { ...EMPTY, pr: "12", outcome: "complete" as const },
    { repo: "a.b/c_d", pr: "3", since: "2026-01-01", until: "2026-12-31", outcome: "failed" as const },
  ];
  for (const form of cases) {
    const { filters } = filtersFromForm(form);
    const back = parseHash(formatRoute({ name: "list", filters, warnings: [] }));
    assert.deepEqual(back.name === "list" ? back.filters : null, filters);
  }
});

test("hostile form values never become filters", () => {
  const hostile = ["<script>alert(1)</script>/x", "o/r' OR '1'='1", "../../etc/passwd", "o/r&pr=1", "o/r#x"];
  for (const repo of hostile) {
    const { filters, warnings } = filtersFromForm({ ...EMPTY, repo });
    assert.deepEqual(filters, {}, repo);
    assert.equal(warnings.length, 1, repo);
  }
});

test("hasFilters tells an empty filter from a used one", () => {
  assert.equal(hasFilters({}), false);
  assert.equal(hasFilters({ pr: 1 }), true);
});

test("the API query carries the page size, the cursor and every filter", () => {
  assert.equal(apiQuery({}, null), `limit=${PAGE_SIZE}`);
  assert.equal(PAGE_SIZE, 20);
  const query = new URLSearchParams(apiQuery({ repo: "o/r", pr: 5, outcome: "failed", since: "2026-11-01", until: "2026-11-30" }, "abc", 50));
  assert.equal(query.get("limit"), "50");
  assert.equal(query.get("cursor"), "abc");
  assert.equal(query.get("repo"), "o/r");
  assert.equal(query.get("pr"), "5");
  assert.equal(query.get("outcome"), "failed");
  assert.equal(query.get("since"), "2026-11-01T00:00:00Z", "the whole first day");
  assert.equal(query.get("until"), "2026-11-30T23:59:59Z", "the whole last day");
});

test("values are encoded, so a filter can never add parameters of its own", () => {
  const query = apiQuery({ repo: "o/r" }, "a&limit=1000");
  assert.equal(new URLSearchParams(query).get("limit"), String(PAGE_SIZE));
  assert.equal(new URLSearchParams(query).get("cursor"), "a&limit=1000");
});
