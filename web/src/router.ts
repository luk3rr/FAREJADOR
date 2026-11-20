// Filename: router.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Addresses of the dashboard, all behind a `#` so the server only ever serves `/`:
//   #/visao-geral, #/revisoes?repo=…&pr=…&resultado=…&de=…&ate=…, #/revisoes/42
// Parsing never throws: an unknown address is a "not found" route, and an invalid filter is
// ignored and reported in `warnings`.

export type Outcome = "complete" | "partial" | "failed";

export interface ListFilters {
  readonly repo?: string;
  readonly pr?: number;
  readonly outcome?: Outcome;
  readonly since?: string; // YYYY-MM-DD
  readonly until?: string; // YYYY-MM-DD
}

export type Route =
  | { readonly name: "overview" }
  | { readonly name: "list"; readonly filters: ListFilters; readonly warnings: readonly string[] }
  | { readonly name: "detail"; readonly id: number }
  | { readonly name: "notfound"; readonly path: string };

const REPO = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/;
const OUTCOMES: readonly string[] = ["complete", "partial", "failed"];
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
export const MAX_PR = 2 ** 31 - 1;

function isRealDate(value: string): boolean {
  const match = DATE.exec(value);
  if (match === null) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function parseFilters(query: string): { filters: ListFilters; warnings: string[] } {
  const params = new URLSearchParams(query);
  const warnings: string[] = [];
  let filters: ListFilters = {};

  const repo = params.get("repo");
  if (repo !== null) {
    if (REPO.test(repo)) filters = { ...filters, repo };
    else warnings.push("O filtro de repositório é inválido e foi ignorado.");
  }
  const pr = params.get("pr");
  if (pr !== null) {
    const number = Number(pr);
    if (/^\d{1,10}$/.test(pr) && number >= 1 && number <= MAX_PR) filters = { ...filters, pr: number };
    else warnings.push("O filtro de PR é inválido e foi ignorado.");
  }
  const outcome = params.get("resultado");
  if (outcome !== null) {
    if (OUTCOMES.includes(outcome)) filters = { ...filters, outcome: outcome as Outcome };
    else warnings.push("O filtro de resultado é inválido e foi ignorado.");
  }
  const since = params.get("de");
  if (since !== null) {
    if (isRealDate(since)) filters = { ...filters, since };
    else warnings.push("A data inicial é inválida e foi ignorada.");
  }
  const until = params.get("ate");
  if (until !== null) {
    if (isRealDate(until)) filters = { ...filters, until };
    else warnings.push("A data final é inválida e foi ignorada.");
  }
  if (filters.since !== undefined && filters.until !== undefined && filters.since > filters.until) {
    const { since: _since, ...rest } = filters;
    filters = rest;
    warnings.push("A data inicial era posterior à final e foi ignorada.");
  }
  return { filters, warnings };
}

export function parseHash(hash: string): Route {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const split = raw.indexOf("?");
  const path = split === -1 ? raw : raw.slice(0, split);
  const query = split === -1 ? "" : raw.slice(split + 1);
  const segments = path.split("/").filter((part) => part !== "");

  if (segments.length === 0 || (segments.length === 1 && segments[0] === "visao-geral")) {
    return { name: "overview" };
  }
  if (segments[0] === "revisoes") {
    if (segments.length === 1) {
      const { filters, warnings } = parseFilters(query);
      return { name: "list", filters, warnings };
    }
    const id = segments[1] ?? "";
    if (segments.length === 2 && /^\d{1,15}$/.test(id) && Number(id) >= 1) {
      return { name: "detail", id: Number(id) };
    }
  }
  return { name: "notfound", path: raw.slice(0, 200) };
}

export function formatFilters(filters: ListFilters): string {
  const parts: [string, string][] = [];
  if (filters.repo !== undefined) parts.push(["repo", filters.repo]);
  if (filters.pr !== undefined) parts.push(["pr", String(filters.pr)]);
  if (filters.outcome !== undefined) parts.push(["resultado", filters.outcome]);
  if (filters.since !== undefined) parts.push(["de", filters.since]);
  if (filters.until !== undefined) parts.push(["ate", filters.until]);
  return new URLSearchParams(parts).toString();
}

export function formatRoute(route: Route): string {
  switch (route.name) {
    case "overview":
      return "#/visao-geral";
    case "list": {
      const query = formatFilters(route.filters);
      return query === "" ? "#/revisoes" : `#/revisoes?${query}`;
    }
    case "detail":
      return `#/revisoes/${route.id}`;
    case "notfound":
      return "#/visao-geral";
  }
}
