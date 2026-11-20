// Filename: findings.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Every finding the model returned, with where it went and why (inline, summary or dropped).

import type { FindingOut } from "../api/types.js";
import { h } from "../dom/vnode.js";
import type { VElement } from "../dom/vnode.js";
import { categoryLabel, dispositionLabel, reasonLabel, severityLabel } from "../labels.js";

function finding(item: FindingOut): VElement {
  const disposition = dispositionLabel(item.disposition);
  return h(
    "div",
    { class: "find" },
    h(
      "div",
      { class: "t" },
      h("span", { class: disposition.tone === "" ? "pill" : `pill ${disposition.tone}` }, disposition.label),
      item.reason === null ? null : h("span", { class: "muted" }, reasonLabel(item.reason)),
      h("span", { class: "mono" }, `${item.path}:${item.line}`),
      h("span", { class: "pill" }, `${severityLabel(item.severity)} · ${categoryLabel(item.category)}`),
    ),
    h("p", { class: "plain" }, item.problem),
    item.rationale === "" && item.suggestion === ""
      ? null
      : h(
          "details",
          { class: "blk" },
          h("summary", {}, "Racional e sugestão"),
          h(
            "div",
            { class: "in" },
            item.rationale === "" ? null : h("p", { class: "plain" }, item.rationale),
            item.suggestion === "" ? null : h("p", { class: "plain" }, item.suggestion),
          ),
        ),
    item.suggestion_diff === null ? null : h("pre", { class: "code" }, item.suggestion_diff),
    item.diff_dropped ? h("p", { class: "hint" }, "O diff sugerido não bateu com o código do PR e não foi publicado.") : null,
  );
}

export function findingsCard(items: readonly FindingOut[]): VElement {
  return h(
    "div",
    { class: "card stack" },
    h("h2", {}, `Achados do modelo (${items.length})`),
    items.length === 0 ? h("p", { class: "muted" }, "O modelo não devolveu achados nesta execução.") : items.map(finding),
  );
}
