// Filename: timeline.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The timeline of the reasoning (design A): one card per step, that is, one trip to the model with
// the tools it called afterwards. The long parts (input, tool results) start collapsed.

import type { MessageOut, StepOut, ToolResultOut } from "../api/types.js";
import { h } from "../dom/vnode.js";
import type { Child, VElement } from "../dom/vnode.js";
import { formatDuration, formatInt } from "../format.js";
import { roleLabel } from "../labels.js";

const FINAL_TOOLS: ReadonlySet<string> = new Set(["submit_review", "submit_verdicts"]);

function block(title: Child, content: Child, options: { open?: boolean; kind?: string } = {}): VElement {
  return h(
    "details",
    { class: options.kind === undefined ? "blk" : `blk ${options.kind}`, open: options.open === true },
    h("summary", {}, title),
    h("div", { class: "in" }, content),
  );
}

function message(item: MessageOut): VElement {
  return h("div", { class: "msg" }, h("div", { class: "hint" }, roleLabel(item.role)), h("pre", { class: "code" }, item.content));
}

function inputBlock(messages: readonly MessageOut[]): VElement | null {
  if (messages.length === 0) return null;
  return block(`Entrada · ${messages.length} ${messages.length === 1 ? "mensagem" : "mensagens"}`, messages.map(message));
}

function reasoningBlock(reasoning: string | null): VElement {
  return reasoning === null || reasoning.trim() === ""
    ? h("p", { class: "hint" }, "Raciocínio indisponível neste provedor.")
    : block("Raciocínio do modelo", reasoning, { open: true, kind: "think" });
}

function resultBlock(result: ToolResultOut): VElement {
  const size = `${formatInt(result.original_chars)} ${result.original_chars === 1 ? "caractere" : "caracteres"}`;
  return block(
    [`Resultado · ${size}`, result.truncated ? [" ", h("span", { class: "cut" }, "cortado")] : null],
    h("pre", { class: "code" }, result.content),
  );
}

function toolCall(call: StepOut["response"]["tool_calls"][number], result: ToolResultOut | undefined): VElement {
  return h(
    "div",
    { class: "call" },
    h(
      "div",
      { class: "callhead" },
      h("code", { class: "mono" }, `${call.name}(${call.arguments})`),
      result === undefined ? null : h("span", { class: "muted" }, formatDuration(result.duration_s)),
      FINAL_TOOLS.has(call.name) ? h("span", { class: "pill ok" }, "resposta final") : null,
    ),
    result === undefined ? null : resultBlock(result),
  );
}

export function stepCard(step: StepOut): VElement {
  const final = step.response.tool_calls.some((call) => FINAL_TOOLS.has(call.name));
  const results = new Map(step.tool_results.map((result) => [result.call_id, result]));
  return h(
    "div",
    { class: final ? "step final" : "step" },
    h("div", { class: "hd" }, h("b", {}, `Passo ${step.index + 1}`), h("span", { class: "muted" }, `${formatDuration(step.duration_s)} · ${formatInt(step.tokens)} tokens`)),
    inputBlock(step.input_messages),
    reasoningBlock(step.response.reasoning),
    step.response.content === null || step.response.content.trim() === "" ? null : block("Resposta do modelo", h("p", { class: "plain" }, step.response.content)),
    step.response.tool_calls.map((call) => toolCall(call, results.get(call.id))),
  );
}

export function timelineCard(steps: readonly StepOut[]): VElement {
  return h(
    "div",
    { class: "card stack" },
    h("h2", {}, "Linha do tempo do raciocínio"),
    steps.length === 0 ? h("p", { class: "muted" }, "Nenhum passo foi registrado: a revisão parou antes da primeira resposta do modelo.") : h("div", { class: "tl" }, steps.map(stepCard)),
  );
}
