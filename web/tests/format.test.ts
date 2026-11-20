// Filename: format.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { formatCompact, formatDateTime, formatDay, formatDuration, formatInt, formatPercent, formatRelative } from "../src/format.js";

// Intl may use a no-break space between a number and its unit; the screens never depend on it.
const plain = (text: string): string => text.replace(/ | /g, " ");

test("integers use the Brazilian thousands separator", () => {
  assert.equal(plain(formatInt(1280)), "1.280");
  assert.equal(formatInt(0), "0");
  assert.equal(formatInt(2.6), "3");
});

test("compact numbers are written in thousands and millions", () => {
  assert.equal(plain(formatCompact(18452)), "18,5 mil");
  assert.equal(plain(formatCompact(18400)), "18,4 mil");
  assert.equal(plain(formatCompact(1_250_000)), "1,3 mi");
  assert.equal(formatCompact(640), "640");
  assert.equal(formatCompact(0), "0");
  assert.equal(formatCompact(null), "—");
});

test("percentages drop the decimal when the value is whole", () => {
  assert.equal(plain(formatPercent(0.0471)), "4,7%");
  assert.equal(formatPercent(0), "0%");
  assert.equal(formatPercent(1), "100%");
  assert.equal(plain(formatPercent(0.5)), "50%");
  assert.equal(plain(formatPercent(0.62)), "62%");
});

test("durations read naturally from seconds to hours", () => {
  assert.equal(plain(formatDuration(3.2)), "3,2 s");
  assert.equal(formatDuration(0.01), "<0,1 s", "a very short tool call is not shown as zero");
  assert.equal(plain(formatDuration(0.2)), "0,2 s");
  assert.equal(formatDuration(0), "0,0 s");
  assert.equal(formatDuration(38), "38 s");
  assert.equal(formatDuration(59.4), "59 s");
  assert.equal(formatDuration(60), "1 min");
  assert.equal(formatDuration(130), "2 min 10 s");
  assert.equal(formatDuration(7200), "2 h");
  assert.equal(formatDuration(7260), "2 h 1 min");
  assert.equal(formatDuration(null), "—");
});

test("a day becomes dd/mm and anything else is returned as it came", () => {
  assert.equal(formatDay("2026-11-21"), "21/11");
  assert.equal(formatDay("x"), "x");
});

test("relative times step from minutes to days and then to a date", () => {
  const now = new Date("2026-11-21T12:00:00Z");
  assert.equal(formatRelative("2026-11-21T11:59:40Z", now), "agora há pouco");
  assert.equal(formatRelative("2026-11-21T11:48:00Z", now), "há 12 min");
  assert.equal(formatRelative("2026-11-21T09:00:00Z", now), "há 3 h");
  assert.equal(formatRelative("2026-11-20T09:00:00Z", now), "ontem");
  assert.equal(formatRelative("2026-11-18T09:00:00Z", now), "há 3 dias");
  assert.match(formatRelative("2026-10-01T09:00:00Z", now), /^\d{2}\/\d{2}\/\d{4}$/);
  assert.equal(formatRelative("not a date", now), "—");
  assert.equal(formatRelative("2026-11-21T13:00:00Z", now), "agora há pouco", "the future is not negative");
});

test("a date and time are shown in the requested time zone", () => {
  assert.equal(formatDateTime("2026-11-21T20:42:11Z", "America/Sao_Paulo"), "21/11/2026 17:42");
  assert.equal(formatDateTime("2026-11-21T20:42:11Z", "UTC"), "21/11/2026 20:42");
  assert.equal(formatDateTime("nope", "UTC"), "—");
});
