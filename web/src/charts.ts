// Filename: charts.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The two charts of the overview, as virtual nodes: bars per day in SVG, and one stacked bar for
// where the findings went. No drawing library, and nothing here receives markup.

import type { DayCount, FindingDestinations } from "./api/types.js";
import { formatDay, formatInt, formatPercent } from "./format.js";
import { h, withVars } from "./dom/vnode.js";
import type { VElement } from "./dom/vnode.js";

const BAR_SLOT = 34;
const PLOT_HEIGHT = 110;
const LABEL_HEIGHT = 18;
const MAX_LABELS = 16;

/** Bars of reviews per day, with the day of the month under each (every n-th one in long periods). */
export function barChart(days: readonly DayCount[]): VElement {
  const peak = Math.max(1, ...days.map((day) => day.reviews));
  const every = Math.max(1, Math.ceil(days.length / MAX_LABELS));
  const width = Math.max(1, days.length) * BAR_SLOT;
  const total = days.reduce((sum, day) => sum + day.reviews, 0);

  const columns = days.map((day, index) => {
    const height = (day.reviews / peak) * PLOT_HEIGHT;
    const x = index * BAR_SLOT + 6;
    const label = `${formatDay(day.day)}: ${formatInt(day.reviews)} ${day.reviews === 1 ? "revisão" : "revisões"}`;
    return h(
      "g",
      {},
      h("rect", {
        x,
        y: PLOT_HEIGHT - Math.max(height, day.reviews === 0 ? 1 : 0),
        width: BAR_SLOT - 12,
        height: Math.max(height, day.reviews === 0 ? 1 : 0),
        rx: 4,
        fill: day.reviews === 0 ? "var(--line)" : "var(--accent)",
      }, h("title", {}, label)),
      index % every === 0
        ? h("text", { x: index * BAR_SLOT + BAR_SLOT / 2, y: PLOT_HEIGHT + 13, "text-anchor": "middle", "font-size": 9, fill: "var(--muted)" }, formatDay(day.day).slice(0, 2))
        : null,
    );
  });

  return h(
    "svg",
    {
      viewBox: `0 0 ${width} ${PLOT_HEIGHT + LABEL_HEIGHT}`,
      width: "100%",
      role: "img",
      "aria-label": `Revisões por dia: ${formatInt(total)} em ${days.length} dias`,
    },
    columns,
  );
}

export interface Destination {
  readonly key: "inline" | "summary" | "dropped";
  readonly label: string;
  readonly count: number;
  readonly share: number; // 0..1
}

const LABELS: Readonly<Record<Destination["key"], string>> = {
  inline: "No código",
  summary: "No resumo",
  dropped: "Descartados",
};

export function destinations(findings: FindingDestinations): Destination[] {
  const total = findings.inline + findings.summary + findings.dropped;
  return (["inline", "summary", "dropped"] as const).map((key) => ({
    key,
    label: LABELS[key],
    count: findings[key],
    share: total === 0 ? 0 : findings[key] / total,
  }));
}

/** One stacked bar and its legend; empty when the period has no findings. */
export function destinationBar(findings: FindingDestinations): VElement {
  const parts = destinations(findings);
  const total = parts.reduce((sum, part) => sum + part.count, 0);
  if (total === 0) {
    return h("p", { class: "muted" }, "Nenhum achado no período.");
  }
  return h(
    "div",
    { class: "stack" },
    h(
      "div",
      { class: "stacked", role: "img", "aria-label": parts.map((part) => `${part.label} ${formatPercent(part.share)}`).join(", ") },
      parts.map((part) =>
        part.count === 0 ? null : withVars(h("span", { class: `part ${part.key}` }), { "--w": `${(part.share * 100).toFixed(2)}%` }),
      ),
    ),
    h(
      "div",
      { class: "legend" },
      parts.map((part) =>
        h("span", {}, h("b", { class: `swatch ${part.key}` }), `${part.label} ${formatInt(part.count)} (${formatPercent(part.share)})`),
      ),
    ),
  );
}
