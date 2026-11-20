// Filename: detail-fixtures.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// A review detail as the API sends it, to build the cases of the detail tests from.

import type { FindingOut, ReviewDetail, StepOut } from "../src/api/types.js";

export const STEP_ONE: StepOut = {
  index: 0,
  started_at: "2026-11-21T20:42:11Z",
  duration_s: 3.2,
  tokens: 4100,
  input_messages: [
    { role: "system", content: "Você é o Farejador…" },
    { role: "user", content: "PR: Adicionar b\n+ value = normalize(None)" },
  ],
  response: {
    content: "Vou ler o arquivo.",
    reasoning: "O diff adiciona `value = normalize(None)`. Preciso ver o que `normalize` faz.",
    tool_calls: [{ id: "c1", name: "read_file", arguments: '{"path": "a.py"}' }],
  },
  tool_results: [{ call_id: "c1", name: "read_file", duration_s: 0.01, content: "def normalize(u):\n    return u.strip()", truncated: false, original_chars: 38 }],
};

export const STEP_TWO: StepOut = {
  index: 1,
  started_at: "2026-11-21T20:42:14Z",
  duration_s: 2.6,
  tokens: 3900,
  input_messages: [],
  response: {
    content: null,
    reasoning: null,
    tool_calls: [{ id: "c2", name: "submit_review", arguments: '{"summary": "ok", "findings": []}' }],
  },
  tool_results: [],
};

export const FINDINGS: FindingOut[] = [
  { path: "b.py", line: 2, severity: "medium", category: "error-handling", problem: "normalize(None) falha com AttributeError.", rationale: "strip() não existe em None.", suggestion: "Proteja a chamada.", suggestion_diff: '-value = normalize(None)\n+value = normalize(texto or "")', diff_dropped: false, disposition: "inline", reason: null },
  { path: "b.py", line: 3, severity: "low", category: "readability", problem: "Linha de contexto, não adicionada.", rationale: "", suggestion: "", suggestion_diff: null, diff_dropped: false, disposition: "summary", reason: "line_not_added" },
  { path: "b.py", line: 2, severity: "medium", category: "error-handling", problem: "normalize(None) falha com AttributeError.", rationale: "", suggestion: "", suggestion_diff: null, diff_dropped: true, disposition: "dropped", reason: "duplicate" },
];

export function detail(overrides: Partial<ReviewDetail> = {}): ReviewDetail {
  return {
    id: 42,
    repo: "luk3rr/FAREJADOR_PILOT",
    pr_number: 1,
    head_sha: "368f9610000000000000000000000000000000aa",
    kind: "review",
    model: "provedor/modelo-a",
    prompt_version: "2026-11-21.2",
    app_version: "0.2.0",
    outcome: "complete",
    step_count: 3,
    tokens: 18452,
    duration_s: 41.7,
    findings_inline: 1,
    findings_summary: 1,
    findings_dropped: 1,
    error_category: null,
    started_at: "2026-11-21T20:42:11Z",
    budgets: { max_steps: 15, max_tokens: 200000, max_seconds: 300, max_files: 40 },
    steps: [STEP_ONE, STEP_TWO],
    findings: FINDINGS,
    error: null,
    truncated: false,
    ...overrides,
  };
}
