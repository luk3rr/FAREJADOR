# Painel de revisões

Uma página pública, somente leitura, para ver o que o Farejador fez: quantas revisões, como terminaram e,
para cada uma, o raciocínio do modelo passo a passo. Ela mostra **apenas repositórios públicos**, os
mesmos que a [API de leitura](api.md) devolve. Existe quando o serviço roda nos modos `webhook` ou
`both` (no modo `polling` não há servidor HTTP).

## Telas

| Endereço | O que mostra |
|---|---|
| `/#/` | Visão geral: totais, resultados, tokens, duração e destino dos achados num período (7, 30 ou 90 dias) |
| `/#/revisoes` | Lista com filtros por repositório, PR, resultado e período, e "Carregar mais" |
| `/#/revisoes/42` | Detalhe: cabeçalho, orçamento usado, linha do tempo do raciocínio e achados |

Os filtros ficam no endereço (`/#/revisoes?repo=dono/nome&resultado=failed`), então um link reproduz a
mesma lista. Há tema escuro (Dracula) e claro; a escolha fica no navegador.

## Como é feito

TypeScript compilado com `tsc`, sem framework nem empacotador. A única dependência de desenvolvimento é
o próprio `typescript`, fixado no `web/package-lock.json`. Cada tela é uma função pura que devolve uma
árvore de nós; só `web/src/dom/render.ts` toca no DOM, e ele recusa tags, atributos e endereços fora de
uma lista permitida. Texto vindo da API nunca vira HTML. A página é servida pelo mesmo contêiner da API,
com uma política de segurança de conteúdo estrita (`default-src 'none'`, scripts só do próprio
endereço).

Os tipos da API são **gerados** do esquema OpenAPI; um teste falha se o arquivo commitado ficar
desatualizado.

## Trabalhar no painel

Requer Node 22 (veja `web/.nvmrc`).

```bash
npm --prefix web ci --ignore-scripts   # instala só o typescript, sem scripts de instalação
npm --prefix web run check             # tsc estrito, sem gerar arquivos
npm --prefix web test                  # testes (node:test)
npm --prefix web run build             # gera src/farejador/web/static/
uv run python scripts/gen_api_types.py # regenera web/src/api/types.ts após mudar a API
```

Depois do `build`, `uv run farejador run` (modo webhook) serve o painel em `http://127.0.0.1:8080/`.
Sem o build, o serviço sobe normalmente e `/` responde 404, com um aviso no log.

A imagem Docker compila o painel num estágio Node (fixado por digest) e copia só o resultado; o Node não
vai para a imagem final. O resultado também entra no wheel.

## Limites conhecidos

- O período das métricas usa dias do calendário em UTC.
- Com mais de 50 mil revisões no período, os totais são marcados como parciais (`capped`).
- Os blocos recolhíveis usam `<details>` nativo; o tema claro e Safari/Firefox ainda não foram
  verificados em navegador real.
