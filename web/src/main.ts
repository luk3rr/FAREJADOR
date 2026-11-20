// Filename: main.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The browser entry point: it wires the pure parts (router, theme, views) to the page. Everything
// that touches `window` or `document` lives here and in dom/render.ts.

import { createClient } from "./api/client.js";
import type { ApiError } from "./api/client.js";
import { view } from "./app.js";
import type { AppState, Loadable } from "./app.js";
import { DEFAULT_PERIOD, defaultPeriod } from "./screens/overview.js";
import type { OverviewState } from "./screens/overview.js";
import { mount } from "./dom/render.js";
import type { Container, DomElementLike, DomFactory } from "./dom/render.js";
import { formatRoute, parseHash } from "./router.js";
import type { Outcome } from "./router.js";
import { filtersFromForm } from "./screens/list-filters.js";
import { apiQuery } from "./screens/list-filters.js";
import { mergeItems } from "./screens/list.js";
import type { ListResult } from "./screens/list.js";
import type { DetailResult } from "./screens/detail.js";
import { loadTheme, saveTheme, toggleTheme } from "./theme.js";
import type { StorageLike } from "./theme.js";
import type { StatsOut, StatusOut } from "./api/types.js";

const factory: DomFactory = {
  createElement: (tag) => document.createElement(tag),
  createElementNS: (namespace, tag) => document.createElementNS(namespace, tag) as unknown as DomElementLike,
  createTextNode: (text) => document.createTextNode(text),
};

function storage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null; // blocked site data
  }
}

const client = createClient({ fetch: (url, init) => fetch(url, { signal: init.signal, credentials: "omit" }) });
const root = document.getElementById("app");

let theme = loadTheme(storage());
let route = parseHash(window.location.hash);
let status: Loadable<StatusOut> = { kind: "loading" };
let overview: OverviewState = { period: DEFAULT_PERIOD, stats: { kind: "loading" } };
let list: ListResult = { kind: "loading" };
let detail: DetailResult = { kind: "loading" };
let detailKey = 0;
let detailFlight: AbortController | null = null;
let listKey = "";
let formWarnings: readonly string[] = [];
let inFlight: AbortController | null = null;
let statsFlight: AbortController | null = null;
let listFlight: AbortController | null = null;

function state(): AppState {
  return { route, theme, status, overview, list: { result: list, now: new Date(), warnings: formWarnings }, detail };
}

function paint(): void {
  document.documentElement.dataset["theme"] = theme;
  if (root !== null) {
    mount(root as unknown as Container, view(state()), factory);
  }
}

async function loadStatus(): Promise<void> {
  inFlight?.abort();
  const controller = new AbortController();
  inFlight = controller;
  status = { kind: "loading" };
  paint();
  try {
    status = { kind: "ok", data: await client.status(controller.signal) };
  } catch (error) {
    if (controller.signal.aborted) {
      return; // a newer load replaced this one
    }
    status = { kind: "error", error: error as ApiError };
  }
  paint();
}

async function loadOverview(): Promise<void> {
  statsFlight?.abort();
  const controller = new AbortController();
  statsFlight = controller;
  overview = { ...overview, stats: { kind: "loading" } };
  paint();
  let stats: Loadable<StatsOut>;
  try {
    stats = { kind: "ok", data: await client.stats(overview.period, controller.signal) };
  } catch (error) {
    if (controller.signal.aborted) {
      return; // a newer load replaced this one
    }
    stats = { kind: "error", error: error as ApiError };
  }
  overview = { ...overview, stats };
  paint();
}

async function loadList(append: boolean): Promise<void> {
  if (route.name !== "list") {
    return;
  }
  const filters = route.filters;
  listFlight?.abort();
  const controller = new AbortController();
  listFlight = controller;
  const current = list;
  const cursor = append && current.kind === "ok" ? current.nextCursor : null;
  if (append && current.kind === "ok") {
    list = { ...current, more: { kind: "loading" } };
  } else {
    list = { kind: "loading" };
    listKey = formatRoute(route);
  }
  paint();
  try {
    const page = await client.reviews(apiQuery(filters, cursor), controller.signal);
    const previous = append && current.kind === "ok" ? current.items : [];
    list = { kind: "ok", items: mergeItems(previous, page.items), nextCursor: page.next_cursor, more: { kind: "idle" } };
  } catch (error) {
    if (controller.signal.aborted) {
      return; // a newer load replaced this one
    }
    list = append && current.kind === "ok" ? { ...current, more: { kind: "error", error: error as ApiError } } : { kind: "error", error: error as ApiError };
  }
  paint();
}

async function loadDetail(): Promise<void> {
  if (route.name !== "detail") {
    return;
  }
  const id = route.id;
  detailFlight?.abort();
  const controller = new AbortController();
  detailFlight = controller;
  detailKey = id;
  detail = { kind: "loading" };
  paint();
  try {
    detail = { kind: "ok", data: await client.review(id, controller.signal) };
  } catch (error) {
    if (controller.signal.aborted) {
      return; // a newer load replaced this one
    }
    const failure = error as ApiError;
    detail = failure.kind === "not_found" ? { kind: "notfound" } : { kind: "error", error: failure };
  }
  paint();
}

function enter(): void {
  route = parseHash(window.location.hash);
  if (route.name !== "list") {
    formWarnings = []; // the form's warnings belong to the list only
  }
  paint();
  if (route.name === "overview" && overview.stats.kind !== "ok") {
    void loadOverview();
  }
  if (route.name === "list" && formatRoute(route) !== listKey) {
    void loadList(false);
  }
  if (route.name === "detail" && (route.id !== detailKey || detail.kind === "error")) {
    void loadDetail();
  }
}

function field(id: string): string {
  const element = document.getElementById(id);
  return element instanceof HTMLInputElement ? element.value : "";
}

/** Read the filter form, validate it with the same rules as the address, and go there. */
function applyFilters(outcome?: Outcome | ""): void {
  const current = route.name === "list" ? route.filters.outcome ?? "" : "";
  const { filters, warnings } = filtersFromForm({
    repo: field("f-repo"),
    pr: field("f-pr"),
    since: field("f-since"),
    until: field("f-until"),
    outcome: outcome === undefined ? current : outcome,
  });
  formWarnings = warnings;
  goTo(formatRoute({ name: "list", filters, warnings: [] }));
}

function goTo(hash: string): void {
  if (window.location.hash === hash) {
    listKey = ""; // same address: reload instead of doing nothing
    enter();
  } else {
    window.location.hash = hash;
  }
}

window.addEventListener("hashchange", enter);

document.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target.closest("[data-action]") : null;
  const action = target?.getAttribute("data-action");
  if (action === "toggle-theme") {
    theme = toggleTheme(theme);
    saveTheme(storage(), theme);
    paint();
  } else if (action === "retry") {
    void loadStatus();
    if (route.name === "overview") {
      void loadOverview();
    }
    if (route.name === "list") {
      listKey = "";
      enter();
    }
    if (route.name === "detail") {
      detailKey = 0;
      enter();
    }
  } else if (action === "apply-filters") {
    applyFilters();
  } else if (action === "set-outcome") {
    const value = target?.getAttribute("data-value") ?? "";
    applyFilters(value === "complete" || value === "partial" || value === "failed" ? value : "");
  } else if (action === "clear-filters") {
    formWarnings = [];
    goTo("#/revisoes");
  } else if (action === "load-more") {
    void loadList(true);
  } else if (action === "open-review") {
    const id = Number(target?.getAttribute("data-id"));
    if (Number.isInteger(id) && id >= 1) {
      goTo(`#/revisoes/${id}`);
    }
  } else if (action === "refresh") {
    void loadOverview();
  } else if (action === "set-period") {
    const days = Number(target?.getAttribute("data-value"));
    if (Number.isInteger(days) && days >= 1 && days <= 365) {
      overview = { period: days, stats: { kind: "loading" } };
      void loadOverview();
    }
  }
});

document.addEventListener("keydown", (event) => {
  const target = event.target instanceof Element ? event.target.closest("[data-enter]") : null;
  if (event.key === "Enter" && target?.getAttribute("data-enter") === "apply-filters") {
    applyFilters();
  }
});

paint();
void loadStatus().then(() => {
  if (status.kind === "ok") {
    overview = { ...overview, period: defaultPeriod(status.data.retention_days) };
  }
  enter();
});
