// Filename: detail-banners.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The faixas that explain how a review ended, and the card with how much of each budget it used.

import type { ReviewDetail } from "../api/types.js";
import { h, withVars } from "../dom/vnode.js";
import type { VElement } from "../dom/vnode.js";
import { formatInt } from "../format.js";

/** The banners for failure, a partial run and cut text. */
export function statusBanners(detail: ReviewDetail): VElement[] {
  const banners: VElement[] = [];
  if (detail.outcome === "failed") {
    banners.push(
      h(
        "div",
        { class: "banner bad", role: "alert" },
        h("b", {}, "Falhou"),
        detail.error === null ? null : [" · ", h("span", { class: "mono" }, detail.error.category), " — ", detail.error.message],
        detail.error === null ? " Não há detalhes do erro." : null,
      ),
    );
  } else if (detail.outcome === "partial") {
    banners.push(
      h(
        "div",
        { class: "banner", role: "status" },
        h("b", {}, "Parcial"),
        detail.error === null
          ? " · a revisão não terminou normalmente (ainda em andamento ou interrompida)."
          : [" · ", h("span", { class: "mono" }, detail.error.category), " — ", detail.error.message],
      ),
    );
  }
  if (detail.truncated) {
    banners.push(
      h(
        "div",
        { class: "banner info", role: "status" },
        "Parte do texto foi cortada ao gravar (limite por item ou teto por revisão). Os trechos cortados trazem o aviso ",
        h("span", { class: "mono" }, "[…cortado: N caracteres no original]"),
        ".",
      ),
    );
  }
  return banners;
}

function limit(budgets: Readonly<Record<string, unknown>>, key: string): number | null {
  const value = budgets[key];
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function budgetRow(label: string, used: number, max: number | null, unit: string, hot: number): VElement {
  const share = max === null ? 0 : Math.min(1, used / max);
  return h(
    "div",
    { class: "budget" },
    h("span", {}, label),
    h("div", { class: share >= hot ? "bar warn" : "bar", role: "img", "aria-label": max === null ? `${label}: ${formatInt(used)}${unit}` : `${label}: ${formatInt(used)}${unit} de ${formatInt(max)}${unit}` }, withVars(h("i", {}), { "--w": `${(share * 100).toFixed(1)}%` })),
    h("span", { class: "mono" }, max === null ? `${formatInt(used)}${unit}` : `${formatInt(used)}${unit} de ${formatInt(max)}${unit}`),
  );
}

export function budgetCard(detail: ReviewDetail): VElement {
  const budgets = detail.budgets;
  return h(
    "div",
    { class: "card stack" },
    h("h2", {}, "Orçamento usado"),
    budgetRow("Passos", detail.step_count, limit(budgets, "max_steps"), "", 1),
    budgetRow("Tokens", detail.tokens, limit(budgets, "max_tokens"), "", 0.9),
    budgetRow("Tempo", Math.round(detail.duration_s ?? 0), limit(budgets, "max_seconds"), " s", 0.9),
  );
}
