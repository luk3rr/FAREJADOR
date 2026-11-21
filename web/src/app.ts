// Filename: app.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The shell of the dashboard as a pure function of its state: a sidebar with the navigation, the
// state of the trace and the theme switch, and the content of the current screen.

import type { StatusOut } from "./api/types.js";
import { errorBanner, loadingBlock, notFoundView } from "./components/states.js";
import { h } from "./dom/vnode.js";
import type { VElement } from "./dom/vnode.js";
import { formatDateTime } from "./format.js";
import type { Route } from "./router.js";
import { detailView } from "./screens/detail.js";
import type { DetailResult } from "./screens/detail.js";
import { listView } from "./screens/list.js";
import type { ListResult } from "./screens/list.js";
import type { Loadable, OverviewState } from "./screens/overview.js";
import { overviewView } from "./screens/overview.js";
import type { Theme } from "./theme.js";

export type { Loadable } from "./screens/overview.js";

export interface AppState {
  readonly route: Route;
  readonly theme: Theme;
  readonly status: Loadable<StatusOut>;
  readonly overview: OverviewState;
  readonly list: { readonly result: ListResult; readonly now: Date; readonly warnings: readonly string[] };
  readonly detail: DetailResult;
}

const NAV: readonly { readonly name: "overview" | "list"; readonly label: string; readonly href: string }[] = [
  { name: "overview", label: "Visão geral", href: "#/visao-geral" },
  { name: "list", label: "Revisões", href: "#/revisoes" },
];

function isActive(item: "overview" | "list", route: Route): boolean {
  return route.name === item || (item === "list" && route.name === "detail");
}

export function statusFooter(status: Loadable<StatusOut>): VElement {
  if (status.kind === "loading") {
    return h("div", { class: "foot", role: "status" }, h("span", {}, "Verificando o trace…"));
  }
  if (status.kind === "error") {
    return h(
      "div",
      { class: "foot", role: "status" },
      h("span", {}, h("i", { class: "dot bad" }), "API indisponível"),
    );
  }
  const { data } = status;
  return h(
    "div",
    { class: "foot", role: "status" },
    h("span", {}, h("i", { class: data.trace_available ? "dot" : "dot bad" }), data.trace_available ? "Trace disponível" : "Trace indisponível"),
    h("span", {}, `Retenção: ${data.retention_days} dias`),
    h("span", {}, "Somente repositórios públicos"),
    h("span", {}, `${data.reviews.toLocaleString("pt-BR")} revisões públicas`),
    h("span", {}, `Versão ${data.app_version}`),
    h("span", { title: data.started_at }, `No ar desde ${formatDateTime(data.started_at)}`),
  );
}

export function sidebar(state: AppState): VElement {
  return h(
    "nav",
    { class: "sidebar", "aria-label": "Navegação principal" },
    h("div", { class: "brand" }, h("img", { src: "/assets/icon.png", alt: "", width: 96, height: 96 }), h("span", {}, "Farejador")),
    NAV.map((item) =>
      h(
        "a",
        { class: isActive(item.name, state.route) ? "nav on" : "nav", href: item.href, ...(isActive(item.name, state.route) ? { "aria-current": "page" } : {}) },
        item.label,
      ),
    ),
    h("span", { class: "sp" }),
    h(
      "button",
      { class: "btn sm ghost theme", type: "button", "data-action": "toggle-theme" },
      state.theme === "dark" ? "Tema claro" : "Tema escuro",
    ),
    statusFooter(state.status),
  );
}

/** The content of the current screen. The data screens arrive in later Units; each is a pure view. */
export function content(state: AppState): VElement {
  const { route } = state;
  switch (route.name) {
    case "notfound":
      return h("main", { class: "content" }, notFoundView());
    case "overview":
      return overviewView(state.overview, state.status.kind === "ok" ? state.status.data.retention_days : null);
    case "list":
      return listView({ filters: route.filters, warnings: [...route.warnings, ...state.list.warnings], result: state.list.result, now: state.list.now });
    case "detail":
      return detailView({ id: route.id, result: state.detail });
  }
}

export function view(state: AppState): VElement {
  const banner =
    state.status.kind === "error" ? errorBanner(state.status.error) : state.status.kind === "loading" ? loadingBlock("Verificando o trace…") : null;
  const body = content(state);
  return h("div", { class: "app" }, sidebar(state), banner === null ? body : h("div", { class: "column" }, banner, body));
}
