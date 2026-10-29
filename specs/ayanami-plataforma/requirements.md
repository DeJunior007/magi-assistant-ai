# Requisitos — Ayanami plataforma (o node 2 inteiro como MCP/cérebro)

Fonte: pedido do Pedro de 2026-10-28 ("usar o máximo potencial da VPS como MCP/cérebro da Ayanami",
depois de derrubar o Minecraft) e os brainstorms em [brainstorm/](brainstorm/): contexto,
1 MCP de programação, 2 serviços pessoais, 3 infra/ops e 4 Condessa esperta. Este arquivo é o
**PRD**. A arquitetura está em [design.md](design.md). Contratos e tarefas virão em `spec.md`/`tasks.md`.
Constrói **sobre** o SDD [ayanami-central](../ayanami-central/requirements.md) (API, fila procrastinate,
workers, MCP em `/mcp/`, backups Y4.2, vigia, modo nuvem, SSE/Web Push) e sobre o ntfy do SDD
[condessa-celular](../condessa-celular/design.md) §6. Não repete o que já está lá.

Critérios em EARS, como na central:
- **X DEVE …**: vale sempre. **QUANDO** gatilho, **X DEVE** …: reação a um evento.
- **ENQUANTO** estado, **X DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

Numeração: `R<frente>.<n>`, com frentes F0–F4. As decisões deste SDD são `D1…D14`. As da central
aparecem como "central D8", "central D11" etc.

## Glossário

| Termo | Significado |
| --- | --- |
| Perfil "node 2 inteiro" | Novo override do Compose que substitui o perfil enxuto `compose.node2.yml` (Y1.0b: núcleos 6–7, ~6,4 GiB), feito para quando o node 2 era dividido com o Minecraft. |
| Janela noturna | Horário em que o lote pesado pode usar até 6 vCPU (padrão 00h–07h, D3). |
| Lote | Trabalho não urgente agendado na janela: LLM local, restore do sandbox, render de áudio, indexação de código. |
| `llm-local` | Container `llama-server` (llama.cpp) que sobe só na janela (D2). Reabre a central D8, opção (b). |
| `sandbox-db` | Postgres no node 2 que recebe a cópia **mascarada** dos bancos de produção do node 1. |
| Porta única só-leitura | Acesso do node 2 ao node 1 por usuário `ayanami-ro` com verbos em lista branca e papel Postgres `ayanami_ro` (D5). |
| Sessões dev | Diário das sessões do Claude Code (brainstorm 1, ideia 2). Tabela `sessoes_dev`, para não colidir com o **diário da Condessa** (tabela `diario`, F3). |
| Incidente | Um ou mais alertas agrupados pela Ayanami (deduplicados e correlacionados), com início, fim e resumo. |

## Problema

1. O node 2 está quase ocioso: a Ayanami usa ~320 MiB e ~3% de CPU de 8 vCPU e 23 GiB. O perfil
   enxuto ainda a confina aos núcleos 6–7, mas desde 2026-10-28 a VPS é toda dela.
2. **O node 1 (produção de clientes) não tem backup** nem alerta de disco/fila. Hoje o Pedro só
   descobre uma queda quando o cliente reclama.
3. O Claude Code gasta dezenas de milhares de tokens em `gh run view --log`, só enxerga o repo
   aberto, não lembra das sessões anteriores e não consulta produção sem SSH.
4. A Condessa é reativa. Nada é preparado enquanto o Pedro dorme: briefing, aula, pesquisa,
   audiolivro.
5. Busca web, notícias e resumo dependem de APIs pagas dentro do teto de US$ 5/mês.

## Objetivo

A Ayanami vira o **único endpoint MCP** do Pedro e o cérebro da Condessa, ocupando o node 2 com
orçamento explícito de RAM e CPU por serviço:
- **de dia**, responde rápido (voz, MCP, alertas) com núcleos reservados;
- **de madrugada**, usa a máquina inteira para o lote (backup e cópia de produção, LLM local, áudio,
  indexação) e deixa tudo pronto às 07h;
- sem nada público, só leitura no node 1 e custo novo de API ≤ US$ 1/mês (D4).

## Escopo

**Dentro** (cinco frentes):
- **F0 base:** perfil "node 2 inteiro", orçamento por serviço, prioridades de CPU, janela noturna,
  ntfy no perfil (o do condessa-celular), endpoint MCP único com escopos novos e auditoria, e
  gateway opcional para sub-servidores MCP de terceiros.
- **F1 dev/MCP:** `ci_*` (CI e deploys de todos os repos), sessões dev do Claude Code, `codigo_*`
  (busca semântica multi-repo sobre o espelho dos repos), `sql_ler` (cópia mascarada da produção),
  `prod_erros` (Bugsink, opcional).
- **F2 ops:** backup por pull do Postgres do node 1 com teste de restore, Gatus, Beszel, alerta
  inteligente (incidentes), "SRE de bolso" (`ops_*`) e ping externo (vigia do vigia).
- **F3 Condessa noturna:** bom dia pré-renderizado, diário da Condessa, aula do dia, pesquisa
  noturna e audiolivro pré-renderizado.
- **F4 serviços pessoais:** SearXNG, Miniflux, LLM local na janela noturna e e-mail IMAP só leitura.

**Fora de escopo** (registrado para não voltar sem decisão):
- torrent e *arr, Jellyfin. Home Assistant na VPS (se houver casa além das TVs, o HA fica em casa).
  Immich, por ora (disco e backup). n8n e Node-RED (a fila procrastinate já é o orquestrador).
- Paperless-ngx, Radicale, Audiobookshelf, Syncthing, Vaultwarden, Memos, Actual/Firefly, Karakeep,
  Changedetection: ficam para depois, sob demanda. O orçamento deixa folga para eles.
- Condessa Engine e revisor noturno com `claude -p` (são do SDD `condessa-engine`), `sandbox_executar`,
  Playwright headless, `docs_*`, `laravel_ops`.
- Logs centralizados (Loki, VictoriaLogs), Prometheus/VictoriaMetrics/Grafana, Uptime Kuma, status
  page pública, registry Zot, Trivy, SOPS e standby frio do MultiVideos: todos ficam fora desta rodada.
- **Qualquer escrita no node 1.** Nenhum verbo de escrita, nem "reiniciar worker".

## Duplicatas resolvidas entre os brainstorms

| Aparece em | Fica como | Por quê |
| --- | --- | --- |
| Gatus (2 #4, 3 #2), `site_*` (1 #10) | **Gatus** único, em F2 | YAML versionado, ~40 MiB |
| LLM local (2 #5, premissas do 4, central D8) | **`llm-local`** único (F4), consumido por F3 e F2 | um container, uma janela |
| SearXNG (2 #2), `web_*` (1 #19), busca da pesquisa (4 #4) | **SearXNG** (F4) | a pesquisa noturna o usa |
| Backup do node 1 (3 #1) e `sql_ler` (1 #4) | **um pull só por noite**: o mesmo dump vai ao restic e ao `sandbox-db` | o restore diário é o teste de restore |
| GlitchTip+Loki (1 #5) e Bugsink (3 #12) | **Bugsink** (opcional, D8) | 1 container, ~300 MiB |
| `ci_*` (1 #1), rastreador de deploys (3 #10), `ops.ci` (3 #5) | `ci_*` (F1) consumido por `ops_status` | uma coleta |
| Espelho Forgejo (1 #13) e espelho noturno (3 #7) | `git clone --mirror` num volume (F1), sem Forgejo | serve `codigo_*` e o backup |
| Beszel (3 #3), `metricas_*` (1 #18), VM+Grafana (3 #17) | **Beszel** (F2) | o mais leve |
| Vigia do node 1 (4 #17), SRE de bolso (3 #5) | `ops_*` + incidentes (F2) | — |
| ntfy (2 #1) | o do [condessa-celular §6](../condessa-celular/design.md) | não duplicar |
| "diário" (1 #2 e 4 #2) | `sessoes_dev` (F1) ≠ `diario` (F3) | nomes distintos |

## Usuários e cenários

- **Pedro programando:** "por que o CI do MultiVideos quebrou?" recebe 1–2k tokens com o step,
  o erro e o comando de reprodução. "Já fiz upload em chunks em outro projeto?" volta com trecho e
  caminho. "Quantos posts falharam ontem?" vira um `SELECT` na cópia mascarada, sem SSH.
- **Pedro fora do PC:** o celular recebe "gold-crm fora há 3 min, começou 2 min depois do deploy
  abc123". Quando o problema some, chega "voltou, 7 min fora".
- **Pedro acordando:** a Condessa toca o bom dia já renderizado: clima, duas notícias, servidores
  e backup ok, aula com 5 frases dele, a pesquisa de ontem pronta no card.
- **Condessa:** responde "o que a gente falou semana passada sobre X?" pelo diário. "Tá tudo de pé?"
  responde pelo `ops_status`.

## Critérios de sucesso

1. Em repouso, a plataforma inteira fica ≤ 3 GiB de RAM. A soma dos `mem_limit` fica ≤ 18 GiB e
   sobram ≥ 5 GiB de RAM física mais o swap (tabela de orçamento).
2. De dia, com lote rodando, a latência do `/v1/turno` e das tools MCP não piora mais de 20% contra a
   máquina parada (os núcleos 0–1 nunca recebem lote).
3. O banco de cada projeto do node 1 tem dump diário restaurado com sucesso, ou um alerta sai
   em ≤ 1 h.
4. Uma queda de site gera **um** incidente com resumo em ≤ 5 min, nunca dezenas de mensagens.
5. Às 07h o bom dia está renderizado em ≥ 95% dos dias, mesmo com o PC desligado.
6. O custo novo de API paga fica ≤ US$ 1/mês (sub-teto "lote", D4) e não toca os US$ 2 do modo nuvem.
7. Nenhuma porta nova fica pública (salvo D8). Nenhuma credencial do node 2 vai para o node 1.

## Requisitos funcionais

### R0 — F0 base: perfil, orçamento, janela, MCP único

**R0.1** A Ayanami DEVE ter um override de Compose "node 2 inteiro" (`compose.node2-inteiro.yml`)
que substitui o perfil enxuto. Cada serviço DEVE declarar `mem_limit`, `memswap_limit`, `cpus` e
`cpu_shares` conforme o orçamento consolidado (abaixo). A soma dos `mem_limit` DEVE ficar ≤ 18 GiB.

**R0.2** Os núcleos 0–1 DEVEM ficar livres de lote: todo serviço ou job de lote (`llm-local`, runner,
restore do `sandbox-db`, indexação, render de audiolivro) DEVE rodar com `cpuset` 2–7. Os serviços
interativos (`ayanami-api`, `worker-rapido`, `ayanami-voz` em tempo real, `ayanami-pg`) DEVEM ter
`cpu_shares` maior que qualquer serviço de lote.

**R0.3** ENQUANTO for janela noturna (D3), o lote PODE somar até 6 vCPU. FORA dela, o lote DEVE
somar ≤ 3 vCPU e DEVE ceder: QUANDO a fila `rapida` tiver trabalho pendente há mais de 2 s, os jobs
de lote longos DEVEM pausar entre etapas (checkpoint) até ela esvaziar.

**R0.4** O `llm-local` e o runner self-hosted (D9) DEVEM ser mutuamente exclusivos e subir/descer
por unidade systemd no host (`deploy/ayanami/host/`). Nenhum container da Ayanami DEVE montar
`docker.sock`.

**R0.5** O perfil DEVE incluir o container ntfy definido no [condessa-celular §6](../condessa-celular/design.md),
o mesmo serviço, sem segundo ntfy. A Ayanami DEVE publicar nele os avisos proativos deste SDD por
`push.enviar`, com prioridade por criticidade (R2.8).

**R0.6** Todas as tools novas DEVEM ficar no `/mcp/` existente (um endpoint, um token por
dispositivo). Cada tool DEVE exigir um escopo. Os escopos novos são `dev-ler`, `codigo-ler`,
`ops-ler`, `prod-ler`, `web`, `pessoal-ler` e `email-ler` (D13). `tools/list` DEVE mostrar só as
tools que o token pode chamar.

**R0.7** Toda chamada MCP DEVE ir à `auditoria` existente com dispositivo, tool, escopo, duração e
tamanho da resposta, **sem** o conteúdo. Respostas de `prod-ler` e `email-ler` DEVEM registrar o
projeto/pasta consultado.

**R0.8** Toda resposta de tool que carregue texto de terceiros (log de CI, log de produção, e-mail,
página web) DEVE passar por um redator de segredos (regras tipo gitleaks: tokens, chaves, senhas,
`APP_KEY`) e marcar o texto como dado não confiável.

**R0.9** ONDE D14 = (b), a Ayanami DEVE montar sub-servidores MCP de terceiros atrás do `/mcp/` com
prefixo (`gh_`, …), lista branca de tools no `ayanami.toml`, imagem fixada por digest, descrições
reescritas e nenhuma tool de escrita sem escopo explícito.

**R0.10** O vigia existente DEVE ganhar limiares por serviço do orçamento: QUANDO um serviço passar
de 90% do `mem_limit` por 10 min ou for morto por OOM, a Ayanami DEVE abrir um incidente (R2.6).

### R1 — F1 dev/MCP

**R1.1** Um job agendado DEVE consultar a API do GitHub a cada 5 min, com PAT *fine-grained*
somente leitura (Actions, Contents, Pull requests, Metadata), e guardar runs e deploys de todos os
repos do Pedro, com log cacheado por 7 dias.

**R1.2** A Ayanami DEVE expor `ci_falhas(repo?, desde?)`, `ci_log_resumo(run_id)` (o step que quebrou,
~60 linhas em volta do erro e o comando para reproduzir, extraído por regra para pytest, PHPUnit,
`tsc` e ESLint, ≤ 2k tokens), `pr_status(repo, numero)` e `ci_deploys(repo)`, todas no escopo `dev-ler`.

**R1.3** QUANDO um run da branch padrão passar de verde a vermelho, a Ayanami DEVE emitir evento
(SSE para a Condessa, push com prioridade baixa). QUANDO voltar a verde, DEVE fechar o aviso.

**R1.4** Um hook `SessionEnd`/`Stop` do Claude Code (script stdlib no repo) DEVE enviar a
`POST /v1/sessoes-dev`, com token `pc`, os dados: projeto, branch, commits da sessão,
`git diff --stat` e a última mensagem do assistente, redigidos (R0.8). **Nunca** o transcript inteiro.
SE a Ayanami estiver fora, ENTÃO o hook DEVE gravar numa fila local e reenviar depois, sem
travar o encerramento da sessão.

**R1.5** A Ayanami DEVE expor `sessoes_ultimas(projeto)`, `sessoes_buscar(consulta)` (e5-small +
pgvector) e `sessoes_pendencias()` no escopo `dev-ler`. A Condessa DEVE responder "o que eu fiz ontem
no gold-crm?" também em modo nuvem.

**R1.6** Um job noturno DEVE manter espelhos `git clone --mirror` de todos os repos do Pedro num
volume e incluí-los no restic (R2.2). Os espelhos excluem `.env*`, `storage/`, `vendor/` e
`node_modules/` da indexação.

**R1.7** A Ayanami DEVE indexar os espelhos por função/classe (tree-sitter: PHP, Blade, TS/TSX, Python)
com embeddings em CPU no pgvector (HNSW) mais `tsvector`, de forma incremental por arquivo alterado,
e expor `codigo_buscar(consulta, projeto?, linguagem?)`, `codigo_simbolo(nome)` e
`codigo_semelhante(trecho)` no escopo `codigo-ler`, com caminho, linha e commit.

**R1.8** ONDE D5 e D6 estiverem ligadas, a Ayanami DEVE expor `sql_schema(projeto)` e
`sql_ler(projeto, sql)` no escopo `prod-ler`, sobre o `sandbox-db`, com estas regras: só `SELECT`
(análise por `sqlglot`, recusa de função com efeito colateral), papel sem `CREATE`,
`statement_timeout` de 5 s, `LIMIT` forçado de 500 e colunas mascaradas (R2.3).

**R1.9** ONDE D8 estiver ligada, a Ayanami DEVE expor `prod_erros(projeto, desde)` (exceções
agrupadas, stack trace e contagem do Bugsink) no escopo `prod-ler`. QUANDO aparecer uma exceção
nova, DEVE abrir um incidente de baixa prioridade.

### R2 — F2 ops

**R2.1** ONDE D5 estiver ligada, um job `backup.node1` DEVE puxar toda noite, iniciado pelo node 2,
`pg_dump -Fc` de cada banco do node 1 (MultiVideos, gold-crm, wedding) pela porta única só-leitura
(SSH com `command=` em lista branca pelo tailnet, papel `ayanami_ro`). O node 1 NÃO DEVE receber
credencial nenhuma do node 2.

**R2.2** Cada dump DEVE entrar no repositório restic existente (Y4.2) com tag `node1-<projeto>` e
a retenção vigente (7 diários, 4 semanais, 6 mensais). ONDE D7 = B2 configurado, também no B2.
SE faltar o segredo do B2, ENTÃO o job DEVE seguir só com o repositório local e avisar uma vez por
semana, como o Y4.2 já faz.

**R2.3** O mesmo dump DEVE ser restaurado num banco de staging do `sandbox-db`, mascarado por
`mascara.toml` de cada projeto (e-mail, telefone, CPF, tokens → hash estável), validado por
contagens e só então trocado pelo banco servido ao `sql_ler`. O dump bruto DEVE ser apagado depois
do restic e do restore. Essa restauração **é** o teste de restore diário.

**R2.4** SE o restore falhar, ou se uma tabela-chave (por projeto, em `mascara.toml`) cair mais de 20%
contra a noite anterior, ENTÃO a Ayanami DEVE abrir um incidente alto e manter servido o banco da
noite anterior.

**R2.5** O Gatus DEVE checar de fora, com `gatus.yaml` versionado no repo: MultiVideos (`/up` e o
smoke de login inválido), gold-crm, wedding, AotMine, tensura-mine, `magi.`/`ayanami.dekasis.com.br`,
validade de TLS (alerta com < 14 dias) e DNS. DEVE também receber heartbeats dos jobs (backup,
restore, lote noturno, bom dia) e tratar o silêncio como falha.

**R2.6** O Beszel (hub no node 2) DEVE coletar métricas de host do node 2, do PC e, ONDE D10 estiver
ligada, do node 1, com alertas de limiar: disco > 80%, RAM > 90% por 10 min, load alto sustentado.

**R2.7** Gatus, Beszel, vigia e jobs DEVEM mandar webhook a `POST /v1/ops/alerta`. A Ayanami DEVE
deduplicar, esperar 2–3 min para correlacionar (node fora → sites fora = 1 incidente), anexar
contexto (último deploy de R1.1, métricas) e gerar um resumo de ≤ 2 frases. O resumo usa um molde
determinístico e, ONDE houver orçamento, o `llm-local` ou a API dentro do sub-teto "lote".

**R2.8** A entrega DEVE seguir a criticidade:
- produção fora: push alto no ntfy, Telegram ONDE houver token, e fala da Condessa se o PC estiver ligado;
- degradação: push normal;
- o resto: só no bom dia (R3.1).

ENQUANTO for horário de silêncio (D11), só "produção fora" DEVE tocar. QUANDO o problema
sumir, a Ayanami DEVE fechar o incidente com a duração.

**R2.9** A Ayanami DEVE expor, no escopo `ops-ler`, as tools `ops_status(projeto?)` (Gatus + Beszel +
último deploy + incidentes abertos), `ops_incidentes(desde)`, `ops_backup()` (último snapshot e
último restore ok por projeto) e, ONDE D5 estiver ligada, `ops_filas(projeto)` (verbo `filas` da porta
única: profundidade e consumidores). Essas tools DEVEM devolver só agregados, nunca linhas de cliente.

**R2.10** ONDE D12 estiver ligada, o node 2 DEVE mandar a cada 5 min um ping a um serviço externo
gratuito (healthchecks.io), para que a queda do node 2 ou da Contabo inteira avise por fora.

### R3 — F3 Condessa noturna

**R3.1** Às 05h30 (cron na fila agendada), a Ayanami DEVE montar o **bom dia** com clima
(Open-Meteo), notícias que importam, `ops_status`, incidentes da noite, a aula (R3.3), as pesquisas
prontas (R3.4) e o placar da véspera. O texto é feito por molde, com 1 frase de humor do
`llm-local` ou, sem ele, da API no sub-teto "lote". O áudio é renderizado em Kokoro e fica pronto
até 06h. QUANDO houver a primeira presença do dia (PC ou celular pela ponte de turno), a Condessa
DEVE tocá-lo e mostrar o card.

**R3.2** Depois do fechamento das 04h, a Ayanami DEVE escrever o **diário da Condessa** do dia
(5–10 linhas em primeira pessoa mais tópicos, decisões e pendências, com embedding e5) na tabela
`diario`. No domingo DEVE consolidar a semana. A tool é `memoria_diario(dia|busca)`, no escopo
`pessoal-ler`. O diário DEVE ser gerado **só pelo `llm-local`**, salvo opt-in explícito (D2/D4).

**R3.3** A partir das observações de Learning Mode do dia (sincronizadas do PC), a Ayanami DEVE
preparar a **aula do dia**: 5 frases dele para reescrever, 1 cenário de roleplay que force o erro
mais recorrente e a revisão espaçada (SM-2) do vocabulário salvo, com o áudio das frases-modelo
pré-renderizado. QUANDO não houver sessão na véspera, nenhuma aula é gerada (sem "curso").

**R3.4** A tarefa `pesquisar` DEVE ganhar um modo **profundo com prazo** ("até amanhã"): N rodadas
de busca (SearXNG, R4.1; Gemini com Google Search na cota grátis como alternativa), leitura com
extração local (trafilatura), resumo pelo `llm-local` e relatório de 1 tela mais 3 frases para o
bom dia. O orçamento de chamadas pagas é por tarefa.

**R3.5** O pipeline do audiolivro (marcação + elenco Kokoro) DEVE rodar como worker na janela,
mantendo prontos os **próximos 2 capítulos** a partir do marcador, em Opus por capítulo. O EPUB
sobe pelo PWA/HUD. O marcador é sincronizado PC↔celular. Livro terminado é apagado após 30 dias.

**R3.6** Toda ação proativa de F3 DEVE registrar a causa ("por que agora") e respeitar o teto de
cenas (≤ 8/h) e o "nunca no meio do jogo" da persona.

**R3.7** SE o lote noturno não terminar uma etapa até 07h, ENTÃO o bom dia DEVE sair com o que
estiver pronto e citar o que faltou. Ele não deve atrasar.

### R4 — F4 serviços pessoais

**R4.1** O SearXNG DEVE rodar só no tailnet, com saída JSON, sem o motor do Google (IP de datacenter)
e com Brave, DuckDuckGo, Bing, Mojeek e Wikipedia. A tool é `web_buscar(q, tempo?)`, escopo `web`.
É o motor padrão da `pesquisar` e do modo nuvem.

**R4.2** O Miniflux DEVE usar um banco próprio no `ayanami-pg`. O worker de notícias DEVE consumir
`entries?status=unread` como fonte, migrando os coletores aos poucos.
Lido ou descartado na Condessa DEVE virar `mark read` no Miniflux. As tools são `rss_assinar(url)`
e `rss_novidades(tema?)`.

**R4.3** ONDE D2 ≠ (a), o `llm-local` DEVE subir só na janela noturna, por unidade systemd do host,
com o modelo da D2, API compatível com OpenAI, só no tailnet interno do Compose, `cpuset` 2–7
(até 6 threads). **Nunca** deve ser usado em tempo real de voz.

**R4.4** Antes de qualquer job trocar API paga pelo `llm-local`, DEVE haver um A/B em 30 amostras
contra o modelo atual por tipo de tarefa (resumo de notícia, classificação de e-mail, diário),
registrado na spec. O tempo de lote por noite DEVE ser medido com `llama-bench -t 6` no node 2.

**R4.5** SE o `llm-local` não estiver de pé, ENTÃO cada job DEVE cair, nesta ordem, em: molde
determinístico; API dentro do sub-teto "lote" (D4); adiar para a noite seguinte. Nada falha em silêncio.

**R4.6** ONDE D7 (b) estiver ligada, um worker DEVE ler IMAP **só leitura**: `BODY.PEEK`,
nunca enviar, mover nem apagar, só nas pastas que o Pedro escolher. DEVE classificar as mensagens
(importante / boleto / promo / ruído) pelo `llm-local` e guardar só remetente, assunto, resumo,
vencimento e embedding, **sem o corpo**. As tools são `email_buscar` e `email_importantes`, no
escopo `email-ler`. O corpo NÃO DEVE ir a API paga sem pedido explícito.

**R4.7** QUANDO um boleto ou vencimento detectado estiver a ≤ 1 dia, a Ayanami DEVE avisar por push
normal e no bom dia.

## Requisitos não funcionais

| Id | Tema | Requisito |
| --- | --- | --- |
| RNF-P1 | Recursos | Orçamento consolidado abaixo: repouso ≤ 3 GiB e soma dos `mem_limit` ≤ 18 GiB. Revisa a meta RNF-A6 da central (≤ 6 GB), que valia para o node compartilhado. |
| RNF-P2 | Disco | Plataforma ≤ 80 GB dos 221 GB livres. Alerta em 70% do disco do node 2. |
| RNF-P3 | Custo | API nova ≤ US$ 1/mês (sub-teto "lote" no `BudgetNuvem`, D4). B2 ≤ US$ 1/mês com o node 1 incluso. Nenhum serviço pago novo. |
| RNF-P4 | Rede | Tudo só no tailnet ou na rede interna do Compose. Exceção pública só pela D8. Os pulls ao node 1 são iniciados pelo node 2. |
| RNF-P5 | Dados de clientes | Só leitura no node 1. A cópia é mascarada antes de ficar consultável. As tools devolvem agregados, salvo `sql_ler`. A `APP_KEY` nunca vem. |
| RNF-P6 | Privacidade pessoal | Diário, e-mail e EPUB ficam só no node 2 e no backup cifrado. Por padrão o LLM é local. |
| RNF-P7 | Operação | Zero operação manual diária. Tudo pela CI/CD, pelo vigia e pelos heartbeats. Imagens fixadas por versão ou digest. |
| RNF-P8 | Testes | O mesmo regime do repo: relógio e rng injetados, sem rede real, sem LLM pago, sem node 1 real nos testes. |
| RNF-P9 | Proibições | Nada de `docker.sock` em container. Nenhum verbo de escrita no node 1. Nada em `magi-pg`. Sem deploy fora da CI. |

## Orçamento de recursos consolidado (node 2: 8 vCPU, 23 GiB, swap 8 GiB, 221 GB livres)

Estimativas de planejamento a confirmar com `docker stats` e o vigia. O pico é o `mem_limit`.

| Serviço | Frente | RAM repouso | RAM pico (`mem_limit`) | CPU (`cpus`) | `cpu_shares` | `cpuset` | Disco |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ayanami-pg` (pgvector, Miniflux, código, sessões, diário) | F0 | 0,40 | 3,0 | 2 | 1024 | — | 20 GB |
| `ayanami-api` (+ MCP + gateway) | F0 | 0,20 | 1,0 | 1 | 1024 | — | — |
| `worker-rapido` | F0 | 0,10 | 0,5 | 1 | 1024 | — | — |
| `worker-agendado` (crons, CI, alertas, pulls) | F0/F2 | 0,15 | 1,0 | 1,5 | 512 | — | — |
| `worker-lento` (e5, código, trafilatura, STT, marcação) | F1/F3 | 0,15 | 3,5 | 4 | 256 | 2–7 | 6 GB modelos |
| `ayanami-voz` (Kokoro; audiolivro à noite) | F3 | 0,10 | 1,5 | 2 (4 à noite) | 1024 | — | 6 GB áudio |
| `llm-local` (Qwen3-4B Q4, só na janela) | F4 | 0 | 3,5 | 6 | 128 | 2–7 | 3 GB (+5 com 8B) |
| `sandbox-db` (cópia mascarada) | F1/F2 | 0,20 | 1,5 | 2 | 256 | 2–7 | 10 GB |
| `searxng` + `valkey` | F4 | 0,25 | 0,5 | 1 | 512 | — | 0,2 GB |
| `miniflux` | F4 | 0,05 | 0,25 | 0,5 | 512 | — | (no pg) |
| `bugsink` (opcional, D8) | F1 | 0,30 | 0,5 | 0,5 | 256 | — | 3 GB |
| `gatus` | F2 | 0,04 | 0,1 | 0,25 | 512 | — | 0,1 GB |
| `beszel` hub (+ agente local) | F2 | 0,06 | 0,2 | 0,5 | 512 | — | 0,5 GB |
| `ntfy` (do condessa-celular) | F0 | 0,03 | 0,1 | 0,25 | 1024 | — | 0,1 GB |
| Espelhos git + staging do restic + dumps | F1/F2 | — | — | — | — | — | 15 GB |
| SO + Docker + Tailscale | — | 0,60 | 0,8 | — | — | — | logs 2 GB |
| **Total** | | **≈ 2,6 GiB** | **≈ 17,95 GiB** | | | | **≈ 66 GB** (+5 com 8B) |
| Runner self-hosted (D9, **no lugar** do `llm-local`, nunca junto) | F1 | 0 | (3,5) | (4) | 128 | 2–7 | 10 GB cache |

Leitura: a soma dos limites (~18 GiB) deixa ≥ 5 GiB de RAM física e mais 8 GiB de swap. Na prática
o pico real é menor, porque o lote da janela é sequencial (design §4). Com o 8B (D2 d), o `llm-local`
sobe para `mem_limit` 6g e a soma vai a ~20,5 GiB: ainda cabe nos 23 GiB, mas sem folga. Por isso o
8B só roda com o `worker-lento` parado (etapas sequenciais, design §4) e fica fora do padrão.

## Decisões (precisam do Pedro; cada uma tem padrão até ele decidir)

- **D1 — Perfil "node 2 inteiro".** (a) Sobe o override com o orçamento acima e aposenta o enxuto
  (os dados do Minecraft continuam parados em `/opt/minecraft/data`); (b) mantém o enxuto.
  **Padrão: (a).** Do Pedro: confirmar que o Minecraft não volta. Se voltar, o enxuto renasce.
- **D2 — LLM local (reabre a central D8).** (a) nenhum; (b) `llama-server` (llama.cpp) com
  **Qwen3-4B Q4_K_M** só na janela; (c) Ollama no lugar do llama.cpp; (d) (b) mais um 7–8B Q4 para o
  que pede qualidade. **Padrão: (b)**, condicionado ao `llama-bench` e ao A/B (R4.4). Do Pedro: sim
  ou não, e qual modelo.
- **D3 — Janela noturna.** **Padrão: 00h–07h**, com lote ≤ 6 vCPU. Fora dela, ≤ 3 vCPU. Do Pedro:
  confirmar o horário (ele joga de madrugada?).
- **D4 — Sub-teto "lote" de API.** (a) US$ 1/mês dentro do teto de US$ 5, sem tocar os US$ 2 do modo
  nuvem (central D11); (b) zero de API no lote (só local ou molde). **Padrão: (a)**, sempre com o
  local primeiro. O diário e o e-mail nunca vão à API sem opt-in.
- **D5 — Porta única só-leitura no node 1.** Node 1 no tailnet (`tag:prod`, ACL só
  `tag:ayanami → tag:prod:22`), usuário `ayanami-ro` com `command=` em lista branca (`pg_dump`,
  `filas`, `disco`), papel `ayanami_ro` com `pg_read_all_data`. **Padrão: desligada** até o Pedro
  instalar (cerca de 30 min, uma vez). Sem ela, R2.1–R2.4, `ops_filas` e `sql_ler` ficam parados, e o
  Gatus continua de fora. Do Pedro: também aceitar, contratualmente, a cópia dos dados de clientes
  no node 2.
- **D6 — `sql_ler` na cópia mascarada.** **Padrão: escopo `prod-ler` desligado em todos os tokens.**
  O restore e a máscara rodam assim mesmo (é o teste de restore). Do Pedro: ligar no token do
  Claude Code e revisar a `mascara.toml` de cada projeto.
- **D7 — Credenciais externas.** (a) **B2:** conta e chave restrita ao bucket. **Padrão: sem B2**,
  só o restic local mais o aviso semanal; ruim, porque fica no mesmo provedor do node 1. (b)
  **E-mail:** senha de app IMAP (Gmail exige 2FA) e pastas. **Padrão: desligado.** Do Pedro: gerar
  as duas.
- **D8 — Erros de produção e rota pública.** (a) sem Bugsink; (b) Bugsink só no tailnet para o
  node 1 (exige D5 e o SDK do Sentry nos apps de clientes); (c) (b) mais a rota pública
  `erros.dekasis.com.br` **só com o endpoint de envelope** e rate-limit, para os sites da Vercel.
  **Padrão: (a).** Do Pedro: mexer nos repos dos clientes, e o DNS (é ele quem mexe).
- **D9 — Runner self-hosted do GitHub Actions.** (a) não; (b) runner efêmero **só para repos
  privados** (nunca o `magi-assistant-ai`, que é público), fora da janela, no lugar do `llm-local`.
  **Padrão: (a).** Do Pedro: se os minutos do plano estão apertando.
- **D10 — Beszel no node 1.** (a) agente só com métricas de host, sem `docker.sock`; (b) com
  containers (o socket dá root a quem comprometer o agente). **Padrão: (a)**, instalado pelo Pedro;
  sem ele, Beszel só no node 2 e no PC.
- **D11 — Canal e silêncio.** **Padrão:** ntfy (já planejado) mais Telegram quando houver token, e
  silêncio das 23h às 07h, exceto "produção fora". Do Pedro: o horário e o bot do Telegram.
- **D12 — Ping externo (vigia do vigia).** **Padrão: ligado assim que o Pedro criar a conta grátis
  no healthchecks.io.** Até lá, desligado e listado no `ops_status` como "ponto cego".
- **D13 — Escopos por token.** **Padrão:** o token `mcp` do Claude Code recebe `dev-ler`, `codigo-ler`,
  `ops-ler` e `web`. A Condessa (`pc`/`celular`) recebe `ops-ler`, `web` e `pessoal-ler`. `prod-ler`
  e `email-ler` ficam desligados em todos. Do Pedro: ligar quando quiser.
- **D14 — Gateway de MCP de terceiros.** (a) só tools nativas da Ayanami; (b) sub-servidores com
  lista branca e digest (primeiro candidato: `github-mcp-server` só leitura). **Padrão: (a)**, com o
  mecanismo (R0.9) entregue só quando houver o primeiro sub-servidor.

## O que precisa do Pedro (resumo, ~1 h no total, uma vez)

1. Responder D1–D4 (Minecraft não volta, LLM local, janela, sub-teto).
2. Sessão de ~30 min no node 1: tailnet + `ayanami-ro` + `ayanami_ro` (D5), mais o agente Beszel (D10).
3. Conta e chave B2 (D7a). Conta healthchecks.io (D12). Bot do Telegram (D11).
4. Lista de URLs críticas para o Gatus, e se gold-crm e wedding têm endpoint de saúde.
5. OPML ou feeds iniciais do Miniflux. Pastas do e-mail e senha de app, se for ligar (D7b).
6. Depois: D6, D8, D9 e D14 quando a dor aparecer.
