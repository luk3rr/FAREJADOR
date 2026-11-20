// Filename: list.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/api/client.js";
import type { ReviewSummary } from "../src/api/types.js";
import { render } from "../src/dom/render.js";
import { findAll, textOf } from "../src/dom/vnode.js";
import { listView, mergeItems } from "../src/screens/list.js";
import type { ListModel, ListResult } from "../src/screens/list.js";
import { allText, fakeFactory } from "./fake-dom.js";
import type { FakeElement } from "./fake-dom.js";

const NOW = new Date("2026-11-21T12:00:00Z");
const plain = (text: string): string => text.replace(/ | /g, " ");

function item(id: number, overrides: Partial<ReviewSummary> = {}): ReviewSummary {
  return {
    id,
    repo: "luk3rr/FAREJADOR_PILOT",
    pr_number: 4,
    head_sha: "a".repeat(40),
    kind: "review",
    model: "provedor/modelo-a",
    prompt_version: "2026-11-21.2",
    app_version: "0.2.0",
    outcome: "complete",
    step_count: 4,
    tokens: 21350,
    duration_s: 52.1,
    findings_inline: 3,
    findings_summary: 1,
    findings_dropped: 0,
    error_category: null,
    started_at: "2026-11-21T11:48:00Z",
    ...overrides,
  };
}

function model(result: ListResult, overrides: Partial<ListModel> = {}): ListModel {
  return { filters: {}, warnings: [], result, now: NOW, ...overrides };
}

const okResult = (items: ReviewSummary[], nextCursor: string | null = null): ListResult => ({
  kind: "ok",
  items,
  nextCursor,
  more: { kind: "idle" },
});

test("a row has every column of the mockup, with the id as a real link", () => {
  const view = listView(model(okResult([item(57)])));
  const headers = findAll(view, (e) => e.tag === "th").map(textOf);
  assert.deepEqual(headers, ["ID", "Repositório · PR", "Tipo", "Resultado", "Modelo", "Passos", "Tokens", "Duração", "Achados", "Quando"]);
  const text = plain(textOf(findAll(view, (e) => e.tag === "tbody")[0] ?? ""));
  assert.match(text, /#57luk3rr\/FAREJADOR_PILOT #4Revisão.*Concluída.*provedor\/modelo-a421,4 mil52 s3 · 1 · 0há 12 min/);
  const links = findAll(view, (e) => e.tag === "a" && String(e.attrs["href"]).startsWith("#/revisoes/"));
  assert.equal(links.length, 1);
  assert.equal(links[0]?.attrs["href"], "#/revisoes/57");
});

test("each row can be opened with the mouse or the keyboard", () => {
  const view = listView(model(okResult([item(1), item(2)])));
  const rows = findAll(view, (e) => e.attrs["data-action"] === "open-review");
  assert.deepEqual(rows.map((r) => r.attrs["data-id"]), ["1", "2"]);
});

test("the result pill and the kind use the words of the mockup", () => {
  const view = listView(
    model(okResult([item(1, { outcome: "failed", kind: "command" }), item(2, { outcome: "partial" }), item(3, { outcome: "weird" })])),
  );
  const pills = findAll(view, (e) => String(e.attrs["class"]).startsWith("pill") && e.tag === "span" && e.attrs["class"] !== "pill info").map((e) => [e.attrs["class"], textOf(e)]);
  assert.deepEqual(pills, [["pill bad", "Falhou"], ["pill warn", "Parcial"], ["pill", "weird"]]);
  assert.match(textOf(view), /Comando/);
});

test("the time shows how long ago and keeps the exact UTC time in the title", () => {
  const cell = findAll(listView(model(okResult([item(1)]))), (e) => e.attrs["title"] === "2026-11-21T11:48:00Z")[0];
  assert.equal(textOf(cell ?? ""), "há 12 min");
});

test("filters show their current values and the active result is marked", () => {
  const view = listView(model(okResult([]), { filters: { repo: "o/r", pr: 9, outcome: "failed", since: "2026-11-01", until: "2026-11-30" } }));
  const inputs = findAll(view, (e) => e.tag === "input");
  assert.deepEqual(inputs.map((i) => [i.attrs["id"], i.attrs["value"]]), [["f-repo", "o/r"], ["f-pr", "9"], ["f-since", "2026-11-01"], ["f-until", "2026-11-30"]]);
  const chips = findAll(view, (e) => e.attrs["data-action"] === "set-outcome");
  assert.deepEqual(chips.map((c) => [c.attrs["data-value"], c.attrs["aria-pressed"]]), [["", false], ["complete", false], ["partial", false], ["failed", true]]);
  assert.ok(inputs.every((i) => i.attrs["data-enter"] === "apply-filters"));
});

test("with no filters 'Todos' is the marked result", () => {
  const chips = findAll(listView(model(okResult([]))), (e) => e.attrs["data-action"] === "set-outcome");
  assert.equal(chips[0]?.attrs["aria-pressed"], true);
});

test("load more shows while there is a next page, and says the list ended otherwise", () => {
  const more = listView(model(okResult([item(1)], "cursor")));
  assert.equal(findAll(more, (e) => e.attrs["data-action"] === "load-more").length, 1);
  assert.doesNotMatch(textOf(more), /Fim da lista/);
  const end = listView(model(okResult([item(1)], null)));
  assert.equal(findAll(end, (e) => e.attrs["data-action"] === "load-more").length, 0);
  assert.match(textOf(end), /Fim da lista/);
  assert.match(plain(textOf(end)), /Mostrando 1/);
});

test("while the next page loads the button is disabled and says so", () => {
  const view = listView(model({ kind: "ok", items: [item(1)], nextCursor: "c", more: { kind: "loading" } }));
  const button = findAll(view, (e) => e.attrs["data-action"] === "load-more")[0];
  assert.equal(button?.attrs["disabled"], true);
  assert.equal(textOf(button ?? ""), "Carregando…");
});

test("a failure loading the next page keeps the rows and offers a retry", () => {
  const view = listView(model({ kind: "ok", items: [item(1), item(2)], nextCursor: "c", more: { kind: "error", error: new ApiError("rate_limited", 429) } }));
  assert.equal(findAll(view, (e) => e.tag === "tr" && e.attrs["data-action"] === "open-review").length, 2);
  const alerts = findAll(view, (e) => e.attrs["role"] === "alert");
  assert.equal(alerts.length, 1);
  assert.match(textOf(alerts[0] ?? ""), /Muitas requisições/);
  assert.ok(findAll(alerts[0] ?? "", (e) => e.attrs["data-action"] === "load-more").length === 1);
});

test("merging a new page never repeats a review that is already there", () => {
  const merged = mergeItems([item(3), item(2)], [item(2), item(1)]);
  assert.deepEqual(merged.map((i) => i.id), [3, 2, 1]);
  assert.deepEqual(mergeItems([], [item(1), item(1)]).map((i) => i.id), [1]);
  const thirty = Array.from({ length: 30 }, (_, i) => item(30 - i));
  const twice = mergeItems(mergeItems([], thirty.slice(0, 20)), thirty.slice(15));
  assert.deepEqual(twice.map((i) => i.id), thirty.map((i) => i.id));
});

test("loading and error states keep the filters and the header", () => {
  const loading = listView(model({ kind: "loading" }, { filters: { repo: "o/r" } }));
  assert.ok(findAll(loading, (e) => e.attrs["role"] === "status").length >= 1);
  assert.equal(findAll(loading, (e) => e.attrs["id"] === "f-repo").length, 1);
  const failed = listView(model({ kind: "error", error: new ApiError("unavailable", 503) }));
  assert.equal(findAll(failed, (e) => e.attrs["role"] === "alert").length, 1);
  assert.equal(findAll(failed, (e) => e.attrs["data-action"] === "retry").length, 1);
});

test("an empty list says the same thing for any filter and never mentions private repositories", () => {
  const filters = [{ repo: "acme/secret" }, { pr: 5 }, { outcome: "failed" as const }, { repo: "x/y", pr: 2 }];
  const texts = new Set(filters.map((f) => textOf(listView(model(okResult([]), { filters: f })))));
  const bodies = [...texts].map((text) => text.slice(text.indexOf("Nenhuma")));
  assert.equal(new Set(bodies.map((b) => b.replace(/Limpar.*/, ""))).size, 1);
  for (const text of texts) {
    assert.match(text, /Nenhuma revisão com esses filtros\./);
    assert.doesNotMatch(text, /privad|acesso|permiss|existe/i);
  }
  assert.doesNotMatch(textOf(listView(model(okResult([]), { filters: { repo: "acme/secret" } }))), /acme\/secret.*acme\/secret/s);
});

test("with no filters and no reviews it is the first-run message instead", () => {
  const text = textOf(listView(model(okResult([]))));
  assert.match(text, /Ainda não há revisões/);
  assert.doesNotMatch(text, /esses filtros/);
});

test("warnings about ignored filters are shown", () => {
  const view = listView(model(okResult([]), { warnings: ["O filtro de PR é inválido e foi ignorado."] }));
  assert.match(textOf(view), /O filtro de PR é inválido/);
  assert.equal(findAll(view, (e) => e.attrs["role"] === "status" && String(e.attrs["class"]).includes("banner")).length, 1);
});

test("hostile text in every field of a row stays text and builds no link", () => {
  const evil = '<img src=x onerror="alert(1)">';
  const row = item(9, { repo: evil, model: "</td><script>alert(1)</script>", prompt_version: evil, outcome: evil, kind: evil });
  const view = listView(model(okResult([row])));
  const dom = render(view, fakeFactory) as FakeElement;
  assert.ok(allText(dom).includes(evil));
  assert.equal(findAll(view, (e) => (e.tag as string) === "img" || (e.tag as string) === "script").length, 0);
  assert.equal(findAll(view, (e) => e.tag === "a").length, 1, "only the id link, built from a number");
});

test("the whole screen goes through the safe renderer in every state", () => {
  const results: ListResult[] = [
    { kind: "loading" },
    { kind: "error", error: new ApiError("timeout") },
    okResult([]),
    okResult([item(1), item(2, { outcome: "failed", duration_s: null })], "c"),
    { kind: "ok", items: [item(1)], nextCursor: "c", more: { kind: "loading" } },
    { kind: "ok", items: [item(1)], nextCursor: "c", more: { kind: "error", error: new ApiError("network") } },
  ];
  for (const result of results) {
    for (const filters of [{}, { repo: "o/r", pr: 1, outcome: "partial" as const, since: "2026-11-01", until: "2026-11-30" }]) {
      assert.doesNotThrow(() => render(listView(model(result, { filters })), fakeFactory));
    }
  }
});

test("a page of 200 rows builds quickly", () => {
  const rows = Array.from({ length: 200 }, (_, i) => item(i + 1));
  const started = performance.now();
  render(listView(model(okResult(rows, "c"))), fakeFactory);
  assert.ok(performance.now() - started < 100, "must stay under 100 ms");
});
