# Filename: labels.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Portuguese display labels for values that are English identifiers inside the code.

Codes such as ``medium`` or ``lockfile`` are a technical contract (schemas, state, logs) and stay
in English; only the text shown to people on the pull request, and to the model, is translated.
"""

from __future__ import annotations

SEVERITY_LABELS = {"high": "alta", "medium": "média", "low": "baixa"}

CATEGORY_LABELS = {
    "maintainability": "manutenibilidade",
    "readability": "legibilidade",
    "complexity": "complexidade",
    "duplication": "duplicação",
    "naming": "nomenclatura",
    "error-handling": "tratamento de erros",
    "testing": "testes",
    "design": "design",
    "performance": "desempenho",
    "security": "segurança",
    "other": "outro",
}

SKIP_REASON_LABELS = {
    "lockfile": "arquivo de lock",
    "secret-bearing": "pode conter credenciais",
    "generated": "arquivo gerado",
    "vendored": "código de terceiros",
    "binary": "binário",
    "deleted": "arquivo removido",
    "custom": "padrão configurado para ignorar",
    "file-limit": "limite de arquivos por revisão",
    "no-added-lines": "sem linhas adicionadas",
}


def severity_label(code: str) -> str:
    return SEVERITY_LABELS.get(code, code)


def category_label(code: str) -> str:
    return CATEGORY_LABELS.get(code, code)


def skip_reason_label(code: str) -> str:
    return SKIP_REASON_LABELS.get(code, code)
