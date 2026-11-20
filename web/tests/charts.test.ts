// Filename: charts.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import type { DayCount } from "../src/api/types.js";
import { barChart, destinationBar, destinations } from "../src/charts.js";
import { render } from "../src/dom/render.js";
import { findAll, textOf } from "../src/dom/vnode.js";
import { fakeFactory } from "./fake-dom.js";

const days = (counts: number[]): DayCount[] =>
  counts.map((reviews, index) => ({ day: `2026-11-${String(index + 1).padStart(2, "0")}`, reviews }));

test("there is one bar per day, empty days included", () => {
  const chart = barChart(days([3, 0, 5, 0]));
  assert.equal(findAll(chart, (e) => e.tag === "rect").length, 4);
});

test("the tallest day fills the plot and the others are proportional", () => {
  const rects = findAll(barChart(days([2, 4, 0])), (e) => e.tag === "rect");
  const heights = rects.map((rect) => Number(rect.attrs["height"]));
  assert.equal(heights[1], 110);
  assert.equal(heights[0], 55);
  assert.equal(heights[2], 1, "an empty day keeps a 1-unit baseline so it stays visible");
});

test("empty days are drawn with the neutral colour and busy days with the accent", () => {
  const fills = findAll(barChart(days([1, 0])), (e) => e.tag === "rect").map((r) => r.attrs["fill"]);
  assert.deepEqual(fills, ["var(--accent)", "var(--line)"]);
});

test("every bar has an accessible tooltip and the chart has a summary label", () => {
  const chart = barChart(days([1, 2]));
  const titles = findAll(chart, (e) => e.tag === "title").map(textOf);
  assert.deepEqual(titles, ["01/11: 1 revisão", "02/11: 2 revisões"]);
  assert.equal(chart.attrs["role"], "img");
  assert.match(String(chart.attrs["aria-label"]), /3 em 2 dias/);
});

test("long periods label only some days so they do not overlap", () => {
  const labels = (count: number): number => findAll(barChart(days(Array(count).fill(1))), (e) => e.tag === "text").length;
  assert.equal(labels(14), 14);
  assert.ok(labels(30) <= 16);
  assert.ok(labels(365) <= 16);
});

test("a period with no reviews at all still draws", () => {
  const chart = barChart(days([0, 0, 0]));
  assert.equal(findAll(chart, (e) => e.tag === "rect").length, 3);
  assert.doesNotThrow(() => render(chart, fakeFactory));
  assert.doesNotThrow(() => render(barChart([]), fakeFactory));
});

test("the chart is accepted by the safe renderer, so it uses no forbidden attribute", () => {
  assert.doesNotThrow(() => render(barChart(days([1, 2, 3, 4, 5, 6, 7])), fakeFactory));
});

test("the destination shares add up to 100%", () => {
  const parts = destinations({ inline: 62, summary: 31, dropped: 7 });
  assert.deepEqual(parts.map((p) => p.label), ["No código", "No resumo", "Descartados"]);
  assert.ok(Math.abs(parts.reduce((sum, p) => sum + p.share, 0) - 1) < 1e-9);
  assert.equal(parts[0]?.share, 0.62);
});

test("the stacked bar has one segment per non-empty destination, with the width as a CSS variable", () => {
  const bar = destinationBar({ inline: 6, summary: 0, dropped: 2 });
  const parts = findAll(bar, (e) => String(e.attrs["class"] ?? "").startsWith("part"));
  assert.equal(parts.length, 2);
  assert.deepEqual(parts.map((p) => p.vars["--w"]), ["75.00%", "25.00%"]);
  assert.match(textOf(bar), /No código 6 \(75%\)/);
  assert.match(textOf(bar), /Descartados 2 \(25%\)/);
});

test("without findings the bar says so and draws nothing", () => {
  const bar = destinationBar({ inline: 0, summary: 0, dropped: 0 });
  assert.match(textOf(bar), /Nenhum achado no período/);
  assert.equal(findAll(bar, (e) => e.tag === "span").length, 0);
});
