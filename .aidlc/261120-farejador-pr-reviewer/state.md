# AI-DLC State — farejador-pr-reviewer

- Intent: 261120-farejador-pr-reviewer
- Status: COMPLETE
- Profile: mvp   Depth: Standard   Tests: Standard
- Project type: greenfield   Repos: FAREJADOR
- Switches: collaborators=off reviewers=off plan_approval=on(UNIT-1 only; waived after first verified Unit by user choice) walking_skeleton=off autonomy=autonomous(granted at UNIT-1 checkpoint; halts on failures, 3.1 notes and external actions) iteration=unit-major
- Verification command: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest --cov=farejador --cov-fail-under=80` (approved 2026-11-20)
- Language: chat=pt-BR files=pt-BR
- Current: phase=construction stage=done   Updated: 2026-11-20

## Route
Legend: [x] done · [>] current · [ ] pending · [S] skipped (reason) · [!] needs redo
### Inception
- [x] 0.1–0.3 Initialization
- [x] 1.1 Intent Capture & Framing
- [x] 1.3 Feasibility & Constraints
- [x] 1.4 Scope Definition
- [S] 1.6 Rough Mockups (no UI expected; revisit if a UI/dashboard is requested)
- [S] 2.1 Reverse Engineering (greenfield)
- [x] 2.2 Practices Discovery
- [x] 2.3 Requirements Analysis
- [x] 2.4 User Stories
- [S] 2.5 Refined Mockups (no UI expected)
- [x] 2.6 Domain Design
- [x] 2.7 Units Generation
- [x] 2.8 Contract Design
- [x] 2.9 Delivery Planning
### Construction
- [x] 3.1 Functional Design (notas aprovadas: UNIT-4, 6, 7, 10)
- [S] 3.2 NFR Requirements (dobrado em design.md § 2.7 e requirements.md § 2.3)
- [S] 3.3 NFR Design (dobrado nas notas 3.1 e nos ADRs)
- [x] 3.4 Infrastructure Design (só UNIT-11: Docker, sem nuvem; aprovado)
- [x] 3.5 Code Generation (UNIT-1 a UNIT-11)
- [x] 3.6 Build and Test
- [x] 3.7 CI Pipeline
### Operations
- (none in the mvp profile)

## Units (filled by 2.7)

| Unit | Depends on | Status | Verified |
|---|---|---|---|
| UNIT-1 Foundation | — | verified | 2026-11-20, exit 0 |
| UNIT-2 State and dispatcher | UNIT-1 | verified | 2026-11-20, exit 0 |
| UNIT-3 GitHub access | UNIT-1 | verified | 2026-11-20, exit 0 |
| UNIT-4 Diff, filters, validation | UNIT-1 | verified | 2026-11-20, exit 0 |
| UNIT-5 Workspace and tools | UNIT-1, UNIT-3 | verified | 2026-11-20, exit 0 |
| UNIT-6 Agent | UNIT-1, UNIT-4, UNIT-5 | verified | 2026-11-20, exit 0 |
| UNIT-7 First review pipeline | UNIT-2, UNIT-3, UNIT-4, UNIT-5, UNIT-6 | verified | 2026-11-20, exit 0 |
| UNIT-8 Polling source | UNIT-2, UNIT-3, UNIT-7 | verified | 2026-11-20, exit 0 |
| UNIT-9 Webhook source | UNIT-2, UNIT-7 | verified | 2026-11-20, exit 0 |
| UNIT-10 Command handler | UNIT-2, UNIT-3, UNIT-6, UNIT-7 | verified | 2026-11-20, exit 0 |
| UNIT-11 Packaging and demo | UNIT-8, UNIT-9, UNIT-10 | verified (comando); build Docker pendente manual | 2026-11-20, exit 0 |

## Open assumptions
- A1 (1.1): inline review comments plus summary — confirmed: yes (1.4)
- A5 (2.2): mypy is the type checker — confirmed: yes (2.2)
- A6 (2.2): GitHub Actions CI on push to main — confirmed: yes (2.2)
- A13 (2.6): reavaliação usa modo reevaluate do AgentRunner com submit_verdicts — confirmed: yes
- A14 (2.6): FAREJADOR_MODE=both permitido, padrão um modo por processo — confirmed: yes
- A15 (2.6): execução interrompida por reinício vira failed e não é refeita — confirmed: yes
- A18-A21 (2.8): prefixo FAREJADOR_, review sempre COMMENT, sugestões em texto simples, id de modelo só exemplo — confirmed: yes
- A22-A24 (2.9): tarefas ≤ ~1h; grep em Python; testes de Docker fora do comando padrão — confirmed: yes (A23 revisada na UNIT-5: grep via git grep com timeout; ver tasks.md)
- A28-A30 (3.1 UNIT-6): comentários em inglês; tokens somam todas as chamadas; LLMClient próprio — confirmed: yes
- A31-A33 (3.1 UNIT-7): retry por comando; threads associados por autor; review só com resumo quando nada a revisar — confirmed: yes
- A34-A36 (3.1 UNIT-10): sem resposta a não autorizados; sem resposta por thread resolvido; comando durante a primeira revisão é descartado com log — confirmed: yes
- A37-A38 (3.4 UNIT-11): Docker é o único alvo; deploy em VPS manual e documentado; se o Docker não estiver disponível, validação estática — confirmed: yes
- (Construction) Riscos aceitos: sem execuções reais de GitHub/OpenRouter/Docker; pip-audit e CI ainda não rodaram; NFR-8 manual — ver verification/phase-check-construction.md
- A4 (1.4): real VPS deploy, UI and per-repo config are deferred, not excluded — confirmed: yes (1.4)
- A3 (1.3): polling mode uses the GitHub App installation token; no separate PAT mode — confirmed: yes (2.3)
- A8 (2.3): no automatic review on pushes after the first review — confirmed: yes
- A9 (2.3): command = configured trigger text in a PR comment (default @farejador), only users with write/maintain/admin — confirmed: yes
- A10 (2.3): thread resolution via GraphQL resolveReviewThread — confirmed: yes
- A11 (2.3): threads left open on purpose count as pending — confirmed: yes

## Memory candidates  (proposed, not yet approved — see protocols.md §Memory)
- C1 (language switch 2.4): arquivos do AI-DLC em pt-BR — saved as M-004
- C2 (2.8/ADR-7): comando de re-revisão é texto de gatilho em comentário, não menção real — scope guess: project
- C3 (2.2): commits direto na main + SonarCloud na CI — scope guess: project (user did not approve at 2.2)

## Notes
- 2026-11-21: o usuário removeu `docs/demo.md` e editou o README; as menções a `docs/demo.md` em tasks.md, design.md e construction/ são histórico. A planilha de avaliação manual (NFR-8) e o roteiro de verificações reais deixaram de existir no repositório.
- 2026-11-21: mensagens do Farejador no PR e prompts do agente passaram para pt-BR (supersede A28); código, logs e commits seguem em inglês. Ver design.md § Alterações pós-Construction.
- Repositório git inicializado em 2026-11-20 (branch main, origin git@github.com:luk3rr/FAREJADOR.git). Nenhum commit nem push feito. .gitignore segue a política MOINEX/MIND: versiona .aidlc/**/*.md, ignora audit.md, archive/ e screenshots/.
- Python: .python-version 3.13, requires-python >=3.12 (NFR-11). Escolha da IA conforme pedido do usuário (compatibilidade das dependências com versões recentes).
- Arquivos não criados pela IA encontrados na raiz: main.py (exemplo do PyCharm) e farejador.jpeg (logo). Não alterados.
- Idioma dos arquivos mudou para pt-BR em 2.4. Seções 1.1 a 2.4, design.md § 2.2 e memory/project.md foram traduzidas; IDs, cabeçalhos '## N.N', tags [src:] e Mermaid permanecem em inglês.
- Project root moved from `Projects/TMP` (no longer exists) to `Projects/FAREJADOR` (confirmed by the user).
- Global rules to honor in Construction: code/comments/commits in English; file header (Filename / Created on / Author) on every source file; Conventional Commits; no session IDs in commit messages.
