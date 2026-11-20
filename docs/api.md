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
| `GET /api/stats` | Agregados dos últimos N dias: totais, duração, tokens, revisões por dia, destino dos achados e tabela por modelo e prompt |
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

### `GET /api/stats`

Os números que o painel mostra na visão geral, calculados no servidor sobre as revisões **públicas** dos últimos `days` dias (de `1` a `365`, padrão `30`). O período são `days` dias corridos em UTC, terminando hoje: com `days=7` em 21/11, vai de 15/11 às 00:00 até agora.

```json
{
  "days": 7,
  "since": "2026-11-15",
  "until": "2026-11-21",
  "capped": false,
  "totals": {"reviews": 6, "complete": 2, "partial": 3, "failed": 1, "failure_rate": 0.1667},
  "duration_s": {"median": 10.0, "p95": 30.0},
  "tokens": {"mean": 1840.0, "median": 1000.0},
  "by_day": [{"day": "2026-11-15", "reviews": 0}, {"day": "2026-11-16", "reviews": 2}],
  "findings": {"inline": 6, "summary": 3, "dropped": 2},
  "by_model": [
    {"model": "provedor/modelo-a", "prompt_version": "2026-11-21.2", "reviews": 2, "failed": 1,
     "mean_tokens": 500.0, "median_duration_s": 6.0, "findings_per_review": 1.5}
  ]
}
```

- Revisões em andamento ou abandonadas contam como `partial`, como na lista, e ficam de fora só das médias de duração e de tokens, que olham as execuções já terminadas. `failure_rate` é `failed` dividido por `reviews` (0 quando não há revisões).
- `by_day` traz **todos** os dias do período, inclusive os sem revisões, do mais antigo para o mais novo.
- `median` e `mean` são `null` quando não há execuções terminadas; `p95` usa o posto mais próximo.
- `findings` soma o destino de todos os achados do período; `findings_per_review` é o total de achados do modelo (no código, no resumo e descartados) dividido pelas revisões da linha.
- A tabela `by_model` junta modelo e versão do prompt e vem da linha com mais revisões para a com menos.
- `capped` é verdadeiro se o período tinha mais de 50 mil execuções e só as 50 mil primeiras entraram nas contas.
- Os totais são os mesmos que se obtém somando a lista paginada (`/api/reviews`) do mesmo período.
- Cache de 60 segundos (`Cache-Control: public, max-age=60`).

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
