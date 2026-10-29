# Brainstorm 1 — a Ayanami como MCP de programação (Claude Code + projetos do Pedro)

Lente: o que o node 2 (8 vCPU, 23 GiB, 221 GB livres, sem GPU, só tailnet) pode expor no `/mcp/`
para o Claude Code — e para o `condessa-engine` — trabalhar melhor nos projetos reais:
`magi-assistant-ai`, **MultiVideos** (Laravel + Postgres, produção no node 1), **gold-crm/ourijoias**
(node 1), sites **Next.js na Vercel** (AotMine, tensura-mine), KPCeramica, scraperr.

Base que já existe e é reaproveitada em quase tudo: FastAPI + `mcp` 2.3.0 com token por
dispositivo, escopos e `auditoria`; Postgres + pgvector; procrastinate (rápida/lenta/agendada);
embeddings e5-small em CPU; vigia; confirmação no PC (padrão do `tv.power_off`). Regra de ouro
herdada: **tool nova = escopo novo, desligado por padrão, auditada**; nada escreve em produção.

## Panorama 2026 (pesquisa)

- **Código:** dois caminhos — índice híbrido (claude-context da Zilliz: BM25 + vetor em Milvus;
  code-index-mcp com Qdrant; semantic-code-mcp com tree-sitter + LanceDB) ou navegação simbólica
  por LSP (Serena, sem índice). O Claude Code em si só faz grep; índice semântico entre *vários*
  repos é o que falta.
- **GitHub:** `ghcr.io/github/github-mcp-server` com `GITHUB_TOOLSETS` e `GITHUB_READ_ONLY=1`.
- **Banco:** o servidor Postgres de referência foi arquivado (read-only só por transação, com bypass
  conhecido); o mais citado é o **Postgres MCP Pro** (crystaldba, MIT) com modo *restricted* que
  analisa o SQL; **DBHub** (Bytebase) para multi-banco com read-only, limite de linhas e timeout.
- **Logs/observabilidade:** `mcp-grafana` oficial (Prometheus, Loki, alertas); servidores Loki
  diretos (LogQL sem Grafana).
- **Docs:** Context7 é hospedado; o equivalente self-hosted mais maduro é o **Grounded Docs MCP**
  (`arabold/docs-mcp-server`, TS, ~1,3k estrelas).
- **Browser:** `@playwright/mcp` da Microsoft (árvore de acessibilidade, imagem Docker, ainda < 1.0).
- **Sandbox:** microsandbox (libkrun/KVM, beta), Daytona/Beam (AGPL), DifySandbox (seccomp).
  **Contabo não dá KVM aninhado** → no node 2 o realista é **gVisor (`runsc`)** como runtime do Docker.
- **Memória:** mem0/Graphiti pedem Neo4j e LLM pago; a tendência leve é Postgres + pgvector — que a
  Ayanami já tem.
- **Consenso:** escopo/credencial de leitura importa mais que qual servidor; MCP mitiga, não resolve
  prompt injection.

Decisão de arquitetura que atravessa as ideias: **implementar em Python dentro da Ayanami** quando
for fino (consulta a API/banco + resumo), e **só subir servidor de terceiro atrás do gateway (ideia
6)** quando ele trouxer muito pronto (Playwright, GitHub). Assim continua um token, uma auditoria,
um `list_tools`.

## Ranking (valor ÷ esforço)

★ = as 5 melhores. Esforço: P (≤ 2 dias), M (≤ 1 semana), G (> 1 semana).

| # | Ideia | Valor | Esforço | RAM extra | Custo/mês |
| --- | --- | --- | --- | --- | --- |
| 1 ★ | `ci_*` — CI do GitHub pré-digerido | alto | P | ~0 | 0 |
| 2 ★ | `diario_*` — diário de sessões do Claude Code | alto | P | ~0 | 0 |
| 3 ★ | `codigo_*` — busca semântica multi-repo | muito alto | M | 1–1,5 GiB | 0 |
| 4 ★ | `sql_ler` — cópia noturna mascarada do banco de produção (+ teste de restore) | muito alto | M | 1–2 GiB | 0 |
| 5 ★ | `prod_erros` / `prod_logs` — Loki + GlitchTip | alto | M | 1,5–2 GiB | 0 |
| 6 | Gateway MCP (sub-servidores atrás do `/mcp/`) | alto (habilitador) | M | ~50 MiB | 0 |
| 7 | `docs_*` — docs de libs versionadas (Context7 local) | alto | P | 0,5 GiB | 0 |
| 8 | `projeto_mapa` — schema, rotas, envs (nomes), jobs | médio-alto | P | ~0 | 0 |
| 9 | `deps_auditoria` — CVEs e desatualizados de todos os repos | médio-alto | P | ~0 | 0 |
| 10 | `site_*` — uptime + deploys da Vercel | médio | P | 150 MiB | 0 |
| 11 | `navegador_*` — Playwright headless | médio-alto | P | 0,5–1 GiB/sessão | 0 |
| 12 | `decisao_buscar` — specs, DECISOES e MEMORY.md indexados | médio-alto | P | ~0 | 0 |
| 13 | Espelho Forgejo de todos os repos | médio (habilitador + backup) | P | 250 MiB | 0 |
| 14 | `sandbox_executar` — execução isolada em gVisor | alto | M | 0,5–4 GiB sob demanda | 0 |
| 15 | Runner self-hosted do GitHub Actions (efêmero) | médio | P–M | 2–4 GiB em uso | 0 (economiza minutos) |
| 16 | `laravel_ops` — artisan só leitura no node 1 | alto | M | ~0 | 0 |
| 17 | `engine_*` — fila do condessa-engine no node 2 | muito alto | G | 2–6 GiB em uso | 0 API (cota do plano) |
| 18 | `metricas_*` — Prometheus node 1/2 + cAdvisor | médio | P | 400 MiB | 0 |
| 19 | `web_*` — SearXNG + leitor limpo com cache | baixo-médio | P | 300 MiB | 0 |
| 20 | `uso_claude` — consumo do plano/sessões por projeto | baixo-médio | P | ~0 | 0 |
| 21 | `revisao_noturna` — revisão de diffs do dia por `claude -p` | médio | M | (via 17) | 0 API |
| 22 | `migracao_ensaio` — roda migrations pendentes na cópia (ideia 4) | alto p/ MultiVideos | M | (via 4) | 0 |

Ordem sugerida de execução: 1 → 2 → 6 → 3 (com 13) → 4 (+22) → 5 → 7 → resto conforme dor.

---

## 1 ★ `ci_*` — CI do GitHub pré-digerido

- **Faz:** `ci_falhas(repo?, desde?)` lista runs vermelhos de todos os repos; `ci_log_resumo(run_id)`
  devolve só o step que quebrou, as ~60 linhas em volta do erro e o comando para reproduzir;
  `pr_status(repo, numero)` (checks, reviews, mergeável). Worker agendado consulta a API a cada
  5 min e emite evento → Condessa fala "o CI do MultiVideos quebrou no phpunit".
- **Por que:** o `gh run view --log` despeja dezenas de milhares de tokens; a Ayanami entrega 1–2k.
  E o aviso chega sem o Pedro olhar o GitHub. Já houve vários commits só de "deixar o CI verde".
- **Peças:** `httpx` (já tem) + GitHub REST; PAT *fine-grained* só `Actions: read`,
  `Contents: read`, `Pull requests: read`, `Metadata`. Extração de erro por regex por linguagem
  (pytest `FAILED`, PHPUnit, `tsc`, ESLint). Opcional: `github-mcp-server` atrás do gateway (6)
  com `GITHUB_TOOLSETS=actions,pull_requests` e `GITHUB_READ_ONLY=1`.
- **Recursos:** desprezível (polling leve; logs cacheados 7 dias, < 200 MB).
- **Risco:** só leitura; logs podem conter segredos mascarados pelo GitHub — passar por filtro
  gitleaks-like antes de devolver. Escopo novo `dev-ler`.
- **Esforço:** P.

## 2 ★ `diario_*` — diário de sessões do Claude Code

- **Faz:** hook `SessionEnd`/`Stop` do Claude Code (no PC e em qualquer máquina) manda à Ayanami:
  projeto, branch, commits da sessão, arquivos tocados (`git diff --stat`) e a última mensagem do
  assistente (que já é um resumo). Tools: `diario_ultimas(projeto)`, `diario_buscar(consulta)`
  (e5-small + pgvector), `diario_pendencias()` (frases "falta", "TODO", "não fiz").
- **Por que:** retomar contexto entre sessões e entre agentes paralelos sem reler o git log;
  a Condessa responde "o que eu fiz ontem no gold-crm?" mesmo com o PC desligado (modo nuvem).
- **Peças:** script de hook (Python, stdlib) + `POST /diario` com token `pc`; tabela `diario`
  com `vector(384)`; zero LLM (sem custo de API).
- **Recursos:** ~0; ~1 MB/mês de texto.
- **Risco:** a mensagem pode ter trechos de segredo → redigir com regras gitleaks antes de enviar;
  nunca mandar o transcript inteiro. Leitura no escopo `dev-ler`; gravação só pelo token `pc`.
- **Esforço:** P.

## 3 ★ `codigo_*` — busca semântica multi-repo

- **Faz:** `codigo_buscar(consulta, projeto?, linguagem?)` híbrido (tsvector BM25-ish + vetor) com
  trecho, caminho, linha e commit; `codigo_simbolo(nome)` (definição + usos via tree-sitter);
  `codigo_semelhante(trecho)` ("já fiz isso em outro projeto?").
- **Por que:** o Pedro repete padrões entre MultiVideos, gold-crm e KPCeramica (upload, auth,
  filas, Filament/Next). Hoje o Claude Code só enxerga o repo aberto e faz grep. Cross-repo e por
  significado é o ganho real — e o `condessa-engine` monta contexto muito mais barato.
- **Peças:** worker na fila `lenta`: `git fetch` do espelho (13) → `tree-sitter` 0.25 +
  `tree-sitter-language-pack` (PHP, TS/TSX, Python, Blade) para fatiar por função/classe →
  embeddings em CPU (começa com o e5-small já carregado; avaliar
  `jinaai/jina-embeddings-v2-base-code`, 161M, 768d) → `pgvector` (HNSW) na mesma Postgres.
  Reindexação incremental por arquivo alterado no push. Alternativa pronta: claude-context com
  Milvus — descartada (Milvus é pesado e duplicaria o pgvector).
- **Recursos:** indexação inicial de ~6 repos: 1–2 h em 4 núcleos, uma vez; depois minutos.
  RAM 1–1,5 GiB no lote; disco ~2–5 GB (índice + clones).
- **Risco:** código de cliente fica no node 2 (já é infra do Pedro, ok); `.env*`, `storage/`,
  `node_modules`, `vendor` excluídos; só leitura. Escopo `codigo-ler`.
- **Esforço:** M.

## 4 ★ `sql_ler` — cópia noturna mascarada do banco de produção (+ teste de restore)

- **Faz:** toda madrugada puxa `pg_dump` do MultiVideos e do gold-crm (usuário Postgres só
  leitura no node 1, via tailnet), restaura num Postgres-sandbox no node 2, **mascara** PII
  (e-mail, telefone, CPF, tokens → hash estável) e expõe `sql_ler(projeto, sql)` (só `SELECT`,
  analisado por `sqlglot`, `statement_timeout` 5 s, `LIMIT` forçado 500) e `sql_schema(projeto)`.
  Efeito colateral valioso: é o **teste de restore diário** dos bancos de produção, com alerta
  no vigia se falhar.
- **Por que:** "quantos vídeos falharam ontem?", "por que esse post não publicou?" sem SSH na
  produção e sem risco de `UPDATE` errado. E backup de cliente que nunca foi restaurado não é backup.
- **Peças:** `postgres:17` (versão igual à de produção) como container `sandbox-db`; worker
  procrastinate `agendada`; mascaramento por SQL declarativo por projeto (`mascara.toml`); opcional
  Postgres MCP Pro (crystaldba) em modo *restricted* atrás do gateway (6) se quiser `explain`/índices.
- **Recursos:** restore 5–20 min de 2 núcleos de madrugada; RAM 1–2 GiB (shared_buffers 512 MB);
  disco 2× o tamanho dos bancos (+ 1 dump anterior).
- **Risco:** maior da lista em dados — exige o **Pedro criar o usuário só-leitura no node 1** (regra
  "não tocar no node 1"); dados de clientes ficam mascarados e só no tailnet; role do sandbox sem
  `CREATE`; dump bruto apagado após restaurar. Escopo `prod-ler`, desligado por padrão.
- **Esforço:** M.

## 5 ★ `prod_erros` / `prod_logs` — erros e logs de produção

- **Faz:** `prod_erros(projeto, desde)` agrupa exceções (GlitchTip, compatível com SDKs do Sentry)
  com stack trace e contagem; `prod_logs(projeto, filtro, desde)` faz LogQL no Loki (Laravel
  `storage/logs`, nginx, `docker logs` do node 1); `prod_fila_falhas(projeto)` (jobs falhos do
  Horizon/queue). Alerta proativo: erro novo → Condessa avisa.
- **Por que:** hoje investigar bug do MultiVideos = SSH + `tail`. Com isso o Claude Code chega ao
  stack trace sozinho e propõe o fix.
- **Peças:** Loki 3.x single-binary (filesystem, retenção 14 d) no node 2; **Grafana Alloy** no
  node 1 empurrando pelo tailnet (instalar = decisão do Pedro); GlitchTip 5.x (web + worker +
  Valkey, usa a Postgres existente) e `sentry/sentry-laravel` / `@sentry/nextjs` nos apps.
  Sem Grafana UI: a Ayanami consulta a API do Loki direto (ou `mcp-grafana` no gateway se um dia
  quiser painéis).
- **Recursos:** Loki ~300–500 MiB; GlitchTip ~1–1,5 GiB; disco 5–15 GB (14 dias).
- **Risco:** logs têm PII → retenção curta e só tailnet. **Os sites na Vercel não alcançam o
  tailnet**: ingest do GlitchTip precisaria de rota pública (`erros.dekasis.com.br` só com o
  endpoint de envelope, rate-limit) — decisão do Pedro; sem isso, cobre só node 1. Escopo `prod-ler`.
- **Esforço:** M.

## 6 Gateway MCP — sub-servidores atrás do `/mcp/`

- **Faz:** a Ayanami vira o único endpoint MCP do Pedro: monta servidores de terceiros (Playwright,
  GitHub, Postgres MCP Pro, mcp-grafana) como sub-processos/containers e re-expõe as tools com
  prefixo (`gh_`, `web_`), aplicando escopo, auditoria e lista de tools permitidas.
- **Por que:** um `claude mcp add`, um token, um log de auditoria; troca/atualiza servidor sem mexer
  nas máquinas; o celular (Condessa) herda as mesmas tools.
- **Peças:** cliente `mcp` 2.3.0 (`ClientSession` streamable HTTP/stdio) dentro da Ayanami; allowlist
  de tools por sub-servidor no `ayanami.toml`; containers com `read_only: true`, sem rede externa
  quando não precisam.
- **Recursos:** proxy ~50 MiB; o custo é de cada sub-servidor.
- **Risco:** descrição de tool de terceiro é vetor de prompt injection → fixar versão por digest e
  reescrever descrições; nunca repassar tool de escrita sem escopo explícito.
- **Esforço:** M.

## 7 `docs_*` — documentação versionada local (Context7 caseiro)

- **Faz:** `docs_buscar(lib, consulta, versao)` sobre Laravel 12, Filament, Next.js 15/16,
  FastAPI, procrastinate 3.10, `mcp` 2.3, PySide6, Kokoro, Tailwind 4 — *nas versões travadas dos
  repos* (lidas do `composer.lock`/`package-lock`/`uv.lock`).
- **Por que:** o Pedro trava versões exatas nas specs; doc da versão certa evita API inventada
  (vários "S3:" na spec são exatamente isso).
- **Peças:** Grounded Docs MCP (`arabold/docs-mcp-server`, Docker) atrás do gateway, com
  embeddings locais; ou nativo: crawler `trafilatura` + o mesmo índice da ideia 3.
- **Recursos:** 0,5 GiB; disco 1–3 GB; reindexa semanalmente.
- **Risco:** baixo (público). Escopo `ler`.
- **Esforço:** P.

## 8 `projeto_mapa` — mapa vivo de cada projeto

- **Faz:** por projeto, a cada push: schema do banco (da cópia da ideia 4 ou das migrations),
  `route:list --json`, rotas do App Router, jobs/schedules, **nomes** de variáveis de ambiente,
  serviços do compose. Tool `projeto_mapa(projeto, secao)`.
- **Por que:** contexto estrutural em 1 chamada, barato, para o Claude Code e o Engine.
- **Peças:** worker que roda extratores em container efêmero (php:8.3-cli / node:22) sobre o
  espelho; parse de migrations sem subir o app quando possível.
- **Recursos:** segundos por push. **Risco:** nunca valores de env. **Esforço:** P.

## 9 `deps_auditoria` — dependências e CVEs de todos os repos

- **Faz:** lote noturno com `osv-scanner` 2.x (composer, npm, uv/pip) + `composer outdated`/
  `npm outdated`; `deps_auditoria(projeto?)` devolve CVEs por severidade e pacote, com versão fixa.
- **Por que:** MultiVideos e gold-crm são de clientes em produção; CVE de Laravel/Next aparece sem
  o Pedro procurar. Combina com o Engine (17) para abrir PR de bump.
- **Peças:** binário `osv-scanner` (Go) + base OSV offline atualizada diariamente.
- **Recursos:** ~200 MB de base; minutos/noite. **Risco:** só leitura. **Esforço:** P.

## 10 `site_*` — uptime e deploys da Vercel

- **Faz:** `site_status()` (uptime, TLS expira em, latência) dos sites e APIs; `vercel_deploys(
  projeto)` (último deploy, estado, URL de preview, log de build com erro resumido).
- **Peças:** Uptime Kuma 2.0 (ou checks nativos em `httpx` na fila agendada) + token Vercel de
  leitura. **Recursos:** ~150 MiB. **Risco:** token Vercel não tem escopo fino → guardar só no
  `.env` e nunca expor; sem ações de deploy. **Esforço:** P.

## 11 `navegador_*` — Playwright headless no node 2

- **Faz:** `navegar_texto(url)`, `screenshot(url, largura)`, `console_erros(url)`,
  `lighthouse(url)` em previews da Vercel e no MultiVideos — o Claude Code verifica a mudança
  visualmente sem abrir o Chrome do Pedro.
- **Peças:** `mcr.microsoft.com/playwright/mcp` (fixar digest) atrás do gateway, `--headless
  --isolated`, sem perfil persistente; `lighthouse` 12 em container separado.
- **Recursos:** 0,5–1 GiB por sessão; limitar a 2 simultâneas.
- **Risco:** página hostil = prompt injection; sem cookies do Pedro, sem acesso ao tailnet
  (rede só de saída, bloquear 100.64.0.0/10 e RFC1918). **Esforço:** P.

## 12 `decisao_buscar` — specs, decisões e memória indexadas

- **Faz:** busca semântica em `specs/**`, `DECISOES-*.md`, `MEMORY.md` e mensagens de commit de
  todos os repos: "por que o STT ficou assíncrono?", "qual versão do procrastinate travamos?".
- **Por que:** as specs do Pedro são grandes; achar a decisão certa custa muitas leituras hoje.
- **Peças:** reaproveita o índice da ideia 3 (coleção `docs-internos`). **Esforço:** P (depois de 3).

## 13 Espelho Forgejo de todos os repos

- **Faz:** Forgejo 11 com *pull mirror* de cada repo do GitHub (de hora em hora); fonte local para
  3/8/9 e **backup de código** fora do GitHub, entrando no restic.
- **Recursos:** ~250 MiB; disco = tamanho dos repos. **Risco:** deploy keys só leitura; UI só no
  tailnet. Alternativa mínima: `git clone --mirror` num cron, sem UI. **Esforço:** P.

## 14 `sandbox_executar` — execução isolada

- **Faz:** `sandbox_executar(imagem, comando, repo?, ref?, tempo_max)` em container efêmero com
  runtime gVisor: reproduzir bug, rodar um script de migração de dados na cópia (4), testar snippet
  de PHP 8.3/Node 22/Python 3.12 sem poluir o PC.
- **Peças:** `runsc` (gVisor, plataforma `systrap`, funciona sem KVM) registrado no Docker;
  `--network none` por padrão; cgroup 2 núcleos/2 GiB/10 min; overlay descartável.
- **Risco:** código gerado por LLM → isolamento obrigatório; sem segredos montados; escopo
  `executar` com confirmação no PC na primeira vez por sessão. **Esforço:** M.

## 15 Runner self-hosted do GitHub Actions

- **Faz:** `actions-runner` efêmero (um job por container) para os repos **privados** —
  testes do magi (Qt offscreen, pg) e do MultiVideos sem gastar os 2.000 min/mês grátis.
- **Recursos:** 2–4 GiB durante o job. **Risco:** nunca em repo público (PR de fork executa
  código); container efêmero; sem acesso ao docker do host. **Esforço:** P–M.

## 16 `laravel_ops` — artisan só leitura no node 1

- **Faz:** `laravel_ops(projeto, comando)` com lista fechada: `route:list`, `schedule:list`,
  `queue:failed`, `horizon:status`, `about`, `migrate:status`.
- **Peças:** chave SSH dedicada no node 1 com `command="/usr/local/bin/artisan-ro"` forçado
  (script valida a allowlist) e `restrict`. **Risco:** toca produção (leitura) → precisa do Pedro
  instalar; qualquer comando fora da lista recusado no próprio node 1. **Esforço:** M.

## 17 `engine_*` — fila do condessa-engine no node 2

- **Faz:** `engine_enfileirar(projeto, pedido)`, `engine_status(id)`, `engine_aprovar(id)`: a
  Ayanami recebe intenções (do Claude Code, da voz ou do celular) e um worker roda `claude -p` em
  worktree no node 2, com testes no sandbox (14), devolvendo branch + PR para revisão.
- **Por que:** é o `condessa-engine` sem depender do PC ligado; o Pedro pede pelo celular e acha o
  PR pronto. Usa a cota do plano do Claude, não o budget de API de US$ 5.
- **Peças:** `@anthropic-ai/claude-code` (Node 22) em container com credencial do plano,
  procrastinate como fila, deploy key com escrita **só em branches `engine/*`** (proteção de
  branch na `main`), limites de turno/tempo por task.
- **Recursos:** 2–6 GiB durante a task (testes dominam). **Risco:** maior autonomia da lista →
  sem merge automático, sem segredos de produção, aprovação explícita. **Esforço:** G.

## 18 `metricas_*` — Prometheus dos dois nodes

- **Faz:** `metricas(host, serie, janela)` e `metricas_anomalias()` (CPU, RAM, disco, containers).
  **Peças:** Prometheus 3.x (retenção 15 d) + `node_exporter` + cAdvisor; o vigia passa a ler daqui.
  **Recursos:** ~400 MiB, 2–4 GB disco. **Risco:** exporter no node 1 = decisão do Pedro.
  **Esforço:** P.

## 19 `web_*` — busca e leitura privadas

- **Faz:** `web_buscar` (SearXNG, sem chave) e `web_ler(url)` (trafilatura, cache 7 d). Útil mais
  para a Condessa e os workers do que para o Claude Code (que já tem WebSearch).
  **Recursos:** ~300 MiB. **Esforço:** P.

## 20 `uso_claude` — consumo do plano por projeto

- **Faz:** o hook da ideia 2 também manda tokens/duração da sessão; `uso_claude(periodo)` soma por
  projeto e máquina (estilo `ccusage`), e o Engine (17) respeita um teto diário.
  **Esforço:** P (junto com 2).

## 21 `revisao_noturna` — revisão dos diffs do dia

- **Faz:** de madrugada, para cada repo com commits no dia, uma sessão `claude -p` (via 17) revisa
  o diff com o mapa (8) e a busca (3); achados viram itens no diário (2) e aviso na manhã.
  **Risco:** só comenta, não altera. **Esforço:** M (depois de 17).

## 22 `migracao_ensaio` — ensaio de migrations na cópia

- **Faz:** antes do deploy do MultiVideos/gold-crm, roda `php artisan migrate --pretend` e depois
  `migrate` de verdade na cópia mascarada (4) dentro do sandbox (14): tempo, locks longos, erros.
- **Por que:** migration que trava tabela grande em produção é o pior incidente possível para
  cliente. **Esforço:** M (depois de 4 e 14).

---

## Orçamento do node 2 se tudo das 5 melhores subir

| Item | RAM | Disco |
| --- | --- | --- |
| Hoje (Ayanami) | ~0,3 GiB | — |
| 1 + 2 | ~0 | < 1 GB |
| 3 (+13) | 1–1,5 GiB no lote, ~0,3 parado | 3–6 GB |
| 4 | 1–2 GiB | 2× bancos |
| 5 | 1,5–2 GiB | 5–15 GB |
| **Total** | **~4–6 GiB** | **~15–30 GB** |

Sobra folga para 6, 7, 11 e o sandbox sob demanda. Custo mensal adicional: **US$ 0** (tudo
self-hosted, sem API paga; o Engine usa a cota do plano).

## Decisões que dependem do Pedro

1. Usuário Postgres só-leitura + `pg_dump` pelo tailnet no node 1 (ideia 4).
2. Alloy/exporter no node 1 (ideias 5 e 18) e SDK de erros nos apps.
3. Rota pública só para ingest de erros dos sites da Vercel (ideia 5) — ou ficar sem.
4. Credencial do plano do Claude no node 2 (ideia 17).
5. Escopos novos (`dev-ler`, `codigo-ler`, `prod-ler`, `executar`) e quais tokens recebem cada um.
