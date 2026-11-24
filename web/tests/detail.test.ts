// Filename: detail.test.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/api/client.js";
import type { FindingOut, ReviewDetail, StepOut } from "../src/api/types.js";
import { render } from "../src/dom/render.js";
import { findAll, textOf } from "../src/dom/vnode.js";
import type { VElement } from "../src/dom/vnode.js";
import { budgetCard, statusBanners } from "../src/screens/detail-banners.js";
import { detailHeader, pullRequestUrl } from "../src/screens/detail-header.js";
import { detailView } from "../src/screens/detail.js";
import type { DetailResult } from "../src/screens/detail.js";
import { findingsCard } from "../src/screens/findings.js";
import { stepCard, timelineCard } from "../src/screens/timeline.js";
import { FINDINGS, STEP_ONE, STEP_TWO, detail } from "./detail-fixtures.js";
import { allElements, allText, fakeFactory } from "./fake-dom.js";
import type { FakeElement } from "./fake-dom.js";

const ok = (data: ReviewDetail = detail()): DetailResult => ({ kind: "ok", data });
const plain = (text: string): string => text.replace(/ | /g, " ");

// -- the link to the pull request ----------------------------------------------------------------

test("the pull request link is built only from a plain repository name and a number", () => {
  assert.equal(pullRequestUrl("luk3rr/FAREJADOR_PILOT", 1), "https://github.com/luk3rr/FAREJADOR_PILOT/pull/1");
  assert.equal(pullRequestUrl("a.b-c_d/e.f", 999_999_999), "https://github.com/a.b-c_d/e.f/pull/999999999");
  const badRepos = ["", "a", "a/b/c", "../x", "a/..", "a/b/..", ".hidden/x", "x/.hidden", "<script>/x", "a b/c", "a/b c", "a/b?x=1", "a/b#x", "ü/x", "a/b\n", "/".repeat(3), "a//b", "http://evil/x", "x".repeat(101) + "/y"];
  for (const repo of badRepos) {
    assert.equal(pullRequestUrl(repo, 1), null, JSON.stringify(repo));
  }
  for (const number of [0, -1, 1.5, Number.NaN, Infinity, 1_000_000_000, 1e12]) {
    assert.equal(pullRequestUrl("o/r", number), null, String(number));
  }
});

test("the header shows the origin and links to GitHub safely", () => {
  const view = detailHeader(detail());
  const links = findAll(view, (e) => e.tag === "a");
  assert.equal(links.length, 1);
  assert.deepEqual([links[0]?.attrs["href"], links[0]?.attrs["target"], links[0]?.attrs["rel"]], ["https://github.com/luk3rr/FAREJADOR_PILOT/pull/1", "_blank", "noopener noreferrer"]);
  const text = textOf(view);
  assert.match(text, /luk3rr\/FAREJADOR_PILOT #1/);
  assert.match(text, /368f961/);
  assert.doesNotMatch(text, /368f9610/);
  assert.match(text, /provedor\/modelo-a/);
  assert.match(text, /2026-11-21\.2/);
  assert.match(text, /0\.2\.0/);
  assert.match(plain(text), /Duração.*42 s/);
});

test("a repository that is not plain gets no link at all", () => {
  const view = detailHeader(detail({ repo: '<img src=x onerror="alert(1)">/r', head_sha: null }));
  assert.equal(findAll(view, (e) => e.tag === "a").length, 0);
  assert.match(textOf(view), /—/, "a missing commit shows a dash");
});

test("the outcome and the kind are shown as pills", () => {
  const pills = (view: VElement): string[] => findAll(view, (e) => String(e.attrs["class"]).startsWith("pill")).map((e) => `${e.attrs["class"]}:${textOf(e)}`);
  assert.deepEqual(pills(detailHeader(detail({ outcome: "failed", kind: "command" }))), ["pill bad:Falhou", "pill:Comando"]);
  assert.deepEqual(pills(detailHeader(detail({ outcome: "partial" }))), ["pill warn:Parcial", "pill:Revisão"]);
});

// -- the banners and the budget ------------------------------------------------------------------

test("a failed review explains the category and the message", () => {
  const banners = statusBanners(detail({ outcome: "failed", error: { category: "model_api", message: "model API returned HTTP 429" } }));
  assert.equal(banners.length, 1);
  assert.equal(banners[0]?.attrs["role"], "alert");
  assert.match(textOf(banners[0] ?? ""), /Falhou · model_api — model API returned HTTP 429/);
});

test("an internal failure shows the hidden-details text the API sends", () => {
  const banners = statusBanners(detail({ outcome: "failed", error: { category: "github_api", message: "detalhes omitidos" } }));
  assert.match(textOf(banners[0] ?? ""), /github_api — detalhes omitidos/);
});

test("a failure without error data and a partial run say what they can", () => {
  assert.match(textOf(statusBanners(detail({ outcome: "failed", error: null }))[0] ?? ""), /Não há detalhes do erro/);
  assert.match(textOf(statusBanners(detail({ outcome: "partial", error: { category: "budget", message: "limite de passos atingido." } }))[0] ?? ""), /Parcial · budget — limite de passos atingido/);
  assert.match(textOf(statusBanners(detail({ outcome: "partial", error: null }))[0] ?? ""), /não terminou normalmente/);
});

test("cut text gets its own notice, and a clean complete review has no banner", () => {
  const cut = statusBanners(detail({ truncated: true }));
  assert.equal(cut.length, 1);
  assert.match(textOf(cut[0] ?? ""), /\[…cortado: N caracteres no original\]/);
  assert.equal(statusBanners(detail()).length, 0);
  assert.equal(statusBanners(detail({ outcome: "failed", truncated: true, error: null })).length, 2);
});

test("the budget compares what was used with each limit", () => {
  const card = budgetCard(detail());
  const text = plain(textOf(card));
  assert.match(text, /Passos3 de 15/);
  assert.match(text, /Tokens18\.452 de 200\.000/);
  assert.match(text, /Tempo42 s de 300 s/);
  const widths = findAll(card, (e) => e.tag === "i").map((i) => i.vars["--w"]);
  assert.deepEqual(widths, ["20.0%", "9.2%", "14.0%"]);
});

test("a budget that was used up is capped at 100% and marked as warm", () => {
  const card = budgetCard(detail({ step_count: 15, tokens: 500_000, budgets: { max_steps: 15, max_tokens: 200000, max_seconds: 300 } }));
  const bars = findAll(card, (e) => String(e.attrs["class"]).startsWith("bar"));
  assert.deepEqual(bars.map((b) => b.attrs["class"]), ["bar warn", "bar warn", "bar"]);
  assert.deepEqual(findAll(card, (e) => e.tag === "i").map((i) => i.vars["--w"]), ["100.0%", "100.0%", "14.0%"]);
});

test("a missing or odd limit shows only the value, with no filled bar", () => {
  for (const budgets of [{}, { max_steps: "<script>", max_tokens: 0, max_seconds: -5 }, { max_steps: null }]) {
    const card = budgetCard(detail({ budgets }));
    assert.deepEqual(findAll(card, (e) => e.tag === "i").map((i) => i.vars["--w"]), ["0.0%", "0.0%", "0.0%"]);
    assert.doesNotMatch(textOf(card), / de /);
  }
  assert.match(textOf(budgetCard(detail({ duration_s: null }))), /0 s de 300 s/);
});

// -- the timeline --------------------------------------------------------------------------------

test("each step is a card with its time, tokens and the collapsed input", () => {
  const card = stepCard(STEP_ONE);
  assert.match(plain(textOf(card)), /Passo 13,2 s · 4\.100 tokens/);
  const input = findAll(card, (e) => e.tag === "details")[0];
  assert.equal(input?.attrs["open"], false, "the input starts collapsed");
  assert.match(textOf(input ?? ""), /Entrada · 2 mensagens/);
  assert.match(textOf(input ?? ""), /SistemaVocê é o Farejador/);
  assert.match(textOf(input ?? ""), /Usuário/);
});

test("the reasoning is open and in its own block, or says it is not available", () => {
  const think = findAll(stepCard(STEP_ONE), (e) => e.tag === "details" && e.attrs["class"] === "blk think");
  assert.equal(think.length, 1);
  assert.equal(think[0]?.attrs["open"], true);
  assert.match(textOf(think[0] ?? ""), /O diff adiciona `value = normalize\(None\)`/);
  assert.match(textOf(stepCard(STEP_TWO)), /Raciocínio indisponível neste provedor/);
  assert.match(textOf(stepCard({ ...STEP_TWO, response: { ...STEP_TWO.response, reasoning: "   " } })), /indisponível neste provedor/);
});

test("a tool call shows its name and arguments and, collapsed, its matching result", () => {
  const card = stepCard(STEP_ONE);
  assert.match(textOf(card), /read_file\(\{"path": "a\.py"\}\)/);
  const result = findAll(card, (e) => e.tag === "details" && textOf(e).startsWith("Resultado"))[0];
  assert.equal(result?.attrs["open"], false);
  assert.match(textOf(result ?? ""), /Resultado · 38 caracteresdef normalize/);
  assert.doesNotMatch(textOf(result ?? ""), /cortado/);
});

test("a cut result says so and keeps the size of the original", () => {
  const step: StepOut = { ...STEP_ONE, tool_results: [{ call_id: "c1", name: "read_file", duration_s: 0.5, content: "início…[…cortado: 48210 caracteres no original]", truncated: true, original_chars: 48210 }] };
  const text = plain(textOf(stepCard(step)));
  assert.match(text, /Resultado · 48\.210 caracteres cortado/);
  assert.match(text, /\[…cortado: 48210 caracteres no original\]/);
});

test("the step that submits the review is marked as the final answer", () => {
  const card = stepCard(STEP_TWO);
  assert.equal(card.attrs["class"], "step final");
  assert.match(textOf(card), /resposta final/);
  assert.equal(stepCard(STEP_ONE).attrs["class"], "step");
});

test("a call without a result and a result without a call are both harmless", () => {
  const lone: StepOut = { ...STEP_ONE, tool_results: [] };
  assert.equal(findAll(stepCard(lone), (e) => e.tag === "details" && textOf(e).startsWith("Resultado")).length, 0);
  const stray: StepOut = { ...STEP_ONE, response: { ...STEP_ONE.response, tool_calls: [] } };
  assert.doesNotMatch(textOf(stepCard(stray)), /def normalize/);
});

test("the model's text answer is its own block", () => {
  assert.match(textOf(stepCard(STEP_ONE)), /Resposta do modelo/);
  assert.match(textOf(stepCard(STEP_ONE)), /Vou ler o arquivo\./);
  assert.doesNotMatch(textOf(stepCard(STEP_TWO)), /Resposta do modelo/);
});

test("a review with no steps says why", () => {
  assert.match(textOf(timelineCard([])), /Nenhum passo foi registrado/);
  assert.equal(findAll(timelineCard([STEP_ONE, STEP_TWO]), (e) => String(e.attrs["class"]).startsWith("step")).length, 2);
});

// -- the findings --------------------------------------------------------------------------------

test("each finding shows where it went, why, where it is and how serious", () => {
  const card = findingsCard(FINDINGS);
  assert.match(textOf(card), /Achados do modelo \(3\)/);
  const text = textOf(card);
  assert.match(text, /No códigob\.py:2média · tratamento de erros/);
  assert.match(text, /Geraisa linha não foi adicionada pelo PRb\.py:3baixa · legibilidade/);
  assert.match(text, /Descartadorepetidob\.py:2/);
  const diffs = findAll(card, (e) => e.tag === "pre").map(textOf);
  assert.deepEqual(diffs, ['-value = normalize(None)\n+value = normalize(texto or "")']);
});

test("rationale and suggestion are collapsed and only there when they exist", () => {
  const card = findingsCard(FINDINGS);
  const blocks = findAll(card, (e) => e.tag === "details");
  assert.equal(blocks.length, 1);
  assert.notEqual(blocks[0]?.attrs["open"], true, "collapsed by default");
  assert.match(textOf(blocks[0] ?? ""), /strip\(\) não existe em None\.Proteja a chamada\./);
});

test("a suggested diff that did not match the code is reported", () => {
  const text = textOf(findingsCard(FINDINGS));
  assert.match(text, /O diff sugerido não bateu com o código do PR/);
});

test("unknown codes are shown as they came, as text", () => {
  const odd: FindingOut = { ...FINDINGS[0]!, severity: "catastrophic", category: "vibes", disposition: "mystery", reason: "because" };
  const text = textOf(findingsCard([odd]));
  assert.match(text, /mystery/);
  assert.match(text, /because/);
  assert.match(text, /catastrophic · vibes/);
});

test("no findings is stated plainly", () => {
  assert.match(textOf(findingsCard([])), /Achados do modelo \(0\)/);
  assert.match(textOf(findingsCard([])), /não devolveu achados/);
});

// -- the whole screen ----------------------------------------------------------------------------

test("a complete review shows every section in order", () => {
  const view = detailView({ id: 42, result: ok() });
  const headings = findAll(view, (e) => e.tag === "h2").map(textOf);
  assert.deepEqual(headings, ["Orçamento usado", "Linha do tempo do raciocínio", "Achados do modelo (3)"]);
  assert.equal(findAll(view, (e) => e.tag === "h1").length, 1);
  assert.equal(findAll(view, (e) => e.tag === "nav" && e.attrs["aria-label"] === "Você está em").length, 1);
});

test("a failed review with no findings does not show an empty findings card", () => {
  const view = detailView({ id: 55, result: ok(detail({ id: 55, outcome: "failed", steps: [], findings: [], error: { category: "model_api", message: "x" } })) });
  assert.doesNotMatch(textOf(view), /Achados do modelo/);
  assert.match(textOf(view), /Nenhum passo foi registrado/);
  const withFindings = detailView({ id: 55, result: ok(detail({ outcome: "failed", error: null })) });
  assert.match(textOf(withFindings), /Achados do modelo/);
});

test("loading shows a live region", () => {
  const view = detailView({ id: 42, result: { kind: "loading" } });
  assert.ok(findAll(view, (e) => e.attrs["role"] === "status").length >= 1);
  assert.match(textOf(view), /#42/);
});

test("an error offers a retry", () => {
  const view = detailView({ id: 42, result: { kind: "error", error: new ApiError("unavailable", 503) } });
  assert.equal(findAll(view, (e) => e.attrs["role"] === "alert").length, 1);
  assert.equal(findAll(view, (e) => e.attrs["data-action"] === "retry").length, 1);
});

test("not found is neutral: it never says private, access or permission", () => {
  const text = textOf(detailView({ id: 9999, result: { kind: "notfound" } }));
  assert.match(text, /Não encontramos esta revisão\./);
  assert.match(text, /Ela pode ter expirado/);
  assert.doesNotMatch(text, /privad|acesso|permiss|repositório|existe/i);
  const links = findAll(detailView({ id: 9999, result: { kind: "notfound" } }), (e) => e.tag === "a").map((e) => e.attrs["href"]);
  assert.deepEqual(links, ["#/revisoes", "#/revisoes"]);
});

test("hostile text in EVERY text field of the API stays text, builds no element and no link", () => {
  const evil = (label: string): string => `<img src=x onerror="alert('${label}')"><script>alert('${label}')</script>`;
  const hostileStep: StepOut = {
    index: 0,
    started_at: evil("started"),
    duration_s: 1,
    tokens: 1,
    input_messages: [{ role: evil("role"), content: evil("content"), tool_call_id: evil("tcid") }],
    response: { content: evil("response"), reasoning: evil("reasoning"), tool_calls: [{ id: evil("id"), name: evil("name"), arguments: evil("args") }] },
    tool_results: [{ call_id: evil("id"), name: evil("rname"), duration_s: 1, content: evil("result"), truncated: true, original_chars: 5 }],
  };
  const hostileFinding: FindingOut = {
    path: evil("path"), line: 1, severity: evil("sev"), category: evil("cat"), problem: evil("problem"), rationale: evil("rationale"),
    suggestion: evil("suggestion"), suggestion_diff: evil("diff"), diff_dropped: true, disposition: evil("disp"), reason: evil("reason"),
  };
  const hostile = detail({
    repo: evil("repo"), head_sha: evil("sha"), kind: evil("kind"), model: evil("model"), prompt_version: evil("prompt"),
    app_version: evil("app"), outcome: evil("outcome"), started_at: evil("start"),
    budgets: { max_steps: evil("steps") as unknown as number, max_tokens: "x" as unknown as number },
    steps: [hostileStep], findings: [hostileFinding], error: { category: evil("ecat"), message: evil("emsg") },
  });
  for (const outcome of [evil("outcome"), "failed", "partial", "complete"]) {
    const view = detailView({ id: 1, result: ok({ ...hostile, outcome, truncated: true }) });
    const dom = render(view, fakeFactory) as FakeElement;
    const tags = new Set(allElements(dom).map((e) => e.tag));
    for (const tag of ["script", "img", "iframe", "style", "link", "object", "embed"]) {
      assert.equal(tags.has(tag), false, `<${tag}> must never be created`);
    }
    const text = allText(dom);
    for (const label of ["model", "prompt", "app", "reasoning", "response", "content", "result", "problem", "rationale", "diff", "path"]) {
      assert.ok(text.includes(evil(label)), `${label} must be shown as plain text`);
    }
    for (const element of allElements(dom)) {
      const href = element.attributes.get("href");
      assert.ok(href === undefined || href.startsWith("#/"), `no external link may come from data: ${href}`);
      for (const name of element.attributes.keys()) {
        assert.doesNotMatch(name, /^on/);
        assert.notEqual(name, "style");
      }
    }
  }
});

test("the whole screen goes through the safe renderer in every state and scenario", () => {
  const results: DetailResult[] = [
    { kind: "loading" },
    { kind: "notfound" },
    { kind: "error", error: new ApiError("timeout") },
    ok(),
    ok(detail({ outcome: "failed", steps: [], findings: [], error: null })),
    ok(detail({ outcome: "partial", truncated: true, head_sha: null, duration_s: null })),
  ];
  for (const result of results) {
    assert.doesNotThrow(() => render(detailView({ id: 1, result }), fakeFactory));
  }
});

test("a heavy review (15 steps with long texts) builds quickly", () => {
  const long = "x".repeat(50_000);
  const steps: StepOut[] = Array.from({ length: 15 }, (_, i) => ({ ...STEP_ONE, index: i, tool_results: [{ ...STEP_ONE.tool_results[0]!, content: long }] }));
  const started = performance.now();
  render(detailView({ id: 1, result: ok(detail({ steps })) }), fakeFactory);
  assert.ok(performance.now() - started < 100, "must stay under 100 ms");
});
