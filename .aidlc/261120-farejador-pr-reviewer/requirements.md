# Requirements — farejador-pr-reviewer

## Original request

Usuário (pt-BR), primeira mensagem:

> Quero criar um reviso de código relativamente simples com integração com github para revisar pull requests. Segue a ideia inicial:
>
> *Automação de Revisão de Código em Pull Requests utilizando Large Language Models*
>
> O objetivo deste trabalho prático é projetar, desenvolver e evoluir um sistema automatizado de revisão de código (Code Review) integrado nativamente ao fluxo de versionamento do GitHub. O software atuará como um assistente assíncrono de revisão em repositórios, interceptando a abertura ou atualização de Pull Requests (PRs) e utilizando Modelos de Linguagem de Grande Escala (LLMs), acessados por meio da API do OpenRouter, para analisar as diferenças (diffs) do código modificado. A meta principal não é substituir a revisão humana, mas sim atuar como uma primeira camada heurística de detecção de code smells, violações de boas práticas, problemas de manutenibilidade e potenciais introduções de dívida técnica. O sistema processará as alterações e fornecerá um feedback rápido, detalhado e contextualizado diretamente por meio de comentários automatizados nas linhas de código do PR, auxiliando a equipe de desenvolvimento a manter a saúde do projeto a longo prazo.
>
> O desenvolvimento seguirá uma abordagem iterativa e incremental, estruturada nas seguintes fases metodológicas:
>
> Fase 1 (Intercepção e Extração de Dados): Implementação do serviço backend capaz de expor um endpoint REST seguro para recebimento de webhooks do GitHub. O sistema validará a assinatura do evento de Pull Request, fará requisições à API REST do GitHub para baixar o arquivo .diff correspondente e fará o parsing das linhas adicionadas e removidas.
>
> Fase 2 (Engenharia de Prompt e Integração com LLM): Os diffs extraídos serão injetados em um prompt estruturado contendo diretrizes estritas de revisão focadas em manutenibilidade. Utilizaremos técnicas de Few-Shot Prompting para guiar a IA a ignorar falsos positivos. Este prompt será enviado à API do OpenRouter, utilizando inicialmente modelos rápidos e baixo custo (como Llama 3).
>
> Fase 3 (Feedback e Fechamento do Ciclo): A resposta em linguagem natural gerada pela IA será sanitizada, formatada em Markdown e publicada de volta no repositório utilizando a API de Issues/Comments do GitHub, vinculando o comentário ao PR que originou o evento.

Complemento (após a discussão de viabilidade):

> O nome sera FAREJADOR
> ele deve ser um agente capaz de não somente ler o texto editado, mas pegar o contextod e demais partes do código se precisar, no escopo do repositório.
> a ideia e poder rodar ele tanto localmente via polling no github como em uma vps ou nuvem
> a ideia inicialmente talvez seria algo com python
>
> Vou usar minha chave da openrouter e decidir o modelo, custo aqui não é problema, pois vou usar apenas para desenvolver e fazer uma demonstração como trabalho de uma disciplina que eu tenho

Decisões da discussão pré-Inception (do chat, confirmadas nos estágios): nome = Farejador; Python; loop agêntico com tool calling e ferramentas read-only sobre um clone raso do head do PR; duas fontes de eventos (polling local e webhook na VPS) sobre um núcleo compartilhado; OpenRouter com modelo configurável; demonstração acadêmica (custo não é preocupação); feedback com comentário-resumo mais comentários inline.

## 1.1 Intent & stakeholders

**Intenção (em termos de negócio).** O Farejador é um revisor de código automatizado de primeira passada para Pull Requests do GitHub. Ele detecta code smells, violações de boas práticas, problemas de manutenibilidade e provável dívida técnica no código alterado, e publica os achados no PR (inline nas linhas alteradas e em um resumo). Não substitui a revisão humana. [src: Original request]

**Mudança central em relação ao texto original.** O Farejador é um *agente*, não um prompt único: além do diff, ele pode ler outras partes do repositório (somente leitura, restrito ao repositório em revisão) quando precisar de contexto. [src: complemento do usuário]

**Onde roda.** Localmente via polling na API do GitHub e em uma VPS/nuvem via webhook, sobre um núcleo de revisão compartilhado. [src: complemento do usuário]

**Posicionamento.** Tratado como um projeto independente; a documentação e os artefatos não devem citar a disciplina que motivou o trabalho. [src: Q1 "considere como apenas um projeto"]

**Entrega.** Um repositório (público ou privado) e um vídeo de demonstração gravado pelo autor ao final. Sem relatório escrito por enquanto. [src: Q1]

**Medidas de sucesso.**

| ID | Medida | Como é observada |
|---|---|---|
| SM-1 | Revisa um PR real de ponta a ponta | Abrir ou atualizar um PR dispara a revisão e os comentários aparecem no GitHub sem nenhum passo manual [src: Q2] |
| SM-2 | Achados úteis e ancorados na linha certa | Comentários inline apontam para linhas realmente adicionadas do diff; poucos falsos positivos em um conjunto de PRs de teste [src: Q2] |
| SM-3 | Usa contexto além do diff | Em pelo menos alguns casos o agente lê outros arquivos do repositório e o comentário resultante mostra isso [src: Q2] |

Não selecionada como medida de sucesso: comparação de modelos (fica apenas como subproduto opcional, já que o modelo é configurável). [src: Q2]

**Partes interessadas.**

| Papel | Quem | Interesse |
|---|---|---|
| Decisor / dono / desenvolvedor / autor da demo | Lucas Araújo (usuário) | Escopo, escolha do modelo, chave do OpenRouter, demo |
| Afetados: autores de PRs | Desenvolvedores cujos PRs são revisados (repositórios do próprio usuário) | Feedback útil e com pouco ruído |
| Consultados: GitHub e OpenRouter | Serviços externos | Limites de API, termos, modelo de autenticação |

**Repositórios-alvo.** Repositórios do próprio usuário, públicos ou privados; tokens e instalação do App limitados a eles. [src: Q3]

**Restrições conhecidas até aqui.** Python; acesso ao LLM via OpenRouter com modelo escolhido pelo usuário; custo não é preocupação; trabalho individual sem prazo apertado. [src: Original request, Q4]

### Assumptions & open questions
- A1: Comentários inline de review mais um resumo geral — fechada em 1.4 (confirmada).
- A2: Repositórios privados podem ser revisados e, portanto, o código vai ao OpenRouter; o usuário aceita isso para os próprios repositórios — resolvida por C-5 em 1.3.

## 1.3 Feasibility, constraints & RAID

**Veredito: GO.** Todas as partes dependem de APIs maduras e documentadas (GitHub REST/GraphQL, API de chat do OpenRouter compatível com OpenAI e com tool calling). O ponto de maior risco é a qualidade do modelo (ancoragem de linhas, confiabilidade no uso de ferramentas), mitigado por validação da saída e por um modelo forte e configurável. [src: discussão, Q-1.3]

**Viabilidade por capacidade.**

| Capacidade | Viável? | Observações |
|---|---|---|
| Receber e verificar webhooks do GitHub (HMAC `X-Hub-Signature-256`) | Sim | Responder rápido (202) e processar em segundo plano, respeitando o timeout de ~10 s do webhook |
| Fazer polling de PRs abertos e novos head SHAs | Sim | Usa o installation token; requisições condicionais (ETag) mantêm o uso de rate limit baixo; estado guardado localmente |
| Autenticação como GitHub App | Sim | JWT assinado com a chave privada, trocado por installation tokens de curta duração; o mesmo token serve à API e ao `git clone` via HTTPS [src: Q-1.3 Auth] |
| Baixar o diff do PR e fazer parsing de linhas adicionadas/removidas | Sim | `Accept: application/vnd.github.diff`; o parser deve mapear cada linha adicionada ao número de linha do novo arquivo |
| Contexto do repositório via clone raso do head do PR | Sim | Ferramentas read-only (`read_file`, `grep`, `list_dir`) confinadas ao diretório do clone; sem execução de código do repositório [src: Q-1.3 Contexto] |
| Loop de agente com tool calling via OpenRouter | Sim, depende do modelo | Precisa de um modelo com uso de ferramentas e saída JSON confiáveis; o modelo é configurável; limites de passos e tokens delimitam o loop |
| Comentários inline de review em linhas do diff | Sim | API de Pull Request Reviews (path, line, side); âncoras inválidas são rejeitadas pelo GitHub, então os achados são validados contra o diff antes |
| Comentário-resumo | Sim | Corpo da review ou API de Issues comments no PR |
| Rodar localmente e em uma VPS | Sim | Mesma imagem Docker; o modo (polling ou webhook) é escolhido por configuração [src: Q-1.3 Deploy] |

**Registro de restrições.**

| ID | Restrição | Fonte |
|---|---|---|
| C-1 | Linguagem e runtime: Python | complemento do usuário |
| C-2 | Acesso ao LLM somente via OpenRouter; modelo escolhido pelo usuário por configuração; a chave do OpenRouter é fornecida pelo usuário e nunca guardada no repositório | Original request, complemento do usuário |
| C-3 | Autenticação por GitHub App desde o início (chave privada + installation tokens); autenticação atrás de uma interface | Q-1.3 Auth |
| C-4 | Contexto do repositório via clone raso do head do PR em diretório temporário, com ferramentas read-only confinadas a ele | Q-1.3 Contexto |
| C-5 | O código dos PRs revisados (inclusive de repositórios privados) é enviado ao OpenRouter e ao modelo escolhido; um filtro básico mascara segredos óbvios e ignora arquivos como `.env` e lockfiles; o README avisa sobre o processamento por terceiros | Q-1.3 Privacidade |
| C-6 | Empacotamento: Docker + docker-compose; o entregável é o artefato. Provisionamento e deploy real em VPS ficam fora do MVP | Q-1.3 Deploy |
| C-7 | Custo não é preocupação (só desenvolvimento e demo), mas limites de passos e tokens por revisão continuam valendo para evitar loops descontrolados | complemento do usuário |
| C-8 | Projeto individual, sem prazo apertado | Q-1.1 |
| C-9 | Nunca escrever segredos (chave do OpenRouter, chave privada do App, segredo do webhook) no repositório ou em logs | CLAUDE.md global, segurança |

**Registro RAID.**

| ID | Tipo | Item | Mitigação / responsável |
|---|---|---|---|
| R-1 | Risco | O modelo alucina números de linha ou caminhos de arquivo | Numerar as linhas do diff no prompt; validar cada achado contra as linhas adicionadas; rebaixar achados sem âncora para o resumo |
| R-2 | Risco | Modelos fracos falham em tool calling ou em saída JSON | Modelo configurável; recomendar um modelo forte; validação estrita de schema com retentativas limitadas |
| R-3 | Risco | Prompt injection vindo do diff ou de arquivos do repositório | Ferramentas read-only e confinadas; diff e arquivos passados como dados delimitados; saída sanitizada antes de publicar; o agente não tem ferramentas de escrita nem de rede |
| R-4 | Risco | O loop do agente fica longo ou caro | Máximo de passos, tokens e tempo por revisão; métricas registradas |
| R-5 | Risco | PRs grandes estouram o contexto | Revisar por arquivo ou chunk; ignorar lockfiles, gerados e binários; limitar o total de arquivos revisados e informar no resumo |
| R-6 | Risco | Revisões duplicadas (eventos repetidos, polling mais webhook, reinícios) | Idempotência por gatilho persistida em estado local; o bot ignora os próprios eventos |
| R-7 | Risco | Segredos vazam para um modelo de terceiros | Filtro de mascaramento e lista de ignorados (C-5); trade-off documentado |
| R-8 | Risco | Rate limits do GitHub durante o polling | ETag/requisições condicionais e intervalo configurável |
| A-1 | Premissa | Um GitHub App pode ser registrado na conta do usuário e instalado nos repositórios dele | Usuário; confirmar na construção |
| A-2 | Premissa | O modelo escolhido no OpenRouter suporta tool calling | Usuário; verificado na inicialização ou na primeira execução |
| D-1 | Dependência | API REST/GraphQL do GitHub, API do OpenRouter, `git` disponível na imagem de execução | A imagem Docker inclui git |
| D-2 | Dependência | Endpoint HTTPS público para o modo webhook (VPS ou túnel); o polling não precisa | Fora da automação do MVP |

### Assumptions & open questions
- A1 (de 1.1): fechada em 1.4.
- A2 (de 1.1): resolvida por C-5.
- A3: No modo polling o App está instalado nos repositórios do usuário e o installation token é usado para listar PRs; não há modo PAT separado. Confirmada em 2.3.

## 1.4 Scope        (in / out / MVP boundary)

**Formato do feedback (fecha A1).** Uma review do GitHub por execução: comentários inline em linhas adicionadas mais um corpo de resumo. Achados sem âncora válida no diff vão para o resumo. [src: Q-1.4 Feedback]

**Dentro do escopo (MVP).**

| ID | Item | Fonte |
|---|---|---|
| S-1 | Núcleo de revisão: download e parsing do diff, clone raso do head do PR, loop de agente com ferramentas read-only do repositório, achados estruturados e validados, formatação e sanitização em Markdown | Original request, Q-1.3 |
| S-2 | Modo polling: lista PRs abertos dos repositórios onde o App está instalado e revisa novos head SHAs (modo local) | Q-1.4 MVP |
| S-3 | Modo webhook: endpoint HTTPS que verifica a assinatura HMAC, responde 202 e processa em segundo plano (modo VPS) | Q-1.4 MVP |
| S-4 | Estado local e idempotência por gatilho; o bot ignora os próprios eventos | Q-1.4 MVP, R-6 |
| S-5 | Prompt de revisão estruturado com exemplos few-shot para reduzir falsos positivos; validação de todo achado contra o diff | Q-1.4 MVP, R-1 |
| S-6 | Autenticação como GitHub App atrás de uma interface de autenticação (JWT para installation token) | C-3 |
| S-7 | Cliente OpenRouter com modelo configurável, mais orçamentos de passos, tokens e tempo por revisão | C-2, C-7 |
| S-8 | Mascaramento de segredos e lista de ignorados para arquivos sensíveis e de baixo valor (lockfiles, gerados, binários) | C-5, R-5 |
| S-9 | Imagem Docker e docker-compose, com o modo selecionado por configuração; README de instalação (registro do GitHub App, chave do OpenRouter, execução dos dois modos) | C-6 |

**Fora do escopo.**

| ID | Item | Fonte |
|---|---|---|
| X-1 | Aplicar correções automaticamente: o Farejador só comenta, nunca altera código nem faz push | Q-1.4 Fora |
| X-2 | Substituir a revisão humana ou bloquear merges (sem required status checks) | Original request |

**Não comprometido para o MVP (adiado, salvo pedido).** Deploy e provisionamento real em VPS (já limitado ao artefato Docker por C-6), interface web ou dashboard (1.6 e 2.5 pulados), arquivos de configuração por repositório e operação multi-conta/multi-tenant, ferramentas de comparação de modelos. Estes não foram marcados como exclusões explícitas, então ficam como "depois" e não como "nunca"; o MVP usa apenas configuração global por variáveis de ambiente. [src: Q-1.4 Fora]

**Limite do MVP.** O MVP está pronto quando um PR aberto ou atualizado em um dos repositórios do usuário é revisado de ponta a ponta nos modos polling e webhook, com comentários inline ancorados em linhas adicionadas reais e um resumo, usando contexto do repositório além do diff em pelo menos alguns casos (SM-1..3). [src: 1.1]

**Backlog priorizado (MoSCoW).**

| Prioridade | Itens |
|---|---|
| Must | S-1, S-2, S-4, S-5, S-6, S-7, S-8 |
| Must (segundo modo) | S-3 |
| Should | S-9 empacotamento e README |
| Could | Configuração por repositório, filtros de caminho, relatório simples de métricas (passos, tokens, latência por revisão) |
| Won't (agora) | Correção automática, UI, multi-tenant, bloqueio de merge |

### Assumptions & open questions
- A1: fechada (inline mais resumo).
- A4: Deploy real em VPS, UI e configuração por repositório estão adiados, não excluídos; o usuário não os marcou como fora do escopo. Confirmada no gate de 1.4.

## 2.3 Requirements

### Ciclo de vida da revisão (resumo)

1. **Primeira revisão (automática):** quando um PR não-draft é aberto, ou um PR draft fica pronto para revisão, e o Farejador ainda não o revisou. [src: Q-2.3 Gatilhos]
2. **Interações posteriores (somente sob demanda):** depois da primeira revisão, novos commits não disparam nada sozinhos. Alguém menciona o Farejador em um comentário do PR. O Farejador então (a) reavalia seus próprios threads de review ainda abertos contra o head atual e resolve aqueles cujo problema foi corrigido; (b) se nenhum thread do Farejador permanecer pendente depois disso, executa uma nova review do head atual; caso contrário, responde com um status curto e não inicia nova review. [src: Q-2.3 Re-revisão]

### Functional

| ID | Requisito | Justificativa | Critérios de aceitação | Prioridade | Fonte |
|---|---|---|---|---|---|
| FR-1 | O sistema deve expor um endpoint HTTPS que recebe webhooks do GitHub e rejeita qualquer requisição cujo HMAC `X-Hub-Signature-256` esteja ausente ou inválido | Só o GitHub pode disparar revisões | Dado uma assinatura válida, quando um evento chega, então é aceito com 202; dado uma assinatura ausente ou errada, então é rejeitado com 401 e nada é processado | Must | [src: S-3] |
| FR-2 | O sistema deve oferecer um modo polling que lista, para cada repositório onde o GitHub App está instalado, PRs abertos e novos comentários de PR, e os transforma nas mesmas solicitações de revisão do modo webhook | Uso local sem endpoint público | Dado o modo polling e um novo PR não-draft, quando um ciclo de polling roda, então uma solicitação de revisão é produzida; rodar outro ciclo sem mudanças não produz nenhuma | Must | [src: S-2, Q-2.3] |
| FR-3 | O sistema deve iniciar uma primeira revisão automática somente para PRs não-draft nos eventos `opened`, `reopened` (se nunca revisado) e `ready_for_review`; PRs draft são ignorados até ficarem prontos; pushes posteriores não devem disparar revisões | Evitar ruído em trabalho em andamento e execuções repetidas | Dado um PR draft, então nenhuma revisão; dado que ele fica pronto, então uma revisão; dado um novo push após a primeira revisão, então nenhuma revisão | Must | [src: Q-2.3 Gatilhos, Re-revisão, A8] |
| FR-4 | O sistema deve registrar cada gatilho tratado (revisão por `(repo, PR, head SHA)`, comando por id de comentário) em estado local persistente e nunca processar o mesmo gatilho duas vezes, inclusive após reinício | Evitar duplicidade entre webhook, polling e reinícios | Dado o mesmo gatilho entregue duas vezes ou o processo reiniciado, então exatamente uma revisão ou resposta é publicada | Must | [src: S-4, R-6] |
| FR-5 | O sistema deve ignorar eventos e comentários criados pelo próprio bot Farejador | Evitar loops de feedback | Dado um comentário do bot, então nenhum processamento acontece | Must | [src: R-6] |
| FR-6 | O sistema deve baixar o diff do PR e fazer parsing em arquivos, hunks e linhas adicionadas, removidas e de contexto, mantendo o número de linha no novo arquivo de cada linha adicionada | Os achados precisam se ancorar em linhas reais | Dado um diff de teste, então cada linha adicionada mapeia para o número correto no novo arquivo e cada linha removida para o do arquivo antigo | Must | [src: S-1] |
| FR-7 | O sistema deve ignorar arquivos que sejam lockfiles, gerados, binários, vendorizados ou que casem com a lista de ignorados, e informar no resumo quais arquivos foram ignorados e por quê | Reduzir ruído e custo, proteger arquivos sensíveis | Dado um PR com `package-lock.json` e `.env`, então nenhum dos dois é enviado ao modelo e ambos aparecem como ignorados | Must | [src: S-8, C-5] |
| FR-8 | O sistema deve fazer um clone raso do commit head do PR em um diretório temporário usando o installation token e apagá-lo ao final | Contexto do repositório além do diff | Dada uma revisão, então o clone existe apenas durante a execução e o diretório é removido em caso de sucesso e de falha | Must | [src: C-4] |
| FR-9 | O sistema deve dar ao agente apenas ferramentas read-only confinadas ao clone: `read_file(path, start, end)`, `grep(pattern, path?)`, `list_dir(path)`, com limites de tamanho de saída | Contexto sem risco | Dado um caminho com `..` ou um symlink que escapa do clone, então a ferramenta recusa; dado um arquivo enorme, então a saída é truncada e informa isso | Must | [src: S-1, R-3] |
| FR-10 | O sistema deve executar um loop de agente contra o OpenRouter usando um modelo configurável e um prompt com diretrizes estritas de manutenibilidade, diff delimitado como dado e exemplos few-shot que mostram o que não sinalizar | Valor central; reduzir falsos positivos | Dado um modelo mockado, então o loop executa chamadas de ferramenta, devolve os resultados e termina com uma resposta estruturada final ou uma parada por orçamento | Must | [src: S-5, S-7] |
| FR-11 | O sistema deve impor orçamentos por revisão (máximo de passos de ferramenta, tokens, tempo de relógio e arquivos revisados) com os padrões do NFR-6 e deve parar com elegância, informando no resumo, quando um deles for atingido | Limitar custo e latência | Dado um orçamento de 2 passos e um modelo que pede uma 3ª chamada de ferramenta, então a execução termina com resultado parcial e uma nota | Must | [src: S-7, R-4, Q-2.3 Limites] |
| FR-12 | O sistema deve exigir que a resposta final do modelo seja uma lista JSON de achados (arquivo, linha, severidade, categoria, mensagem, sugestão opcional) validada por schema, com número limitado de retentativas em caso de saída inválida | Saída verificável por máquina | Dado um JSON inválido, então ocorrem até 2 retentativas e depois vale o caminho de falha (FR-20) | Must | [src: S-5, R-2] |
| FR-13 | O sistema deve validar cada achado contra o diff: um achado só é publicado inline se seu arquivo e linha forem uma linha adicionada do diff atual; caso contrário, vai para o resumo | Evitar âncoras alucinadas e rejeições da API | Dado um achado em uma linha de contexto ou em arquivo inexistente, então ele aparece no resumo e não inline | Must | [src: S-5, R-1] |
| FR-14 | O sistema deve sanitizar e formatar o texto do modelo como Markdown antes de publicar: neutralizar `@mentions`, remover HTML bruto e conteúdo ativo, limitar tamanhos e escapar fences inseguros | Publicação segura de texto não confiável | Dada uma saída do modelo com `@alguem`, `<script>` ou uma mensagem muito longa, então o texto publicado não contém as partes ativas e respeita os limites | Must | [src: Original request Fase 3, R-3] |
| FR-15 | O sistema deve publicar cada revisão como uma única review do GitHub com comentários inline em linhas adicionadas válidas e um corpo de resumo que informa o SHA do commit revisado, o número de achados por severidade, os arquivos ignorados e qualquer limite de orçamento atingido | Fecha o ciclo | Dados achados, então uma review é criada com N comentários inline e um resumo; sem achados, então um resumo curto diz que nada relevante foi encontrado | Must | [src: Q-1.4 Feedback] |
| FR-16 | O sistema deve aceitar um comando vindo de um comentário de PR que mencione o Farejador (padrão `@farejador`, configurável), somente de usuários com permissão write, maintain ou admin no repositório; comentários de outros são ignorados | Re-revisão sob demanda e controlada | Dada uma menção por um usuário apenas com leitura, então nada acontece; por um usuário com escrita, então o comando é processado | Must | [src: Q-2.3 Re-revisão, A9] |
| FR-17 | Em um comando, o sistema deve primeiro reavaliar todos os threads de review abertos criados pelo Farejador contra o head atual, usando o agente com o texto do thread e o código atual, e resolver os threads cujo problema foi corrigido, opcionalmente adicionando uma nota curta | Fechar comentários corrigidos | Dado um thread cuja linha sinalizada foi corrigida em um commit posterior, então o thread é resolvido; dado um ainda válido, então permanece aberto | Must | [src: Q-2.3 Re-revisão] |
| FR-18 | Após a reavaliação do FR-17, se nenhum thread do Farejador permanecer aberto, o sistema deve executar uma nova review do head atual; se algum permanecer aberto, deve responder com um status curto (contagem de resolvidos e pendentes) e não iniciar nova review | Regra de re-revisão definida | Dado 0 pendentes após a reavaliação, então uma nova review é publicada; dado 2 pendentes, então apenas uma resposta de status é publicada | Must | [src: Q-2.3 Re-revisão] |
| FR-19 | O sistema deve mascarar segredos óbvios (chaves privadas, tokens de API, senhas em atribuições) em qualquer texto enviado ao modelo, além da lista de ignorados | Trade-off de privacidade aceito | Dado um diff com um padrão de token, então o prompt do modelo contém um placeholder mascarado | Must | [src: S-8, C-5] |
| FR-20 | Em erros do modelo, saída inválida ou retentativas esgotadas, o sistema deve registrar o erro em log e publicar um aviso curto no PR, e deve marcar o gatilho como falho para não repeti-lo em loop | Falha visível sem loops | Dado um modelo que sempre falha, então exatamente um aviso é publicado e o gatilho é marcado como falho | Must | [src: Q-2.3 Falhas] |
| FR-21 | O sistema deve se autenticar como GitHub App (assinar um JWT com a chave privada, obter installation tokens, renovar antes de expirar) atrás de uma interface de autenticação | Modelo de autenticação escolhido | Dado um token expirado, então um novo é obtido de forma transparente | Must | [src: C-3, S-6] |
| FR-22 | O sistema deve ler todas as configurações de variáveis de ambiente (modo, id e local da chave do App, segredo do webhook, chave e modelo do OpenRouter, orçamentos, intervalo de polling, texto do gatilho, padrões de ignorados) e falhar logo na inicialização com mensagem clara quando uma obrigatória estiver ausente | Mesma imagem para local e VPS | Dada a chave do OpenRouter ausente, então a inicialização falha citando a variável | Must | [src: S-9, C-2] |
| FR-23 | O sistema deve emitir logs estruturados por revisão com PR, SHA, modo, passos, tokens, duração, número de achados e resultado, sem segredos | Depuração e evidência para a demo | Dada uma revisão, então um registro de log resumido contém esses campos | Should | [src: S-1, C-9] |
| FR-24 | O sistema deve entregar um Dockerfile e uma configuração docker-compose que executem qualquer um dos modos, além de um README com registro do GitHub App, configuração do OpenRouter e como executar os dois modos | Entrega e demo | Dados os passos do README, então os dois modos iniciam a partir da mesma imagem | Should | [src: S-9] |

### Non-functional

| ID | Categoria | Meta mensurável | Verificação | Fonte |
|---|---|---|---|---|
| NFR-1 | Segurança (webhook) | HMAC comparado em tempo constante; assinatura inválida ou ausente rejeitada com 401 antes de qualquer processamento | Testes unitários com assinaturas válida, inválida e ausente | [src: FR-1] |
| NFR-2 | Segurança (ferramentas do agente) | 100% das tentativas de path traversal e de fuga por symlink no conjunto de testes das ferramentas são recusadas; as ferramentas não expõem escrita, rede nem execução | Testes unitários da camada de ferramentas; revisão da lista de ferramentas | [src: FR-9, R-3] |
| NFR-3 | Segurança (segredos) | Nenhuma chave do OpenRouter, chave privada do App ou segredo do webhook aparece em logs, comentários publicados ou no repositório | Teste em que a saída de logs e comentários de uma execução com segredos sentinela não contém nenhum | [src: C-9] |
| NFR-4 | Confiabilidade | O mesmo gatilho nunca produz duas revisões, nem após reinício do processo | Teste de integração reiniciando o armazenamento de estado entre duas entregas | [src: FR-4] |
| NFR-5 | Desempenho (webhook) | O webhook responde em menos de 2 s independentemente da duração da revisão | Teste de que o handler retorna antes de a revisão terminar | [src: FR-1, timeout de webhook do GitHub] |
| NFR-6 | Limites de custo e latência | Padrões: 15 passos de ferramenta, 200k tokens, 300 s de tempo de relógio, 40 arquivos revisados por revisão; todos sobrescritíveis por variáveis de ambiente; exceder qualquer um encerra a execução com elegância | Testes com orçamentos reduzidos | [src: Q-2.3 Limites, FR-11] |
| NFR-7 | Correção das âncoras | 100% dos comentários inline publicados apontam para arquivo e linha que sejam linha adicionada do diff | Testes baseados em propriedades sobre diffs de teste; achados inválidos vão para o resumo | [src: FR-13] |
| NFR-8 | Qualidade da revisão (qualitativa) | Em um conjunto pequeno de PRs de demo com smells plantados e PRs limpos, a maioria dos smells plantados é reportada e PRs limpos geram poucos ou nenhum achado; avaliado manualmente pelo autor | Avaliação manual durante a demo, resultados anotados no README | [src: SM-2] |
| NFR-9 | Rate limits | Intervalo de polling padrão de 60 s, configurável; usa requisições condicionais para que recursos inalterados não consumam o rate limit primário | Teste de que um polling repetido envia validadores e trata 304 | [src: R-8] |
| NFR-10 | Manutenibilidade | `ruff` e `mypy` passam sem erros; cobertura de testes de ao menos 80% nos módulos do núcleo; o quality gate do SonarCloud passa | Execução de CI no push para a main | [src: práticas 2.2 A5, A6, M-002] |
| NFR-11 | Portabilidade | Uma imagem Docker executa os dois modos em Linux apenas com variáveis de ambiente e arquivos montados; Python 3.12 ou superior | Build e inicialização dos dois modos via compose | [src: C-6, FR-22] |
| NFR-12 | Privacidade | Documentado que o código é enviado a terceiros; lista de ignorados e mascaramento ativos por padrão | Verificação do README e testes de FR-7 e FR-19 | [src: C-5] |

### Constraints · Out of scope · Glossary

**Restrições.** Valem C-1 a C-9 de § 1.3; valem as práticas de design.md § 2.2 (uv, ruff, mypy, pytest com mocks, SonarCloud, commits na main, código em inglês e cabeçalho em todo arquivo-fonte).

**Fora do escopo.** X-1, X-2 de § 1.4; além disso: reagir a comentários de review escritos por humanos em conversa livre, revisar eventos que não sejam de PR e disparo automático a cada push depois da primeira revisão.

**Glossário.**

| Termo | Significado |
|---|---|
| Review | Uma review do GitHub criada pelo Farejador: comentários inline mais um corpo de resumo |
| Finding | Um problema reportado pelo modelo: arquivo, linha, severidade, categoria, mensagem |
| Thread | Uma conversa de review do GitHub em uma linha; resolvida quando o problema é corrigido |
| Trigger | Um evento que pode causar trabalho: evento de primeira revisão ou um comentário de comando |
| Command | Um comentário de PR que menciona o Farejador (padrão `@farejador`) escrito por um usuário com acesso de escrita |
| Head SHA | O commit na ponta da branch do PR no momento de um gatilho |
| Installation token | Token de curta duração do GitHub App usado em chamadas de API e no clone |
| Ignore list | Padrões de arquivos nunca enviados ao modelo (lockfiles, gerados, binários, `.env` e similares) |

### Assumptions & open questions
- A3 (de 1.3): o polling usa o installation token do App; sem modo PAT. Confirmada no gate de 2.3.
- A8: A primeira revisão roda automaticamente apenas na abertura ou ao ficar pronto para revisão; não há revisão automática em pushes posteriores, então eventos `synchronize` são ignorados quando já existe uma revisão. Confirmada.
- A9: O comando é um comentário contendo o texto de gatilho configurado (padrão `@farejador`), e não uma menção real do GitHub (GitHub Apps não podem ser mencionados como usuários); só usuários com permissão write, maintain ou admin podem usá-lo. Confirmada.
- A10: A resolução de threads usa a mutation GraphQL `resolveReviewThread` do GitHub, que exige a permissão `pull requests: write` do App; o REST não tem equivalente. Confirmada.
- A11: No FR-18, "pendente" significa threads criados pelo Farejador que continuam sem resolução após a reavaliação, inclusive os que o usuário deixou abertos de propósito. Confirmada.

## 2.4 User stories

### Personas

| Persona | Descrição | Objetivos principais |
|---|---|---|
| Pat, autor do PR | Desenvolvedor que abre PRs em um repositório onde o Farejador está instalado | Feedback rápido, útil e com pouco ruído antes da revisão humana |
| Morgan, mantenedor | Pessoa com acesso de escrita que é dona do repositório e do processo de revisão | Controlar quando o Farejador roda de novo, manter os threads limpos, manter o código razoavelmente protegido |
| Operador | Lucas, que instala e executa o Farejador localmente ou em uma VPS | Instalação simples, credenciais seguras, mesmo comportamento nos dois modos, evidência para a demo |

### US-1 Primeira revisão no meu PR (FR-3, FR-6, FR-15)  Persona: Pat
Como autor de PR, quero que meu PR recém-aberto ou marcado como pronto seja revisado automaticamente, para receber feedback antes de um humano olhar.
- AC1: Dado que um PR não-draft é aberto, quando o Farejador está em execução, então uma review (comentários inline mais um resumo com o SHA do commit revisado) aparece no PR.
- AC2: Dado que um PR draft é aberto, então nada é publicado; dado que ele é marcado como pronto, então uma review é publicada.
- AC3: Dado que eu faço novos pushes após a primeira revisão, então o Farejador não publica nada sozinho.

### US-2 Comentários inline nas linhas certas (FR-12, FR-13, FR-14, FR-15)  Persona: Pat
Como autor de PR, quero cada achado anexado à linha alterada exata a que se refere, para agir sobre ele sem precisar procurar.
- AC1: Dado um achado em uma linha adicionada, então ele é publicado como comentário inline nessa linha.
- AC2: Dado um achado cuja linha não é uma linha adicionada, então ele aparece no resumo e não inline.
- AC3: Dado um texto do modelo contendo `@alguem` ou HTML, então o comentário publicado o neutraliza.

### US-3 Achados informados pelo resto do repositório (FR-8, FR-9, FR-10)  Persona: Pat
Como autor de PR, quero que o revisor olhe outros arquivos do repositório quando necessário, para que os comentários considerem como o código alterado é usado.
- AC1: Dada uma função alterada usada em outro lugar, quando o agente precisa de contexto, então ele lê ou busca em outros arquivos do repositório e o comentário reflete isso.
- AC2: Dada uma solicitação de ferramenta fora do diretório do repositório, então ela é recusada.
- AC3: Dado que a execução termina, então o diretório clonado é apagado.

### US-4 Pouco ruído (FR-7, FR-10)  Persona: Pat
Como autor de PR, quero que lockfiles, arquivos gerados e arquivos com segredos fiquem de fora e que não-problemas óbvios não sejam sinalizados, para que os comentários valham a leitura.
- AC1: Dado um PR que altera `package-lock.json` e `.env`, então nenhum dos dois é revisado e ambos são listados como ignorados no resumo.
- AC2: Dado um diff limpo que corresponde aos padrões few-shot de "não sinalizar", então a revisão não reporta nenhum achado para ele.

### US-5 Falhas limitadas e visíveis (FR-11, FR-20)  Persona: Operador
Como operador, quero que cada revisão pare dentro dos limites configurados e que as falhas sejam visíveis, para que custo e latência sejam previsíveis e nada entre em loop.
- AC1: Dado que um orçamento (passos, tokens, tempo ou arquivos) é atingido, então a execução para com elegância e o resumo informa qual limite foi alcançado.
- AC2: Dado que o modelo continua falhando ou devolve saída inválida, então, após até 2 retentativas, um aviso curto é publicado no PR e o gatilho é marcado como falho.

### US-6 Tratamento mais seguro do meu código (FR-19)  Persona: Morgan
Como mantenedor, quero que segredos óbvios sejam mascarados antes de o código chegar ao modelo, para reduzir o risco de vazar credenciais.
- AC1: Dado um diff contendo um padrão de token ou de chave privada, então o prompt do modelo contém um placeholder mascarado no lugar.

### US-7 Fechar threads corrigidos sob pedido (FR-16, FR-17)  Persona: Morgan
Como mantenedor, quero mencionar o Farejador em um comentário do PR e ele resolver os próprios threads cujo problema foi corrigido, para que o PR mostre só o que resta.
- AC1: Dado que um usuário com acesso de escrita menciona `@farejador`, então o comando é processado; dado um usuário sem acesso de escrita, então é ignorado.
- AC2: Dado um thread do Farejador cujo problema foi corrigido em um commit posterior, então o thread é resolvido.
- AC3: Dado um thread cujo problema ainda existe, então ele permanece aberto.

### US-8 Nova revisão só quando não há pendências (FR-16, FR-18)  Persona: Morgan
Como mantenedor, quero uma nova revisão somente depois que os threads anteriores do Farejador estiverem resolvidos, para não receber comentários duplicados ou conflitantes.
- AC1: Dado que nenhum thread do Farejador permanece aberto após a reavaliação, então uma nova review do head atual é publicada.
- AC2: Dado que um ou mais threads do Farejador permanecem abertos, então apenas uma resposta de status curta (contagens de resolvidos e pendentes) é publicada.

### US-9 Modo webhook em uma VPS (FR-1, FR-4, FR-5)  Persona: Operador
Como operador, quero que o Farejador reaja a webhooks do GitHub de forma segura, para que as revisões comecem imediatamente em um servidor.
- AC1: Dada uma assinatura válida, então o evento é aceito com 202 e processado em segundo plano.
- AC2: Dada uma assinatura ausente ou inválida, então é rejeitado com 401 e nada executa.
- AC3: Dada a mesma entrega duas vezes ou um reinício, então exatamente uma review é publicada; eventos do próprio bot são ignorados.

### US-10 Modo polling local (FR-2, FR-4)  Persona: Operador
Como operador, quero executar o Farejador na minha máquina sem endpoint público, para desenvolver e demonstrar localmente.
- AC1: Dado um novo PR não-draft ou um novo comentário de comando em um repositório instalado, quando um ciclo de polling roda, então ele produz a mesma solicitação de revisão do modo webhook.
- AC2: Dado que nada mudou, então o próximo ciclo de polling não produz nada e usa requisições condicionais.

### US-11 Conectar por GitHub App e configuração (FR-21, FR-22)  Persona: Operador
Como operador, quero autenticação por GitHub App e todas as configurações em variáveis de ambiente, para que a instalação seja igual em qualquer lugar e os segredos fiquem fora do repositório.
- AC1: Dados o id do App, a chave privada e a instalação, então chamadas de API e clones usam installation tokens de curta duração renovados automaticamente.
- AC2: Dado que uma configuração obrigatória está ausente, então a inicialização falha citando-a.

### US-12 Empacotar, executar e observar (FR-23, FR-24)  Persona: Operador
Como operador, quero uma imagem Docker, um arquivo compose, um README e logs por revisão, para executar os dois modos e mostrar evidências na demo.
- AC1: Dados os passos do README, então os dois modos iniciam a partir da mesma imagem.
- AC2: Dada uma revisão finalizada, então um registro de log estruturado mostra PR, SHA, modo, passos, tokens, duração, achados e resultado, sem segredos.

### Matriz de cobertura (FR para história)

| FR | Histórias | FR | Histórias |
|---|---|---|---|
| FR-1 | US-9 | FR-13 | US-2 |
| FR-2 | US-10 | FR-14 | US-2 |
| FR-3 | US-1 | FR-15 | US-1, US-2 |
| FR-4 | US-9, US-10 | FR-16 | US-7, US-8 |
| FR-5 | US-9 | FR-17 | US-7 |
| FR-6 | US-1 | FR-18 | US-8 |
| FR-7 | US-4 | FR-19 | US-6 |
| FR-8 | US-3 | FR-20 | US-5 |
| FR-9 | US-3 | FR-21 | US-11 |
| FR-10 | US-3, US-4 | FR-22 | US-11 |
| FR-11 | US-5 | FR-23 | US-12 |
| FR-12 | US-2 | FR-24 | US-12 |

### Assumptions & open questions
- A12: As personas Pat, Morgan e Operador são papéis de trabalho, não pessoas reais; Morgan e Pat podem ser a mesma pessoa nos repositórios do próprio usuário.
- Os NFRs não são cobertos por histórias; são atribuídos a Units e a Definições de Pronto em 2.7.
