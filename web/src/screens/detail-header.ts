// Filename: detail-header.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The top of the review detail: where it came from, who ran it and when. The link to the pull
// request is built only from a repository name and a number that passed validation, so no text
// from the API can become part of an address.

import type { ReviewDetail } from "../api/types.js";
import { h } from "../dom/vnode.js";
import type { VElement } from "../dom/vnode.js";
import { formatDateTime, formatDuration } from "../format.js";

const REPO = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$/;
const MAX_PR = 999_999_999;
const KIND: Readonly<Record<string, string>> = { review: "Revisão", command: "Comando" };
const OUTCOME: Readonly<Record<string, { label: string; tone: string }>> = {
  complete: { label: "Concluída", tone: "ok" },
  partial: { label: "Parcial", tone: "warn" },
  failed: { label: "Falhou", tone: "bad" },
};

/** `https://github.com/owner/name/pull/N`, or null when the repository or the number is not plain. */
export function pullRequestUrl(repo: string, number: number): string | null {
  if (!REPO.test(repo) || repo.includes("..") || !Number.isInteger(number) || number < 1 || number > MAX_PR) {
    return null;
  }
  return `https://github.com/${repo}/pull/${number}`;
}

export function outcomePill(outcome: string): VElement {
  const known = OUTCOME[outcome] ?? { label: outcome, tone: "" };
  return h("span", { class: known.tone === "" ? "pill" : `pill ${known.tone}` }, known.label);
}

export function breadcrumb(id: number): VElement {
  return h("nav", { class: "crumb", "aria-label": "Você está em" }, h("a", { href: "#/revisoes" }, "Revisões"), " › ", h("b", {}, `#${id}`));
}

function fact(label: string, value: VElement | string): VElement {
  return h("div", {}, h("span", { class: "lbl" }, label), value);
}

export function detailHeader(detail: ReviewDetail): VElement {
  const url = pullRequestUrl(detail.repo, detail.pr_number);
  const sha = detail.head_sha === null ? "—" : detail.head_sha.slice(0, 7);
  return h(
    "div",
    { class: "stack" },
    h(
      "div",
      { class: "head" },
      h("h1", {}, detail.repo, " ", h("span", { class: "muted" }, `#${detail.pr_number}`)),
      h("div", { class: "chips" }, outcomePill(detail.outcome), h("span", { class: "pill" }, KIND[detail.kind] ?? detail.kind)),
    ),
    h(
      "div",
      { class: "card" },
      h(
        "div",
        { class: "meta" },
        fact(
          "Repositório · PR",
          h(
            "div",
            {},
            h("b", {}, detail.repo),
            " ",
            h("span", { class: "muted" }, `#${detail.pr_number}`),
            url === null ? null : h("a", { class: "extlink", href: url, target: "_blank", rel: "noopener noreferrer" }, "abrir no GitHub ↗"),
          ),
        ),
        fact("Commit", h("b", { class: "mono" }, sha)),
        fact("Modelo", h("b", { class: "mono" }, detail.model)),
        fact("Início", h("b", { title: detail.started_at }, formatDateTime(detail.started_at))),
        fact("Prompt", h("b", { class: "mono" }, detail.prompt_version)),
        fact("Versão do app", h("b", { class: "mono" }, detail.app_version)),
        fact("Tipo", h("b", {}, KIND[detail.kind] ?? detail.kind)),
        fact("Duração", h("b", {}, formatDuration(detail.duration_s))),
      ),
    ),
  );
}
