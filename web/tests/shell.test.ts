// Filename: shell.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/api/client.js";
import type { StatusOut } from "../src/api/types.js";
import { statusFooter, view } from "../src/app.js";
import type { AppState } from "../src/app.js";
import { errorMessage } from "../src/components/states.js";
import { render } from "../src/dom/render.js";
import { findAll, textOf } from "../src/dom/vnode.js";
import { allText, fakeFactory } from "./fake-dom.js";
import type { FakeElement } from "./fake-dom.js";

const STATUS: StatusOut = {
  status: "ok",
  trace_available: true,
  retention_days: 30,
  reviews: 1280,
  app_version: "0.3.1",
  started_at: "2026-11-21T00:45:12Z",
};

function state(overrides: Partial<AppState> = {}): AppState {
  return {
    route: { name: "overview" },
    theme: "dark",
    status: { kind: "ok", data: STATUS },
    overview: { period: 30, stats: { kind: "loading" } },
    list: { result: { kind: "loading" }, now: new Date("2026-11-21T12:00:00Z"), warnings: [] },
    detail: { kind: "loading" },
    ...overrides,
  };
}

test("with the trace available the sidebar shows state, retention, scope and the count", () => {
  const text = textOf(view(state()));
  assert.match(text, /Trace disponível/);
  assert.match(text, /Retenção: 30 dias/);
  assert.match(text, /Somente repositórios públicos/);
  assert.match(text, /1\.280 revisões públicas/);
});

test("a trace reported as unavailable says so", () => {
  const text = textOf(statusFooter({ kind: "ok", data: { ...STATUS, trace_available: false } }));
  assert.match(text, /Trace indisponível/);
});

test("a failing status shows the API as unavailable, an error banner with retry, and keeps the navigation", () => {
  const tree = view(state({ status: { kind: "error", error: new ApiError("unavailable", 503) } }));
  assert.match(textOf(tree), /API indisponível/);
  const alerts = findAll(tree, (e) => e.attrs["role"] === "alert");
  assert.equal(alerts.length, 1);
  assert.match(textOf(alerts[0] ?? ""), /503/);
  const retry = findAll(tree, (e) => e.attrs["data-action"] === "retry");
  assert.equal(retry.length, 1);
  assert.equal(findAll(tree, (e) => e.tag === "a" && e.attrs["href"] === "#/revisoes").length, 1);
});

test("while the status loads there is a live region and no numbers", () => {
  const tree = view(state({ status: { kind: "loading" } }));
  assert.ok(findAll(tree, (e) => e.attrs["aria-live"] === "polite").length >= 1);
  assert.doesNotMatch(textOf(tree), /revisões públicas/);
});

test("the active navigation item is marked, and the detail screen belongs to Revisões", () => {
  const active = (route: AppState["route"]): string[] =>
    findAll(view(state({ route })), (e) => e.attrs["aria-current"] === "page").map(textOf);
  assert.deepEqual(active({ name: "overview" }), ["Visão geral"]);
  assert.deepEqual(active({ name: "list", filters: {}, warnings: [] }), ["Revisões"]);
  assert.deepEqual(active({ name: "detail", id: 7 }), ["Revisões"]);
  assert.deepEqual(active({ name: "notfound", path: "x" }), []);
});

test("an unknown address shows the not-found page with a way back", () => {
  const tree = view(state({ route: { name: "notfound", path: "<script>alert(1)</script>" } }));
  assert.match(textOf(tree), /Página não encontrada/);
  const back = findAll(tree, (e) => e.tag === "a" && e.attrs["href"] === "#/visao-geral" && e.attrs["class"] === "btn sm ghost");
  assert.equal(back.length, 1);
  assert.doesNotMatch(textOf(tree), /alert\(1\)/, "the unknown path is never echoed");
});

test("the theme button names the theme it would switch to", () => {
  const label = (theme: AppState["theme"]): string =>
    textOf(findAll(view(state({ theme })), (e) => e.attrs["data-action"] === "toggle-theme")[0] ?? "");
  assert.equal(label("dark"), "Tema claro");
  assert.equal(label("light"), "Tema escuro");
});

test("the whole shell renders with the safe renderer in every state (no forbidden attribute)", () => {
  const routes: AppState["route"][] = [
    { name: "overview" },
    { name: "list", filters: { repo: "o/r" }, warnings: [] },
    { name: "detail", id: 3 },
    { name: "notfound", path: "x" },
  ];
  const statuses: AppState["status"][] = [
    { kind: "loading" },
    { kind: "ok", data: STATUS },
    { kind: "error", error: new ApiError("timeout") },
  ];
  for (const route of routes) {
    for (const status of statuses) {
      for (const theme of ["dark", "light"] as const) {
        const overview = { period: 30, stats: { kind: "loading" } } as const;
        const list = { result: { kind: "loading" }, now: new Date(), warnings: [] } as const;
        const detail = { kind: "loading" } as const;
        const dom = render(view({ route, status, theme, overview, list, detail }), fakeFactory) as FakeElement;
        assert.ok(allText(dom).length > 0);
      }
    }
  }
});

test("the overview route shows the overview screen with the state it was given", () => {
  const tree = view(state({ overview: { period: 14, stats: { kind: "loading" } } }));
  assert.match(textOf(tree), /Visão geral/);
  assert.match(textOf(tree), /Últimos 14 dias/);
  assert.match(textOf(tree), /Calculando os números/);
});

test("the period options come from the retention reported by the API", () => {
  const short = view(state({ status: { kind: "ok", data: { ...STATUS, retention_days: 14 } } }));
  const buttons = findAll(short, (e) => e.attrs["data-action"] === "set-period").map((b) => b.attrs["data-value"]);
  assert.deepEqual(buttons, ["7", "14"]);
});

test("the detail route shows the detail screen with the state it was given", () => {
  const tree = view(state({ route: { name: "detail", id: 42 } }));
  assert.match(textOf(tree), /#42/);
  assert.match(textOf(tree), /Carregando a revisão/);
  const missing = view(state({ route: { name: "detail", id: 7 }, detail: { kind: "notfound" } }));
  assert.match(textOf(missing), /Não encontramos esta revisão/);
});

test("every error kind has a message in Portuguese", () => {
  const kinds = ["not_found", "invalid_parameter", "unavailable", "rate_limited", "timeout", "network", "aborted", "bad_response"] as const;
  for (const kind of kinds) {
    assert.ok(errorMessage(new ApiError(kind)).length > 10, kind);
  }
});


test("the footer says which release is running and since when", () => {
  const tree = statusFooter({ kind: "ok", data: STATUS });
  const text = textOf(tree);
  assert.match(text, /Versão 0\.3\.1/);
  assert.match(text, /No ar desde \d{2}\/\d{2}\/2026/);
  const since = findAll(tree, (e) => e.tag === "span" && textOf(e).startsWith("No ar desde"))[0];
  assert.equal(since?.attrs["title"], "2026-11-21T00:45:12Z", "the exact UTC time is one hover away");
});

test("a hostile version string is shown as text only", () => {
  const evil = '<img src=x onerror="alert(1)">';
  const tree = statusFooter({ kind: "ok", data: { ...STATUS, app_version: evil } });
  assert.ok(textOf(tree).includes(`Versão ${evil}`));
  assert.equal(findAll(tree, (e) => e.tag === "img").length, 0);
  assert.doesNotThrow(() => render(tree, fakeFactory));
});
