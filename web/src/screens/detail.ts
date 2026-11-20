// Filename: detail.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// The review detail screen, a pure function of its model. A 404 says only that the review may have
// expired: it is the same answer for a missing, a private and an unknown review, and the screen
// must not hint at which one it was.

import type { ApiError } from "../api/client.js";
import type { ReviewDetail } from "../api/types.js";
import { errorBanner, loadingBlock } from "../components/states.js";
import { h } from "../dom/vnode.js";
import type { VElement } from "../dom/vnode.js";
import { budgetCard, statusBanners } from "./detail-banners.js";
import { breadcrumb, detailHeader } from "./detail-header.js";
import { findingsCard } from "./findings.js";
import { timelineCard } from "./timeline.js";

export type DetailResult =
  | { readonly kind: "loading" }
  | { readonly kind: "notfound" }
  | { readonly kind: "error"; readonly error: ApiError }
  | { readonly kind: "ok"; readonly data: ReviewDetail };

export interface DetailModel {
  readonly id: number;
  readonly result: DetailResult;
}

export function detailView(model: DetailModel): VElement {
  const { id, result } = model;
  if (result.kind === "ok") {
    const detail = result.data;
    return h(
      "main",
      { class: "content" },
      breadcrumb(id),
      detailHeader(detail),
      statusBanners(detail),
      budgetCard(detail),
      timelineCard(detail.steps),
      detail.outcome === "failed" && detail.findings.length === 0 ? null : findingsCard(detail.findings),
    );
  }
  const body =
    result.kind === "loading"
      ? loadingBlock("Carregando a revisão…")
      : result.kind === "error"
        ? errorBanner(result.error)
        : h(
            "div",
            { class: "empty" },
            h("h2", {}, "Não encontramos esta revisão."),
            h("p", { class: "muted" }, "Ela pode ter expirado (guardamos os dados por um tempo limitado)."),
            h("a", { class: "btn sm ghost", href: "#/revisoes" }, "Voltar à lista"),
          );
  return h("main", { class: "content" }, breadcrumb(id), body);
}
