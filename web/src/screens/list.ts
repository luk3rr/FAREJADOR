// Filename: list.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The list of reviews: filters, the table, "load more" by cursor, and the states. A pure function
// of its model; every piece of text from the API goes in as text.

import type { ApiError } from "../api/client.js";
import type { ReviewSummary } from "../api/types.js";
import { errorBanner, errorMessage, emptyState, loadingBlock } from "../components/states.js";
import { h } from "../dom/vnode.js";
import type { VElement } from "../dom/vnode.js";
import { formatCompact, formatDuration, formatInt, formatRelative } from "../format.js";
import type { ListFilters, Outcome } from "../router.js";
import { hasFilters } from "./list-filters.js";

export type MoreState =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly error: ApiError };

export type ListResult =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly error: ApiError }
  | {
      readonly kind: "ok";
      readonly items: readonly ReviewSummary[];
      readonly nextCursor: string | null;
      readonly more: MoreState;
    };

export interface ListModel {
  readonly filters: ListFilters;
  readonly warnings: readonly string[];
  readonly result: ListResult;
  readonly now: Date;
}

/** Append the new page without ever repeating a review that is already on the list. */
export function mergeItems(existing: readonly ReviewSummary[], incoming: readonly ReviewSummary[]): ReviewSummary[] {
  const seen = new Set(existing.map((item) => item.id));
  const merged = [...existing];
  for (const item of incoming) {
    if (!seen.has(item.id)) {
      seen.add(item.id);
      merged.push(item);
    }
  }
  return merged;
}

const OUTCOMES: readonly { readonly value: Outcome | ""; readonly label: string }[] = [
  { value: "", label: "Todos" },
  { value: "complete", label: "Concluída" },
  { value: "partial", label: "Parcial" },
  { value: "failed", label: "Falhou" },
];

const PILL: Readonly<Record<string, { readonly label: string; readonly tone: string }>> = {
  complete: { label: "Concluída", tone: "ok" },
  partial: { label: "Parcial", tone: "warn" },
  failed: { label: "Falhou", tone: "bad" },
};

const KIND: Readonly<Record<string, string>> = { review: "Revisão", command: "Comando" };

export function filterBar(filters: ListFilters): VElement {
  return h(
    "div",
    { class: "card" },
    h(
      "div",
      { class: "filters" },
      field("Repositório", h("input", { class: "f", id: "f-repo", type: "text", value: filters.repo ?? "", placeholder: "dono/nome", "aria-label": "Repositório", "data-enter": "apply-filters" })),
      field("PR", h("input", { class: "f narrow", id: "f-pr", type: "text", value: filters.pr === undefined ? "" : String(filters.pr), placeholder: "nº", "aria-label": "Número do PR", "data-enter": "apply-filters" })),
      field(
        "Resultado",
        h(
          "div",
          { class: "seg", role: "group", "aria-label": "Resultado" },
          OUTCOMES.map((option) =>
            h(
              "button",
              { class: (filters.outcome ?? "") === option.value ? "chip on" : "chip", type: "button", "data-action": "set-outcome", "data-value": option.value, "aria-pressed": (filters.outcome ?? "") === option.value },
              option.label,
            ),
          ),
        ),
      ),
      field("De", h("input", { class: "f", id: "f-since", type: "date", value: filters.since ?? "", "aria-label": "Data inicial", "data-enter": "apply-filters" })),
      field("Até", h("input", { class: "f", id: "f-until", type: "date", value: filters.until ?? "", "aria-label": "Data final", "data-enter": "apply-filters" })),
      h("button", { class: "btn sm", type: "button", "data-action": "apply-filters" }, "Filtrar"),
      h("button", { class: "btn sm ghost", type: "button", "data-action": "clear-filters" }, "Limpar"),
    ),
  );
}

function field(label: string, control: VElement): VElement {
  return h("div", { class: "field" }, h("span", { class: "lbl" }, label), control);
}

function destination(item: ReviewSummary): VElement {
  return h(
    "span",
    { class: "mono", title: "no código · no resumo · descartados" },
    h("span", { class: "inline" }, String(item.findings_inline)),
    " · ",
    h("span", { class: "summary" }, String(item.findings_summary)),
    " · ",
    h("span", { class: "dropped" }, String(item.findings_dropped)),
  );
}

function row(item: ReviewSummary, now: Date): VElement {
  const pill = PILL[item.outcome] ?? { label: item.outcome, tone: "" };
  return h(
    "tr",
    { class: "click", "data-action": "open-review", "data-id": String(item.id) },
    h("td", { class: "mono" }, h("a", { href: `#/revisoes/${item.id}` }, `#${item.id}`)),
    h("td", {}, h("b", {}, item.repo), " ", h("span", { class: "muted" }, `#${item.pr_number}`)),
    h("td", {}, KIND[item.kind] ?? item.kind),
    h("td", {}, h("span", { class: pill.tone === "" ? "pill" : `pill ${pill.tone}` }, pill.label)),
    h("td", { class: "mono" }, item.model),
    h("td", { class: "num" }, formatInt(item.step_count)),
    h("td", { class: "num" }, formatCompact(item.tokens)),
    h("td", { class: "num" }, formatDuration(item.duration_s)),
    h("td", {}, destination(item)),
    h("td", { class: "muted", title: item.started_at }, formatRelative(item.started_at, now)),
  );
}

function table(items: readonly ReviewSummary[], nextCursor: string | null, more: MoreState, now: Date): VElement {
  return h(
    "div",
    { class: "card scroll" },
    h(
      "table",
      {},
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", { scope: "col" }, "ID"),
          h("th", { scope: "col" }, "Repositório · PR"),
          h("th", { scope: "col" }, "Tipo"),
          h("th", { scope: "col" }, "Resultado"),
          h("th", { scope: "col" }, "Modelo"),
          h("th", { scope: "col", class: "num" }, "Passos"),
          h("th", { scope: "col", class: "num" }, "Tokens"),
          h("th", { scope: "col", class: "num" }, "Duração"),
          h("th", { scope: "col", title: "no código · no resumo · descartados" }, "Achados"),
          h("th", { scope: "col" }, "Quando"),
        ),
      ),
      h("tbody", {}, items.map((item) => row(item, now))),
    ),
    h(
      "div",
      { class: "tablefoot" },
      h("span", { class: "hint" }, `Mostrando ${formatInt(items.length)} · cada linha abre o detalhe`),
      nextCursor !== null
        ? h("button", { class: "btn sm ghost", type: "button", "data-action": "load-more", disabled: more.kind === "loading" }, more.kind === "loading" ? "Carregando…" : "Carregar mais")
        : h("span", { class: "hint" }, "Fim da lista"),
    ),
    more.kind === "error"
      ? h("div", { class: "banner bad", role: "alert" }, errorMessage(more.error), " ", h("button", { class: "btn sm ghost", type: "button", "data-action": "load-more" }, "Tentar de novo"))
      : null,
  );
}

export function emptyList(filters: ListFilters): VElement {
  return h(
    "div",
    { class: "card" },
    hasFilters(filters)
      ? h("div", { class: "empty" }, h("b", {}, "Nenhuma revisão com esses filtros."), h("p", { class: "muted" }, "Tente outros valores ou limpe os filtros."), h("button", { class: "btn sm ghost", type: "button", "data-action": "clear-filters" }, "Limpar filtros"))
      : emptyState("Ainda não há revisões.", "Abra um pull request em um repositório onde o Farejador está instalado e a primeira revisão aparece aqui."),
  );
}

export function listView(model: ListModel): VElement {
  const { filters, warnings, result, now } = model;
  const body =
    result.kind === "loading"
      ? loadingBlock("Carregando as revisões…")
      : result.kind === "error"
        ? errorBanner(result.error)
        : result.items.length === 0
          ? emptyList(filters)
          : table(result.items, result.nextCursor, result.more, now);
  return h(
    "main",
    { class: "content" },
    h(
      "div",
      { class: "head" },
      h("h1", {}, "Revisões"),
      h("div", { class: "chips" }, h("span", { class: "pill info" }, "Repositórios públicos")),
    ),
    warnings.map((warning) => h("div", { class: "banner info", role: "status" }, warning)),
    filterBar(filters),
    body,
  );
}
