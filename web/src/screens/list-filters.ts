// Filename: list-filters.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Filters of the review list: from the form to the address, and from the address to the API query.
// The rules live in router.ts (parseFilters); this module only reuses them, so a value is
// validated in exactly one place.

import { parseFilters } from "../router.js";
import type { ListFilters, Outcome } from "../router.js";

export interface FormValues {
  readonly repo: string;
  readonly pr: string;
  readonly since: string;
  readonly until: string;
  readonly outcome: Outcome | "";
}

/** What the user typed, as validated filters; invalid fields are dropped with a warning. */
export function filtersFromForm(form: FormValues): { filters: ListFilters; warnings: string[] } {
  const params = new URLSearchParams();
  const fields: [string, string][] = [
    ["repo", form.repo.trim()],
    ["pr", form.pr.trim()],
    ["resultado", form.outcome],
    ["de", form.since.trim()],
    ["ate", form.until.trim()],
  ];
  for (const [name, value] of fields) {
    if (value !== "") params.set(name, value);
  }
  return parseFilters(params.toString());
}

export function hasFilters(filters: ListFilters): boolean {
  return Object.keys(filters).length > 0;
}

export const PAGE_SIZE = 20;

/** The query string of GET /api/reviews: dates become the start and the end of the day in UTC. */
export function apiQuery(filters: ListFilters, cursor: string | null, limit: number = PAGE_SIZE): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) params.set("cursor", cursor);
  if (filters.repo !== undefined) params.set("repo", filters.repo);
  if (filters.pr !== undefined) params.set("pr", String(filters.pr));
  if (filters.outcome !== undefined) params.set("outcome", filters.outcome);
  if (filters.since !== undefined) params.set("since", `${filters.since}T00:00:00Z`);
  if (filters.until !== undefined) params.set("until", `${filters.until}T23:59:59Z`);
  return params.toString();
}
