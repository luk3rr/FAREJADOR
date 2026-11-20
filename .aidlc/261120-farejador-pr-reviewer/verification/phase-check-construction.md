# Verificação de fase — Construction (farejador-pr-reviewer)

Data: 2026-11-20. Resultado: **PASS COM RESSALVAS** (riscos aceitos listados na seção 4; nenhuma falha de teste).

## 1. Inventário de artefatos

| Artefato | Presente |
|---|---|
| Código em `src/farejador/` (35 arquivos Python) e testes em `tests/` (70 arquivos Python) | ✓ |
| Notas 3.1 em `design.md` para UNIT-4, 6, 7 e 10; 3.4 para UNIT-11 (3.2 e 3.3 dobrados, conforme a rota combinada) | ✓ |
| `tasks.md`: resumo de cada Unit com arquivos, resultado e desvios | ✓ |
| `construction/build-and-test.md` (3.6) | ✓ |
| `construction/ci-pipeline.md` e `.github/workflows/ci.yml` (3.7) | ✓ |
| README, `docs/demo.md`, Dockerfile, compose, `.env.example`, script de fumaça | ✓ |
| Comando de verificação aprovado passando | ✓ exit 0, 627 testes, cobertura 99,11% |

## 2. Rastreabilidade: Unit para código, testes e resultado

| Unit | Tarefas | Código principal | Testes | Resultado |
|---|---|---|---|---|
| UNIT-1 Foundation | 6/6 | `config.py`, `log.py`, `pyproject.toml`, CI | `test_config`, `test_log`, `test_repo_files`, `test_headers` | verificada, exit 0 |
| UNIT-2 State and dispatcher | 6/6 | `models.py`, `state/store.py`, `dispatcher.py` | `tests/state/*`, `test_dispatcher*`, `test_models` | verificada, exit 0 |
| UNIT-3 GitHub access | 6/6 | `github/*` | `tests/github/*` | verificada, exit 0 |
| UNIT-4 Diff, filters, validation | 7/7 | `review/{findings,diff,filters,validator,sanitizer}.py` | `tests/review/test_{findings,diff*,ignore,mask,validator,sanitizer}.py` | verificada, exit 0 |
| UNIT-5 Workspace and tools | 6/6 | `tools.py`, `workspace.py` | `tests/tools/*`, `test_workspace` | verificada, exit 0 |
| UNIT-6 Agent | 7/7 | `agent/*` | `tests/agent/*` | verificada, exit 0 |
| UNIT-7 First review pipeline | 7/7 | `review/{pipeline,publisher}.py` | `tests/review/test_{eligibility,pipeline,publisher_*,failure_path,run_log}.py`, `tests/integration/test_first_review_e2e.py` | verificada, exit 0 |
| UNIT-8 Polling source | 4/4 | `sources/polling.py` | `tests/sources/test_polling_*.py` | verificada, exit 0 |
| UNIT-9 Webhook source | 5/5 | `sources/webhook.py` | `tests/sources/test_{hmac,webhook_*}.py` | verificada, exit 0 |
| UNIT-10 Command handler | 6/6 | `commands.py` | `tests/commands/*`, `tests/integration/test_command_e2e.py` | verificada, exit 0 |
| UNIT-11 Packaging and demo | 5/6 | `app.py`, `cli.py`, `Dockerfile`, compose, README | `test_app`, `test_cli`, `test_docker_files` | verificada pelo comando; **T-11.6 (execução manual do smoke) pendente** |

Total: **65 de 66 tarefas** concluídas. Nenhuma Unit foi pulada (`[S]`).

## 3. Cobertura dos requisitos

- **FR-1 a FR-24 e NFR-1 a NFR-12:** a matriz em `construction/build-and-test.md` § 3 aponta testes que passam para todos, verificado por script; exceção registrada: **NFR-8** (qualidade da revisão), que é manual por definição.
- **Histórias US-1 a US-12:** cada uma tem verificação automatizada (tabela do mesmo arquivo).
- **NFRs com Unit dona e validação:** NFR-1, 2, 4, 5, 6, 7, 9, 10 e 12 têm teste automatizado direto; NFR-3 tem testes na UNIT-1 e o teste de segredos sentinela da UNIT-7; NFR-11 tem validação estática e depende do build real para a prova completa.

## 4. Consistência e riscos aceitos

| Item | Situação |
|---|---|
| Contratos × código | Coerentes. Desvios aprovados e registrados: bind padrão do webhook agora `127.0.0.1` (a imagem define `0.0.0.0`); `grep` via `git grep` (A23 revisada); status `skipped` na UNIT-2; `FirstReview.review_now` e `report_failure` públicos; `OpenRouterClient` usa `httpx2` |
| Segurança | Ver `build-and-test.md` § 4. Pontos de alto risco da análise (R-1, R-3, R-6, R-7) têm teste automatizado |
| Estado de `design.md` | Notas 3.1 e 3.4 alinhadas ao código entregue; a tabela C-C foi atualizada para o novo padrão do bind |
| **Risco aceito 1** | Nenhuma chamada real ao GitHub, ao OpenRouter ou ao Docker foi feita: respostas simuladas (M-003) e Docker indisponível sem `sudo` interativo. Fechamento: `docs/demo.md` § 6 e `scripts/smoke_compose.sh` |
| **Risco aceito 2** | Auditoria de dependências (`pip-audit`) não executada; a CI e o SonarCloud só rodam depois do primeiro push |
| **Risco aceito 3** | Qualidade das revisões depende do modelo escolhido pelo usuário e será medida na demo (NFR-8) |
| Sem contradições abertas | As suposições A1 a A38 estão confirmadas ou registradas como desvio |

## 5. Veredito

PASS COM RESSALVAS. Não há testes falhando, tarefas obrigatórias sem código nem requisitos sem teste, exceto NFR-8 (manual). Os riscos aceitos acima dependem de ações suas (primeiro push, token do SonarCloud, `scripts/smoke_compose.sh`, demo com o GitHub App real e a chave do OpenRouter).
