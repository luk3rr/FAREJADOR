// Filename: labels.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Portuguese labels for the codes of the API. Unknown codes are shown as they came, as text.

const SEVERITY: Readonly<Record<string, string>> = { low: "baixa", medium: "média", high: "alta" };
const CATEGORY: Readonly<Record<string, string>> = {
  maintainability: "manutenibilidade",
  readability: "legibilidade",
  complexity: "complexidade",
  duplication: "duplicação",
  naming: "nomes",
  "error-handling": "tratamento de erros",
  testing: "testes",
  design: "design",
  performance: "desempenho",
  security: "segurança",
  other: "outros",
};
const DISPOSITION: Readonly<Record<string, { label: string; tone: string }>> = {
  inline: { label: "No código", tone: "ok" },
  summary: { label: "Gerais", tone: "warn" },
  dropped: { label: "Descartado", tone: "" },
};
const REASON: Readonly<Record<string, string>> = {
  line_not_added: "a linha não foi adicionada pelo PR",
  duplicate: "repetido",
  file_not_in_diff: "arquivo fora do diff",
  file_ignored: "arquivo ignorado",
  inline_limit: "limite de comentários na linha",
};
const ROLE: Readonly<Record<string, string>> = {
  system: "Sistema",
  user: "Usuário",
  assistant: "Modelo",
  tool: "Ferramenta",
};
const ERROR_CATEGORY: Readonly<Record<string, string>> = {
  model_api: "erro do modelo",
  invalid_output: "resposta inválida",
  github_api: "erro do GitHub",
  budget: "orçamento esgotado",
  internal: "erro interno",
};

export const severityLabel = (code: string): string => SEVERITY[code] ?? code;
export const categoryLabel = (code: string): string => CATEGORY[code] ?? code;
export const dispositionLabel = (code: string): { label: string; tone: string } => DISPOSITION[code] ?? { label: code, tone: "" };
export const reasonLabel = (code: string): string => REASON[code] ?? code;
export const roleLabel = (code: string): string => ROLE[code] ?? code;
export const errorCategoryLabel = (code: string): string => ERROR_CATEGORY[code] ?? code;
