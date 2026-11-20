// Filename: overview.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The overview screen: four numbers, reviews per day, where the findings went, and a table by
// model and prompt version, all from GET /api/stats. A pure function of its state.

import type { ApiError } from "../api/client.js";
import type { StatsOut } from "../api/types.js";
import { barChart, destinationBar } from "../charts.js";
import { emptyState, errorBanner, loadingBlock } from "../components/states.js";
import { h } from "../dom/vnode.js";
import type { Child, VElement } from "../dom/vnode.js";
import { formatCompact, formatDuration, formatInt, formatPercent } from "../format.js";

export type Loadable<T> =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly error: ApiError }
  | { readonly kind: "ok"; readonly data: T };

export interface OverviewState {
  readonly period: number;
  readonly stats: Loadable<StatsOut>;
}

export const DEFAULT_PERIOD = 30;
const PERIODS: readonly number[] = [7, 14, 30, 90, 365];

/** 7, 14 and 30 days, plus longer ones only when the retention keeps that much (A-5). */
export function periodOptions(retentionDays: number | null): number[] {
  if (retentionDays === null) return [7, 14, 30];
  const options = PERIODS.filter((days) => days <= retentionDays);
  return options.length > 0 ? options : [Math.max(1, retentionDays)];
}

/** The period to start with: 30 days, or the longest one the retention allows. */
export function defaultPeriod(retentionDays: number | null): number {
  const options = periodOptions(retentionDays);
  return options.includes(DEFAULT_PERIOD) ? DEFAULT_PERIOD : (options[options.length - 1] ?? DEFAULT_PERIOD);
}

function periodPicker(period: number, options: readonly number[]): VElement {
  return h(
    "div",
    { class: "seg", role: "group", "aria-label": "Período" },
    options.map((days) =>
      h(
        "button",
        { class: days === period ? "chip on" : "chip", type: "button", "data-action": "set-period", "data-value": String(days), "aria-pressed": days === period },
        `${days} dias`,
      ),
    ),
  );
}

function kpi(label: string, value: Child, detail: string, tone = ""): VElement {
  return h(
    "div",
    { class: "card kpi" },
    h("div", { class: "l" }, label),
    h("div", { class: tone === "" ? "v" : `v ${tone}` }, value),
    h("div", { class: "d muted" }, detail),
  );
}

function modelTable(data: StatsOut): VElement {
  return h(
    "div",
    { class: "card scroll" },
    h("h2", {}, "Por modelo e versão do prompt"),
    h(
      "table",
      {},
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", { scope: "col" }, "Modelo"),
          h("th", { scope: "col" }, "Prompt"),
          h("th", { scope: "col", class: "num" }, "Revisões"),
          h("th", { scope: "col", class: "num" }, "Falhas"),
          h("th", { scope: "col", class: "num" }, "Tokens (média)"),
          h("th", { scope: "col", class: "num" }, "Duração (mediana)"),
          h("th", { scope: "col", class: "num" }, "Achados por revisão"),
        ),
      ),
      h(
        "tbody",
        {},
        data.by_model.map((row) =>
          h(
            "tr",
            {},
            h("td", { class: "mono" }, row.model),
            h("td", { class: "mono" }, row.prompt_version),
            h("td", { class: "num" }, formatInt(row.reviews)),
            h("td", { class: "num" }, formatInt(row.failed)),
            h("td", { class: "num" }, formatCompact(row.mean_tokens)),
            h("td", { class: "num" }, formatDuration(row.median_duration_s)),
            h("td", { class: "num" }, row.findings_per_review.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })),
          ),
        ),
      ),
    ),
  );
}

function dataView(data: StatsOut): VElement[] {
  const { totals } = data;
  return [
    ...(data.capped
      ? [h("div", { class: "banner", role: "status" }, "O período tem mais execuções do que o limite de cálculo; os números cobrem só as primeiras.")]
      : []),
    h(
      "div",
      { class: "kpis" },
      kpi("Revisões", formatInt(totals.reviews), "no período"),
      kpi("Falhas", [formatInt(totals.failed), " ", h("span", { class: "sub" }, formatPercent(totals.failure_rate))], `${formatInt(totals.partial)} parciais`, totals.failed > 0 ? "bad" : ""),
      kpi("Duração mediana", formatDuration(data.duration_s.median), `p95: ${formatDuration(data.duration_s.p95)}`),
      kpi("Tokens por revisão", formatCompact(data.tokens.mean), `mediana ${formatCompact(data.tokens.median)}`),
    ),
    h(
      "div",
      { class: "two" },
      h("div", { class: "card" }, h("h2", {}, "Revisões por dia"), barChart(data.by_day), h("p", { class: "hint" }, "Dias em UTC; cada barra são as revisões iniciadas naquele dia.")),
      h("div", { class: "card stack" }, h("h2", {}, "Para onde vão os achados"), destinationBar(data.findings), h("p", { class: "hint" }, "“No resumo”: o achado não pôde ser ancorado numa linha adicionada. “Descartados”: repetidos.")),
    ),
    data.by_model.length > 0 ? modelTable(data) : null,
  ].filter((node): node is VElement => node !== null);
}

export function overviewView(state: OverviewState, retentionDays: number | null): VElement {
  const options = periodOptions(retentionDays);
  const body: VElement[] =
    state.stats.kind === "loading"
      ? [loadingBlock("Calculando os números…")]
      : state.stats.kind === "error"
        ? [errorBanner(state.stats.error)]
        : state.stats.data.totals.reviews === 0
          ? [h("div", { class: "card" }, emptyState("Ainda não há revisões neste período.", "Abra um pull request em um repositório onde o Farejador está instalado e a primeira revisão aparece aqui."))]
          : dataView(state.stats.data);
  return h(
    "main",
    { class: "content" },
    h(
      "div",
      { class: "head" },
      h("h1", {}, "Visão geral"),
      h("div", { class: "chips" }, h("span", { class: "pill info" }, "Repositórios públicos"), h("span", { class: "pill" }, `Últimos ${state.period} dias`)),
    ),
    h(
      "div",
      { class: "cap" },
      periodPicker(state.period, options),
      h("span", { class: "hint" }, "Agregados do servidor, com cache de 60 s · ", h("button", { class: "btn sm ghost", type: "button", "data-action": "refresh" }, "Atualizar")),
    ),
    body,
  );
}
