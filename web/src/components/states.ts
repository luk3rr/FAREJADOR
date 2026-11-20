// Filename: states.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The states every data screen shares: loading, empty, error (with "try again") and not found.
// Loading and error are announced to screen readers through live regions (FR-27).

import { ApiError } from "../api/client.js";
import { h } from "../dom/vnode.js";
import type { VElement } from "../dom/vnode.js";

export function errorMessage(error: ApiError): string {
  switch (error.kind) {
    case "unavailable":
      return "Não foi possível carregar os dados: a API respondeu 503 (trace indisponível).";
    case "timeout":
      return "A API demorou mais de 10 segundos para responder.";
    case "network":
      return "Sem conexão com a API.";
    case "rate_limited":
      return "Muitas requisições em pouco tempo. Aguarde alguns segundos e tente de novo.";
    case "not_found":
      return "Não encontramos o que você pediu.";
    case "invalid_parameter":
      return "A API recusou os parâmetros pedidos.";
    case "aborted":
      return "A chamada foi cancelada.";
    case "bad_response":
      return "A API devolveu uma resposta inesperada.";
  }
}

export function loadingBlock(label = "Carregando…"): VElement {
  return h(
    "div",
    { class: "card stack", role: "status", "aria-live": "polite", "aria-busy": "true" },
    h("span", { class: "muted" }, label),
    h("div", { class: "sk sk-wide" }),
    h("div", { class: "sk" }),
    h("div", { class: "sk sk-short" }),
  );
}

export function emptyState(title: string, text: string): VElement {
  return h("div", { class: "empty" }, h("b", {}, title), h("p", { class: "muted" }, text));
}

export function errorBanner(error: ApiError): VElement {
  return h(
    "div",
    { class: "banner bad", role: "alert" },
    h("span", {}, errorMessage(error)),
    " ",
    h("button", { class: "btn sm ghost", type: "button", "data-action": "retry" }, "Tentar de novo"),
  );
}

export function notFoundView(): VElement {
  return h(
    "div",
    { class: "empty" },
    h("h2", {}, "Página não encontrada"),
    h("p", { class: "muted" }, "Este endereço não existe no painel."),
    h("a", { class: "btn sm ghost", href: "#/visao-geral" }, "Ir para a visão geral"),
  );
}
