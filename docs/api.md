# API de leitura do trace

O Farejador guarda, para cada revisão, o que o modelo viu e decidiu: as mensagens, as ferramentas
que chamou, o raciocínio (quando o provedor o devolve), cada achado e o destino dele. Esta API
permite **ler** esses dados. Ela é somente leitura e serve apenas repositórios **públicos**.

Ela existe só quando o serviço roda nos modos `webhook` ou `both`. No modo `polling` o trace é
gravado, mas não há servidor HTTP, então não há API.

## Regras que valem para tudo

- **Só repositórios públicos.** Uma revisão de repositório privado, ou cuja visibilidade não foi
  possível confirmar, não aparece em nenhuma lista, filtro ou contagem. Consultar o `id` dela
  responde `404`, exatamente igual a um `id` que não existe.
- **Somente leitura.** Qualquer método que não seja `GET` ou `HEAD` responde `405`.
- **Retenção.** Os traces são apagados depois de `FAREJADOR_TRACE_RETENTION_DAYS` dias (padrão 30).
- **Tudo é JSON** (`application/json; charset=utf-8`), com `X-Content-Type-Options: nosniff` e sem
  CORS. O texto dos campos vem do modelo e de pull requests de terceiros: **trate-o como
  não confiável** e escape-o antes de mostrá-lo em uma página.
- **Limite de requisições.** A Cloudflare limita as requisições por endereço; passar do limite
  devolve `429`.

## Rotas

| Rota | O que devolve |
|---|---|
| `GET /api/reviews` | Lista paginada de resumos, da revisão mais recente para a mais antiga |
| `GET /api/reviews/{id}` | O trace completo de uma revisão |
| `GET /api/status` | Se o trace está disponível, a retenção e quantas revisões públicas existem |
| `GET /api/openapi.json` | O esquema OpenAPI destas rotas |

### `GET /api/reviews`

| Parâmetro | Tipo | Padrão | Regra |
|---|---|---|---|
| `limit` | inteiro | 20 | de 1 a 50 |
| `cursor` | texto | início | o `next_cursor` da página anterior |
| `repo` | `dono/nome` | todos | formato validado; comparação exata |
| `pr` | inteiro | todos | maior que 0 |
| `outcome` | `complete`, `partial` ou `failed` | todos | revisões em andamento ou abandonadas aparecem como `partial` |
| `since`, `until` | data e hora ISO 8601 | sem limite | sem fuso vale UTC; `since` não pode passar de `until` |

```json
{
  "items": [
    {
      "id": 42,
      "repo": "luk3rr/FAREJADOR_PILOT",
      "pr_number": 1,
      "head_sha": "368f961…",
      "kind": "review",
      "model": "provedor/modelo",
      "prompt_version": "2026-11-21.2",
      "app_version": "0.1.2",
      "outcome": "complete",
      "step_count": 3,
      "tokens": 18452,
      "duration_s": 41.7,
      "findings_inline": 2,
      "findings_summary": 1,
      "findings_dropped": 1,
      "error_category": null,
      "started_at": "2026-11-21T20:42:11Z"
    }
  ],
  "next_cursor": "NDE"
}
```

`next_cursor` é `null` na última página. O `kind` é `review` (primeira revisão ou nova revisão por
comando) ou `command` (reavaliação dos threads abertos).

### `GET /api/reviews/{id}`

O resumo acima, mais:

```json
{
  "budgets": {"max_steps": 15, "max_tokens": 200000, "max_seconds": 300, "max_files": 40},
  "steps": [
    {
      "index": 0,
      "started_at": "2026-11-21T20:42:11Z",
      "duration_s": 3.2,
      "tokens": 4100,
      "input_messages": [
        {"role": "system", "content": "…", "tool_call_id": null},
        {"role": "user", "content": "…", "tool_call_id": null}
      ],
      "response": {
        "content": null,
        "reasoning": null,
        "tool_calls": [{"id": "c1", "name": "read_file", "arguments": "{\"path\": \"a.py\"}"}]
      },
      "tool_results": [
        {"call_id": "c1", "name": "read_file", "duration_s": 0.01, "content": "…",
         "truncated": false, "original_chars": 812}
      ]
    }
  ],
  "findings": [
    {"path": "a.py", "line": 14, "severity": "medium", "category": "design",
     "problem": "…", "rationale": "…", "suggestion": "…", "suggestion_diff": null,
     "diff_dropped": false, "disposition": "inline", "reason": null}
  ],
  "error": null,
  "truncated": false
}
```

- Cada passo traz em `input_messages` **só as mensagens novas** daquele passo. Para reconstruir a
  conversa, junte os passos em ordem: as mensagens de entrada, a resposta e os resultados das
  ferramentas, passo a passo.
- `reasoning` só vem preenchido quando o provedor do modelo o devolve.
- `disposition` diz o que aconteceu com cada achado que o modelo devolveu: `inline` (comentário na
  linha), `summary` (foi para o resumo da revisão, porque não pôde ser ancorado) ou `dropped` (não
  foi publicado: era repetido). O `reason` explica os dois últimos: `file_ignored`,
  `file_not_in_diff`, `line_not_added`, `inline_limit` e `duplicate`. Um diff de sugestão que não
  bate com o código não muda o destino do achado; ele sai com `diff_dropped` verdadeiro.
- `error`, quando existe, traz `category` (`model_api`, `invalid_output`, `github_api`, `budget` ou
  `internal`) e uma `message`. A mensagem só é pública para `budget`, `model_api` e
  `invalid_output`; para `github_api` e `internal` vem o texto fixo `detalhes omitidos`, porque o texto
  original pode revelar como o servidor está configurado.
- `truncated` é verdadeiro se algum texto foi cortado (limite por item ou teto por revisão); cada
  resultado de ferramenta cortado também traz o tamanho original em `original_chars`.
- Todo texto foi mascarado antes de ser gravado: no lugar de segredos aparece `«segredo-removido»`.

### `GET /api/status`

```json
{"status": "ok", "trace_available": true, "retention_days": 30, "reviews": 128}
```

`reviews` conta só as revisões públicas.

## Erros

| Situação | Resposta |
|---|---|
| Revisão inexistente, privada ou de visibilidade desconhecida; rota desconhecida | `404 {"error": "not_found"}` |
| Método diferente de `GET` e `HEAD` | `405 {"error": "method_not_allowed"}` com `Allow: GET, HEAD` |
| Parâmetro inválido | `422 {"error": "invalid_parameter", "detail": [{"field": "limit", "message": "…"}]}` |
| O arquivo do trace falta, está corrompido ou uma consulta passou de 5 segundos | `503 {"error": "trace_unavailable"}` |
| Excesso de requisições | `429`, devolvido pela Cloudflare |

As respostas de erro levam `Cache-Control: no-store`; as de sucesso, `public, max-age=30`.

## Exemplos

```bash
# as 5 revisões mais recentes
curl -s 'https://farejador.luk3rr.com/api/reviews?limit=5'

# só as que falharam, de um repositório
curl -s 'https://farejador.luk3rr.com/api/reviews?repo=luk3rr/FAREJADOR_PILOT&outcome=failed'

# o raciocínio e as ferramentas de uma revisão
curl -s 'https://farejador.luk3rr.com/api/reviews/42' | jq '.steps[] | {index, reasoning: .response.reasoning}'
```
