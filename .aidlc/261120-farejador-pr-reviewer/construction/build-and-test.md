# Build and Test — farejador-pr-reviewer

Data: 2026-11-20. Estágio 3.6 (uma vez, para a solução inteira). Estratégia de testes do perfil `mvp`: **Standard** (testes unitários por componente, integração nas fronteiras entre Units e verificações de aceitação por história).

## 1. Comandos executados

| Comando | Resultado |
|---|---|
| `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest --cov=farejador --cov-fail-under=80` (comando aprovado) | **exit 0**: lint e formatação sem problemas; mypy strict sem erros em 35 arquivos; **627 testes passando**; cobertura **99,11%** (mínimo 80%) |
| `uv run ruff check --select S src` (regras de segurança tipo bandit, antes de entrarem na configuração) | 3 achados, todos tratados (seção 4); as regras `S` agora fazem parte do `ruff check` do comando aprovado |
| `bash -n scripts/smoke_compose.sh` | sintaxe válida |
| `uvx pip-audit` (auditoria de dependências) | **não executado**: a ação foi negada pelo ambiente por baixar e executar uma ferramenta de terceiros sem versão fixada; não foi contornada |
| `docker build` e `docker compose up` | **não executados**: o Docker deste computador exige `sudo` com terminal (ver seção 6) |

## 2. Resultado dos testes

| Pasta | Testes |
|---|---|
| `tests/` (raiz: config, log, modelos, dispatcher, workspace, CLI, app, arquivos do repositório, cabeçalhos, empacotamento) | 212 |
| `tests/review/` | 145 |
| `tests/sources/` | 73 |
| `tests/tools/` | 58 |
| `tests/agent/` | 54 |
| `tests/github/` | 38 |
| `tests/commands/` | 31 |
| `tests/state/` | 13 |
| `tests/integration/` | 3 |
| **Total** | **627** |

Nenhuma falha conhecida: todos os testes passam e nenhum foi enfraquecido ou removido para passar (cada falha durante a Construction foi corrigida no código, ou no teste quando a expectativa estava errada, e registrada em `audit.md` e nos resumos de cada Unit em `tasks.md`).

### Cobertura (99,11% no total)

Módulos abaixo de 100%, com as linhas que sobram: `agent/llm.py` 98% (ramo de saída), `agent/runner.py` 98% (ramos de fechamento já exercitados indiretamente), `app.py` 98% (ramo defensivo do segredo do webhook), `config.py` 99%, `github/auth.py` 97% (segunda checagem do cache dentro do lock), `github/client.py` 99%, `review/diff.py` 99%, `review/publisher.py` 97% (ramos de corte de listas muito longas), `sources/polling.py` 99%, `sources/webhook.py` 97% (ramos defensivos), `tools.py` 99%. Todos os demais módulos têm 100%.

## 3. Matriz requisito para teste

Cada arquivo citado existe e contém testes (verificado por script). Os testes de integração entre Units estão em `tests/integration/` (`test_first_review_e2e.py`, `test_command_e2e.py`).

### Requisitos funcionais

| FR | Testes que o validam |
|---|---|
| FR-1 | `tests/sources/test_hmac.py`, `tests/sources/test_webhook_events.py`, `tests/sources/test_webhook_errors.py` |
| FR-2 | `tests/sources/test_polling_prs.py`, `tests/sources/test_polling_comments.py`, `tests/sources/test_polling_etag.py`, `tests/sources/test_polling_loop.py` |
| FR-3 | `tests/review/test_eligibility.py`, `tests/sources/test_webhook_events.py`, `tests/sources/test_polling_prs.py` |
| FR-4 | `tests/state/test_store_claim.py`, `tests/state/test_idempotency_restart.py`, `tests/test_dispatcher.py`, `tests/sources/test_webhook_idempotency.py` |
| FR-5 | `tests/test_dispatcher_bot_and_restart.py`, `tests/sources/test_polling_comments.py`, `tests/sources/test_webhook_idempotency.py` |
| FR-6 | `tests/review/test_diff.py` |
| FR-7 | `tests/review/test_ignore.py`, `tests/review/test_pipeline.py` |
| FR-8 | `tests/test_workspace.py` |
| FR-9 | `tests/tools/test_confinement.py`, `tests/tools/test_read_file.py`, `tests/tools/test_grep.py`, `tests/tools/test_list_dir.py` |
| FR-10 | `tests/agent/test_runner_loop.py`, `tests/agent/test_prompts.py`, `tests/agent/test_openrouter_client.py` |
| FR-11 | `tests/agent/test_budgets.py` |
| FR-12 | `tests/agent/test_submit_review.py`, `tests/review/test_findings.py` |
| FR-13 | `tests/review/test_validator.py`, `tests/review/test_pipeline.py` |
| FR-14 | `tests/review/test_sanitizer.py`, `tests/review/test_publisher_format.py` |
| FR-15 | `tests/review/test_publisher_format.py`, `tests/review/test_publisher_post.py`, `tests/review/test_pipeline.py` |
| FR-16 | `tests/commands/test_authorization.py`, `tests/integration/test_command_e2e.py` |
| FR-17 | `tests/commands/test_command_reevaluate.py`, `tests/commands/test_resolve.py`, `tests/agent/test_reevaluate.py` |
| FR-18 | `tests/commands/test_branching.py`, `tests/integration/test_command_e2e.py` |
| FR-19 | `tests/review/test_mask.py`, `tests/review/test_diff_render.py`, `tests/tools/test_read_file.py`, `tests/integration/test_first_review_e2e.py` |
| FR-20 | `tests/review/test_failure_path.py` |
| FR-21 | `tests/github/test_auth.py`, `tests/github/test_client_errors.py` |
| FR-22 | `tests/test_config.py`, `tests/test_cli.py` |
| FR-23 | `tests/test_log.py`, `tests/review/test_run_log.py` |
| FR-24 | `tests/test_docker_files.py` |

### Requisitos não funcionais

| NFR | Testes que o validam |
|---|---|
| NFR-1 | `tests/sources/test_hmac.py`, `tests/sources/test_webhook_errors.py` |
| NFR-2 | `tests/tools/test_confinement.py` |
| NFR-3 | `tests/test_log.py`, `tests/test_config.py`, `tests/integration/test_first_review_e2e.py` |
| NFR-4 | `tests/state/test_idempotency_restart.py`, `tests/sources/test_webhook_idempotency.py` |
| NFR-5 | `tests/sources/test_webhook_fast_ack.py` |
| NFR-6 | `tests/agent/test_budgets.py`, `tests/test_config.py` |
| NFR-7 | `tests/review/test_validator.py` |
| NFR-9 | `tests/sources/test_polling_etag.py` |
| NFR-10 | `tests/test_repo_files.py`, `tests/test_headers.py` |
| NFR-11 | `tests/test_docker_files.py`, `tests/test_app.py` |
| NFR-12 | `tests/review/test_mask.py`, `tests/review/test_ignore.py`, `tests/test_docker_files.py` |
| NFR-8 | **Lacuna registrada**: qualidade da revisão é avaliada manualmente pelo autor; roteiro e planilha em `docs/demo.md` |

### Histórias de usuário (aceitação)

| História | Verificação automatizada |
|---|---|
| US-1 | `tests/review/test_eligibility.py` (draft, pronto, push posterior), `tests/review/test_pipeline.py` |
| US-2 | `tests/review/test_validator.py`, `test_sanitizer.py`, `test_pipeline.py` |
| US-3 | `tests/agent/test_runner_loop.py`, `tests/tools/*`, `tests/test_workspace.py` |
| US-4 | `tests/review/test_ignore.py`, `tests/agent/test_prompts.py`, `tests/review/test_pipeline.py` |
| US-5 | `tests/agent/test_budgets.py`, `tests/review/test_failure_path.py` |
| US-6 | `tests/review/test_mask.py`, `tests/integration/test_first_review_e2e.py` |
| US-7 | `tests/commands/test_authorization.py`, `test_resolve.py`, `tests/integration/test_command_e2e.py` |
| US-8 | `tests/commands/test_branching.py`, `tests/integration/test_command_e2e.py` |
| US-9 | `tests/sources/test_webhook_*.py`, `tests/sources/test_hmac.py` |
| US-10 | `tests/sources/test_polling_*.py` |
| US-11 | `tests/github/test_auth.py`, `tests/test_config.py`, `tests/test_cli.py` |
| US-12 | `tests/review/test_run_log.py`, `tests/test_docker_files.py` (empacotamento só estático) |

## 4. Notas de segurança

- **Lint de segurança.** Com as regras `S` do `ruff` aplicadas ao código-fonte apareceram três pontos, todos tratados: (1) `assert` em `app.py`, que desaparece com `python -O`, trocado por um erro explícito (`ConfigError`); (2) o webhook escutava em `0.0.0.0` por padrão: o padrão passou a `127.0.0.1` e a imagem Docker define `0.0.0.0` (alteração de contrato registrada em `design.md § 2.8`); (3) o `git grep` roda em subprocesso com argv fixo e sem shell, o que é intencional e ficou com `noqa` justificado. Os testes têm exceções limitadas (`assert`, segredos falsos, `subprocess` de teste).
- **Propriedades de segurança com teste automatizado:** verificação HMAC em tempo constante e rejeição antes de qualquer parsing; ferramentas do agente confinadas ao checkout (path traversal, symlinks, `.git`, arquivos de credenciais); saída das ferramentas e texto publicado mascarados; segredos sentinela ausentes de prompt, comentários e logs; token do GitHub fora de `.git/config` e de argv; mensagens de erro de configuração sem valores; comandos de usuários sem permissão de escrita ignorados em silêncio.
- **Não executado nesta sessão:** auditoria de vulnerabilidades das dependências (`pip-audit`) e varredura da imagem; recomenda-se rodar `uv run --with pip-audit pip-audit` (ou habilitar o Dependabot no repositório) antes de usar em produção. O quality gate do SonarCloud só roda na CI depois do primeiro push.

## 5. Observações sobre dependências

- O SDK `openai` instalado (3.57.0) usa o pacote `httpx2`; por isso o adaptador do OpenRouter recebe um `httpx2.AsyncClient`, os testes dele usam `httpx2.MockTransport`, e `httpx2` foi declarado como dependência direta. O restante do projeto usa `httpx`.
- Python 3.13 fixado em `.python-version`; `requires-python >= 3.12` mantido (NFR-11).

## 6. Lacunas conhecidas e riscos

| Lacuna | Impacto | Como fechar |
|---|---|---|
| Nenhum teste fala com o GitHub real nem com o OpenRouter real (M-003) | O formato das respostas, `git fetch` por SHA com o installation token, `resolveReviewThread` e a API de permissões só foram exercitados com respostas simuladas | Roteiro da seção 6 de `docs/demo.md`, uma vez, num repositório de teste |
| Confiabilidade de tool calling depende do modelo escolhido em `FAREJADOR_MODEL` | Modelos pequenos podem cair em `InvalidModelOutput` e gerar o aviso de falha | Escolher um modelo capaz; registrar na planilha da demo |
| `docker build` e `docker compose up` não foram executados | Erro de sintaxe do Dockerfile ou versão de imagem/uv só apareceriam no build real | `scripts/smoke_compose.sh` (ou `DOCKER="sudo docker" scripts/smoke_compose.sh`) |
| NFR-8 (qualidade da revisão) é manual | Sem número de qualidade até a demo | Planilha em `docs/demo.md` |
| Webhook real (entrega assinada pelo GitHub) | Só entregas simuladas e assinadas pelo teste | Túnel ou VPS, conferir *Recent deliveries* do App |
| SonarCloud e GitHub Actions só rodam após o primeiro push | Versões das actions e a organização do Sonar não foram validadas | Criar o projeto e o segredo `SONAR_TOKEN`, empurrar e olhar a primeira execução |

## 7. Como repetir

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy src \
  && uv run pytest --cov=farejador --cov-fail-under=80
```
