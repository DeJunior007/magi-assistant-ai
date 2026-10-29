# Brainstorm 3 — Infra: o node 2 como central de operação (2026-10-28)

Lente: o node 2 deixa de ser "só a Ayanami" e vira a **sala de controle** do Pedro: observa, faz backup e
ajuda o CI do PC, do node 1 (produção: MultiVideos, gold-crm, wedding) e dos projetos (Vercel, GitHub).
Base: `contexto.md` e `MultiVideos/INFRA.md` (lido localmente; **o node 1 não foi acessado**).

## Fatos que pesam

- **O node 1 não tem backup** (INFRA.md §Backup): perder o volume do Postgres = perder Meta Apps, páginas,
  tokens e histórico. É o maior risco do ecossistema hoje, e o que mais compensa resolver.
- Hoje a observabilidade do node 1 se resume ao `docker compose logs`, ao RabbitMQ UI por túnel SSH e ao sidecar de stats
  no painel. Também não há alerta de disco nem do contador de `publish_exhausted`, embora o INFRA.md peça os dois.
- O INFRA.md já registrou a armadilha do `docker.sock`: proxy genérico com `CONTAINERS=1` expõe o env
  (senhas) via inspect. **Nenhuma ideia abaixo monta socket do node 1 em algo genérico.**
- Postgres/RabbitMQ/Redis do node 1 só escutam em `127.0.0.1` → acesso remoto só por SSH/túnel.
- Repositórios: `magi-assistant-ai` é **público**; `multivideos-*`, `gold-crm`, `wedding-*` e `scraperr-*` são
  privados (esses gastam minutos do plano).
- Node 2: 8 vCPU, 23 GiB, 221 GB livres. A Ayanami usa ~320 MiB. Teto que proponho para todo o "ops": **≤ 1,5 GiB de RAM e
  ≤ 1 vCPU médio**, para sobrar folga ao resto do brainstorm.
- O node 1 e o node 2 estão na Contabo, então uma pane de datacenter derruba o vigia junto. Por isso existe a ideia 6.

### Princípio de acesso ao node 1: "porta única só-leitura"

Feito uma vez pelo Pedro, e serve de base para as ideias 1, 5, 9 e 16:
1. O node 1 entra no tailnet com uma tag (`tag:prod`), e uma ACL permite só `tag:ayanami → tag:prod:22`. Assim nada novo fica
   público. A alternativa é SSH público com `from="<IP do node 2>"`.
2. Um usuário `ayanami-ro`, sem sudo, com chave `restrict,command="/usr/local/sbin/ayanami-ro"` no
   `authorized_keys`. O script é uma **lista branca de verbos** (`pg_dump`, `filas`, `disco`, `deploy`, `erros`) que
   ignora qualquer argumento livre. Sem shell, sem port-forward, sem pty.
3. No Postgres, um papel `ayanami_ro` com `pg_read_all_data` (PG 14+), usado só para o dump. Para métricas, um papel separado com
   `pg_monitor`. No RabbitMQ, um usuário com a tag `monitoring`, que lê filas mas não publica nem apaga.
4. Tudo que sai do node 1 é **pull iniciado pelo node 2**. O node 1 nunca recebe credencial do node 2.

Custo de rompimento: se o node 2 for comprometido, o atacante **lê** o banco do node 1 (o dump) mas não altera nada.
Esse é o risco residual aceito, e cabe ao Pedro decidir.

---

## Ranking (valor ÷ esforço) — ★ = as 5 melhores

| # | Ideia | Valor | Esforço | RAM node 2 | Custo/mês |
|---|---|---|---|---|---|
| 1 ★ | Backup do Postgres do node 1 (pull só-leitura → restic → B2 + ensaio de restore) | altíssimo | M | ~100 MiB em pico | ~US$ 0,10 |
| 2 ★ | Gatus: uptime + TLS + heartbeats de tudo | alto | P | ~40 MiB | 0 |
| 3 ★ | Beszel: métricas de host/containers (node 1, node 2, PC) | alto | P | ~60 MiB hub | 0 |
| 4 ★ | Alerta inteligente: dedup + resumo pela Ayanami → Condessa/Telegram | alto | M | ~0 (na Ayanami) | ≤ US$ 0,20 |
| 5 ★ | "SRE de bolso": tools MCP `ops.*` (perguntar por voz) | alto | M | ~0 (na Ayanami) | ~0 |
| 6 | Vigia do vigia (heartbeat externo do node 2) | médio-alto | P | 0 | 0 |
| 7 | Espelho noturno de todos os repos do GitHub → restic B2 | médio-alto | P | ~50 MiB pico | ~US$ 0,05 |
| 8 | Radar de vencimentos (TLS, domínio, PAT, chaves B2, tokens Meta) | médio-alto | P | 0 | 0 |
| 9 | Sinais de negócio do MultiVideos (fila, `publish_exhausted`, disco do `videos_data`) | alto | M | ~0 | 0 |
| 10 | Rastreador de deploys e CI (todos os repos) | médio | P | 0 | 0 |
| 11 | Trivy noturno nas imagens de produção (com versão fixada) | médio | P | ~300 MiB pico | 0 |
| 12 | Bugsink: captura de erros compatível com Sentry | médio-alto | M | ~300 MiB | 0 |
| 13 | Runner efêmero do GitHub Actions só para repos privados | médio | M | 0–4 GiB sob demanda | 0 |
| 14 | SOPS + age para os `.env` (node 1, node 2, PC) | médio | M | 0 | 0 |
| 15 | Relatório semanal de higiene (apt, reboot, disco Docker, imagens órfãs) | médio | P | 0 | 0 |
| 16 | Logs centralizados: VictoriaLogs + Vector | médio | M | ~250 MiB | 0 |
| 17 | VictoriaMetrics + Grafana (só se o Beszel não bastar) | médio-baixo | M | ~400 MiB | 0 |
| 18 | Status page pública para os clientes | baixo-médio | P | 0 (Gatus) | 0 |
| 19 | Registry/cache de imagens (Zot) | baixo | P | ~60 MiB | 0 |
| 20 | Standby frio do MultiVideos no node 2 (runbook + ensaio de DR) | médio | G | 0 (só no ensaio) | 0 |

Soma de 1–12 em regime: ~**0,9 GiB de RAM** e ~5 GB de disco (TSDB + cache do restic + espelhos). Cabe no teto.

---

## As ideias

### 1 ★ Backup do Postgres do node 1 via pull só-leitura
- **O que é:** um job agendado `backup.node1` na fila da Ayanami. Ele roda `ssh ayanami-ro@node1 pg_dump`, e o script do node 1 faz
  `docker compose exec -T postgres pg_dump -Fc -U ayanami_ro`. O stream chega ao node 2 e entra no **mesmo** repositório restic, com a tag
  `node1-multivideos`, `node1-goldcrm` e `node1-wedding`. Aplica a retenção que já existe (7 diários, 4 semanais, 6 mensais). Uma vez por mês, um
  `restore_teste` sobe um `postgres:16-alpine` efêmero no node 2, faz o `pg_restore` e confere contagens (`meta_apps`, `facebook_pages`,
  `posts`). Se a contagem cair mais de 20% em relação ao dump anterior, o job alerta.
- **Valor:** fecha o maior risco do ecossistema, a perda total do cadastro de clientes. O backup é testado de verdade, não só gravado.
- **Peças:** restic 0.19.1, já no worker. `pg_dump` 16 no cliente (precisa ser ≥ ao major do servidor, que é o `postgres:16-alpine`).
  Backblaze B2. A peça que já existe é `backup.*` (Y4.2).
- **Recursos:** CPU curta, minutos por noite. ~100 MiB de RAM no pico. Disco: os dumps comprimidos do MultiVideos são de dezenas de MB, e
  os vídeos ficam fora (são efêmeros por design).
- **Custo:** B2 a ~US$ 6/TB/mês, então centavos. Egress do node 1 desprezível.
- **Risco:** o node 2 passa a ter uma cópia legível do banco de clientes, que guarda tokens Meta criptografados com a `APP_KEY`
  (a `APP_KEY` **não** entra no backup). O restic cifra em repouso. O acesso é só leitura, com o verbo único `pg_dump`. Os dados de clientes saem
  do node 1, então o Pedro deve validar se isso é aceitável contratualmente.
- **Esforço:** M.
- **Exige do Pedro:** criar a conta B2 e a chave restrita ao bucket (já pendente para a Y4.2), instalar o usuário/script/chave no node 1,
  pôr o node 1 no tailnet e criar o papel `ayanami_ro`. ~30 min, uma vez só.

### 2 ★ Gatus — uptime, TLS e heartbeats em YAML versionado
- **O que é:** um container Gatus no node 2 com `gatus.yaml` no repo. Checa por fora: MultiVideos `/up` (200), login inválido
  (401/422, o mesmo smoke do deploy), gold-crm, wedding, sites Vercel (AotMine/tensura-mine), `magi./ayanami.dekasis.com.br`.
  Também acompanha a validade do certificado (alerta em < 14 dias), DNS e latência. Tem endpoints **push/heartbeat** para jobs: backup,
  `restore_teste` e workers da Ayanami avisam "estou vivo", e o silêncio vira alerta.
- **Valor:** saber antes do cliente que caiu. O YAML em git combina com o fluxo SDD/CI, sem painel para clicar.
- **Peças:** Gatus v5.37 (set/2026, `ghcr.io/twin/gatus:stable`). Estado em SQLite ou no Postgres da Ayanami. A alternativa com
  painel é o Uptime Kuma 2.5.3. O Gatus ganha por ser declarativo.
- **Recursos:** ~40 MiB de RAM, CPU desprezível, < 100 MB de disco.
- **Custo:** 0.
- **Risco:** só faz requests públicos e não toca o node 1 por dentro. A UI fica no tailnet.
- **Esforço:** P.
- **Exige do Pedro:** listar as URLs que importam e dizer se gold-crm e wedding têm endpoint de saúde.

### 3 ★ Beszel — métricas de host e containers
- **O que é:** o hub Beszel no node 2 e agentes no node 1, no node 2 e no PC. Mostra CPU, RAM, disco, rede, temperatura (PC) e
  stats por container, com histórico e alertas de limiar (disco > 80% no node 1, que o INFRA.md pede; RAM; load).
- **Valor:** responde "o ffmpeg está sufocando o node 1?" e "o disco do `videos_data` vai encher?" com gráfico e
  tendência. Substitui o "não incluído por ora: Grafana/Prometheus" do INFRA.md com um custo baixo.
- **Peças:** hub e agente Beszel (release atual do GitHub `henrygd/beszel`, a confirmar no dia). O agente é um binário em Go e roda
  como systemd ou container.
- **Recursos:** agente < 10 MiB por máquina, hub ~60 MiB e ~200 MB de disco por ano de histórico.
- **Custo:** 0.
- **Risco:** para ver containers, o agente do node 1 precisa do `docker.sock`, que é a mesma armadilha do INFRA.md. Mitigações: (a) começar **só com
  métricas de host** (sem socket); (b) se quiser containers, o agente escuta só no IP do tailnet e só aceita a chave ed25519
  do hub, e o hub fica atrás de login. O agente não expõe inspect/env pela API dele, mas quem o compromete vira root.
  A decisão fica com o Pedro.
- **Esforço:** P.
- **Exige do Pedro:** instalar o agente no node 1 (um comando) e escolher entre host-only e containers.

### 4 ★ Alerta inteligente — a Ayanami agrupa, resume e avisa pela Condessa
- **O que é:** Gatus, Beszel, os jobs e o vigia mandam webhook para `POST /v1/ops/alerta` na Ayanami. Ela **deduplica**
  (uma queda = um incidente, não 40 mensagens) e espera 2–3 min para correlacionar ("o node 1 caiu, então os 3 sites
  caíram"). Também junta contexto (último deploy, idea 10; métricas, idea 3) e gera **um resumo de 2 frases**. A entrega
  segue a criticidade: produção fora do ar vai em push no celular + Telegram (já usado no node 1) + fala da Condessa se o PC
  estiver ligado. Coisas menores entram no relatório diário. Quando o problema some, ela fecha o incidente com a duração.
- **Valor:** o Pedro recebe "MultiVideos fora há 4 min, começou 2 min após o deploy abc123; worker-facebook-publish
  reiniciando em loop", não um pager barulhento. Respeita silêncio noturno, exceto em produção.
- **Peças:** os eventos/SSE/push da Ayanami (já existem), o token do Telegram (pendente), e um LLM barato só para o resumo, com
  template determinístico como fallback.
- **Recursos:** desprezíveis.
- **Custo:** ≤ US$ 0,20/mês (dezenas de incidentes × ~1k tokens), dentro do sub-teto.
- **Risco:** o resumo pode vazar segredo de log. Por isso o texto passa por um redator (regex de token/senha) antes do LLM, e o LLM nunca vê `.env`.
- **Esforço:** M.
- **Exige do Pedro:** o bot do Telegram e o horário de silêncio.

### 5 ★ "SRE de bolso" — tools MCP `ops.*`
- **O que é:** tools novas no `/mcp/` da Ayanami, consumidas pela Condessa (voz/HUD/celular) e pelo Claude Code:
  `ops.status(projeto)` (Gatus + Beszel + último deploy + incidentes abertos), `ops.filas(multivideos)` (profundidade e
  consumers do RabbitMQ via verbo `filas`), `ops.erros(projeto, desde)` (ideia 12/16), `ops.deploys(repo)`,
  `ops.backup()` (último snapshot e último restore testado), `ops.ci(repo)`. **Todas são só leitura.** O único verbo de
  escrita imaginável, o "reiniciar worker" que o painel do MultiVideos já tem, fica **fora** e com confirmação, como casa/TV.
- **Valor:** perguntar "o MultiVideos tá ok?" e ouvir "Tudo no ar; fila de publicação com 12 mensagens, 8 consumers;
  último deploy ontem 18h; backup de hoje 4h12 ok". Ao programar, o Claude Code consulta produção sem SSH.
- **Peças:** o servidor MCP existente; dados das ideias 1–3 e 9–10.
- **Recursos:** ~0.
- **Custo:** 0.
- **Risco:** a resposta pode carregar dado de cliente, então as tools devolvem agregados (contagens, estados), nunca linhas.
- **Esforço:** M, crescendo junto com as fontes.
- **Exige do Pedro:** nada além das ideias de base.

### 6 Vigia do vigia
- **O que é:** o node 2 manda um ping de 5 em 5 min para um serviço externo gratuito (healthchecks.io, plano grátis com ~20 checks).
  Se o node 2 sumir, ou a Contabo inteira cair, o e-mail/Telegram chega por fora.
- **Valor:** cobre o ponto cego de tudo acima, que mora no mesmo provedor que o node 1. **Peças:** cron + curl. **Recursos/custo:** 0.
- **Risco:** nenhum dado sai, só o ping. **Esforço:** P. **Exige do Pedro:** criar a conta.

### 7 Espelho noturno dos repositórios
- **O que é:** um job `git clone --mirror`/`fetch` de todos os repos do `DeJunior007` (inclusive privados), com um token fine-grained
  de **só leitura** em Contents. Depois entra no restic (B2). Inclui o wiki e as releases.
- **Valor:** perder a conta do GitHub ou sofrer um force-push acidental deixa de ser catastrófico. Código de cliente fica com 3 cópias.
- **Peças:** git, restic 0.19.1. **Recursos:** ~1–3 GB de disco, minutos de CPU por noite. **Custo:** centavos no B2.
- **Risco:** o token vaza leitura de repos privados, então expira em 1 ano e entra no radar (ideia 8). **Esforço:** P.
- **Exige do Pedro:** criar o PAT fine-grained.

### 8 Radar de vencimentos
- **O que é:** um job diário que lista o que expira e avisa com 30/14/3 dias: certificados (Gatus já vê), domínio
  `dekasis.com.br` (RDAP do registro.br), PATs do GitHub, chaves do B2, cartão/fatura da Contabo (data manual) e,
  se o MultiVideos expuser um endpoint agregado, **tokens Meta perto de expirar** (só a contagem).
- **Valor:** essas coisas costumam quebrar produção numa sexta à noite. **Peças:** Ayanami (`agendada`) + tabela `vencimentos`.
- **Recursos/custo:** 0. **Risco:** baixo. **Esforço:** P. **Exige do Pedro:** cadastrar as datas que não dá para descobrir sozinho.

### 9 Sinais de negócio do MultiVideos
- **O que é:** a cada 5 min, via os verbos `filas` e `disco` da porta só-leitura, coletar a profundidade de `video.processing` e
  `facebook.publish`, consumers ativos, mensagens não confirmadas, `df` do `videos_data`, e uma consulta agregada com
  `pg_monitor`/role só-leitura: `count(*) where failed_reason='publish_exhausted'` e posts publicados nas últimas 24h.
  Os alertas usam regra simples: fila crescendo há 30 min com 0 consumers, publish_exhausted subindo, ou zero posts em 6h.
- **Valor:** pega o problema **que o uptime não vê**: a API responde 200, mas nada está sendo publicado. O INFRA.md
  pede exatamente esses dois alertas.
- **Peças:** RabbitMQ management API (usuário `monitoring`) ou plugin `rabbitmq_prometheus` (porta 15692 em localhost).
- **Recursos:** ~0. **Custo:** 0. **Risco:** a consulta SQL é fixa no script do node 1, sem SQL livre. **Esforço:** M.
- **Exige do Pedro:** criar o usuário do RabbitMQ e aprovar as consultas.

### 10 Rastreador de deploys e CI
- **O que é:** o poll da API do GitHub (token só-leitura em Actions) a cada 10 min guarda os runs e deploys de todos os repos.
  A Ayanami correlaciona os deploys com incidentes e avisa "CI do magi vermelho há 2 dias".
- **Valor:** responde "foi o deploy?" na hora e alimenta a ideia 4. **Peças:** GitHub REST, tabela `deploys`.
- **Recursos/custo:** 0. **Risco:** baixo. **Esforço:** P. **Exige do Pedro:** o token (pode ser o mesmo da ideia 7, com escopo Actions:read).

### 11 Trivy noturno nas imagens
- **O que é:** o node 2 baixa as tags `latest` do ghcr (MultiVideos, Ayanami e o que estiver em produção) e roda `trivy image`
  e `trivy fs` nos repos espelhados (ideia 7). O resultado vai para o relatório semanal, com só os CRITICAL/HIGH com fix disponível.
- **Valor:** descobrir CVE explorável na base PHP/Alpine/Python antes de virar problema, sem tocar o node 1.
- **Peças:** binário Trivy **fixado por versão e checksum**, nunca `trivy-action@tag`: em mar/2026 a TeamPCP sequestrou as
  tags do trivy-action/setup-trivy e publicou o Trivy 0.69.4 malicioso (CVE-2026-33634, imagens 0.69.4–0.69.6). Usar uma
  release posterior verificada, ou o Grype como segunda opinião. Vale também **fixar por SHA** todas as Actions de todos os repos.
- **Recursos:** ~300 MiB e 1 vCPU por ~5 min por noite, ~1 GB de cache do banco de CVE. **Custo:** 0.
- **Risco:** o próprio scanner é vetor de supply chain (ver acima), então não roda com segredos no ambiente. **Esforço:** P.
- **Exige do Pedro:** nada. Só ler o resumo.

### 12 Bugsink — erros de aplicação
- **O que é:** um servidor de erros compatível com o SDK do Sentry, em um container só (Bugsink, release atual a confirmar;
  o GlitchTip é a alternativa mais pesada). Laravel (`sentry/sentry-laravel`), Next.js e FastAPI mandam exceções com stack, e o
  `ops.erros()` lê dali.
- **Valor:** "erros recentes" de verdade, agrupados, em vez de garimpar `docker compose logs`.
- **Recursos:** ~300 MiB de RAM, ~1–2 GB de disco com retenção de 30 dias. **Custo:** 0.
- **Risco:** exceções podem carregar PII e token, então é preciso `send_default_pii=false` e scrubbing. Para os apps do node 1 enviarem ao node 2,
  o node 1 precisa alcançar a porta de ingest pelo tailnet (sentido node 1 → node 2, só nessa porta).
- **Esforço:** M (mexe no código dos apps de cliente). **Exige do Pedro:** aprovar a dependência nova no MultiVideos/gold-crm.

### 13 Runner efêmero do GitHub Actions — só repos privados
- **O que é:** um runner oficial `--ephemeral` em container no node 2 (um job por container, destruído depois), com limite de
  2–4 vCPU e 4 GiB, label `ayanami`, registrado **só** nos repos privados (`multivideos-backend`, `gold-crm`, `wedding-*`).
- **Valor:** builds Docker com cache local (camadas do PHP/composer) mais rápidos que no runner hospedado, e economia dos
  minutos privados do plano grátis. **Nunca no `magi-assistant-ai` (público):** o GitHub recomenda não usar runner
  self-hosted em repo público, porque um PR de fork executa código na máquina. O caso PyTorch e o hackerbot-claw que abriu a brecha do Trivy
  mostram o risco.
- **Custo:** 0 de infra. Atenção: a cobrança de US$ 0,002/min para self-hosted foi anunciada para 01/03/2026 e **adiada**. Conferir
  o status atual antes. Repos públicos seguem grátis no hospedado.
- **Risco:** o runner fica **no mesmo host da Ayanami e dos backups**. Um job comprometido (dependência maliciosa) roda ao lado
  dos dumps do node 1. Mitigações: usuário/rede Docker separados, sem acesso ao volume `/dados`, sem Docker socket do host
  (usar build sem daemon ou um DinD isolado), e o segredo de deploy do node 1 continua só no GitHub. Se isso parecer muito, ficar no hospedado.
- **Esforço:** M. **Exige do Pedro:** decidir se a economia compensa e registrar o runner (token de registro).

### 14 SOPS + age para segredos
- **O que é:** os `.env` de produção (node 2, e o modelo do node 1) ficam cifrados com SOPS + age num repo privado `infra-segredos`.
  O deploy decifra com a chave age guardada só no GitHub Secrets e no cofre pessoal do Pedro. Junto vem um inventário (nome, onde é
  usado, quando roda) que alimenta a ideia 8.
- **Valor:** acaba com o ".env que só existe no servidor" (o INFRA.md teve o incidente do rsync sobrescrevendo o `.env`). Desastre
  vira `git clone` + `sops -d`. O Infisical self-hosted é mais um serviço para operar, então não vale nessa escala.
- **Peças:** SOPS 3.x, age 1.x. **Recursos/custo:** 0. **Risco:** perder a chave age = perder tudo, então ela vai para papel/cofre.
- **Esforço:** M. **Exige do Pedro:** guardar a chave age e migrar os `.env` uma vez.

### 15 Relatório semanal de higiene
- **O que é:** um job de domingo que junta: pacotes de segurança pendentes (`unattended-upgrades`), `reboot-required`, crescimento de
  disco por volume Docker, imagens órfãs, tamanho dos logs json (o INFRA.md recomenda `max-size`), resumo do Trivy e status dos backups.
  A Condessa lê em 30 segundos ou manda em texto.
- **Valor:** manutenção preventiva sem o Pedro abrir SSH. **Recursos/custo:** 0. **Risco:** baixo (verbos `disco`/`apt` só-leitura no
  node 1). **Esforço:** P. **Exige do Pedro:** nada.

### 16 Logs centralizados — VictoriaLogs + Vector
- **O que é:** o Vector no node 1 lê os logs json do Docker, aplica redação (tokens/senhas) e envia ao VictoriaLogs no node 2 pelo tailnet.
  Consulta por LogsQL, e o `ops.erros()` pesquisa ali quando não houver Bugsink.
- **Valor:** busca histórica ("quando o worker começou a perder AMQP?") sem depender de o container ainda existir.
  O VictoriaLogs usa bem menos RAM/disco que o Loki em benchmarks públicos (relatos de < 50% de CPU/RAM e ~40% menos disco).
- **Recursos:** VictoriaLogs ~150–250 MiB, ~2–5 GB de disco com retenção de 14 dias. Vector no node 1 ~50 MiB.
- **Risco:** é o item que mais **instala coisa no node 1** e o que mais move dado sensível. Fica atrás das ideias 9/12. **Esforço:** M.
- **Exige do Pedro:** instalar o Vector no node 1 e definir a retenção.

### 17 VictoriaMetrics + Grafana
- **O que é:** um TSDB compatível com Prometheus (VictoriaMetrics single-node, release atual), mais `node_exporter`, `postgres_exporter`
  (`pg_monitor`), `rabbitmq_prometheus` e Grafana. Painéis ricos e PromQL.
- **Valor:** só se o Beszel ficar curto (métricas de aplicação customizadas, SLOs). É uma pilha maior para manter.
- **Recursos:** ~400 MiB juntando VM e Grafana, ~2 GB por ano. **Custo:** 0. **Risco:** mais exporters no node 1. **Esforço:** M.
- **Exige do Pedro:** nada, mas é o ponto onde o "zero operação manual" começa a ceder.

### 18 Status page pública
- **O que é:** a página de status do Gatus publicada em `status.dekasis.com.br` (só leitura, só serviços de cliente).
- **Valor:** profissionaliza o MultiVideos e o gold-crm diante dos clientes. **Custo:** 0. **Risco:** é o **primeiro serviço público** do
  node 2. Dá para expor via Cloudflare Tunnel/Tailscale Funnel em vez de abrir porta, ou gerar estático e publicar na Vercel.
- **Esforço:** P. **Exige do Pedro:** a decisão de expor e o DNS.

### 19 Registry/cache de imagens (Zot)
- **O que é:** um registry OCI leve no node 2, usado como pull-through cache do Docker Hub/ghcr para os dois nodes e o runner.
- **Valor:** baixo hoje, porque o ghcr já atende. Ajuda contra rate limit do Docker Hub e acelera builds do runner (ideia 13).
- **Recursos:** ~60 MiB, disco variável (5–20 GB). **Risco:** baixo (tailnet). **Esforço:** P. **Exige do Pedro:** nada.

### 20 Standby frio do MultiVideos no node 2
- **O que é:** um runbook mais um **ensaio trimestral**: com o último dump (ideia 1) e a imagem do ghcr, subir o MultiVideos inteiro
  no node 2 num compose isolado, rodar o smoke e derrubar. Em desastre real, troca o DNS.
- **Valor:** RTO de horas em vez de dias se o node 1 morrer. Não é HA, e o INFRA.md já diz que HA é outro projeto.
- **Recursos:** só durante o ensaio (~4 vCPU, 6 GiB por 30 min). **Risco:** o ensaio **não pode** publicar no Facebook, então precisa de
  `.env` de ensaio sem tokens válidos e workers de publicação desligados. **Esforço:** G.
- **Exige do Pedro:** aprovar o runbook e estar presente no primeiro ensaio.

---

## Ordem sugerida

1. **Já:** 6 (vigia do vigia), 2 (Gatus), 3 (Beszel host-only). Nada disso exige credencial do node 1.
2. **Com o Pedro, numa sessão de ~30 min:** a porta única só-leitura no node 1, mais o B2. Isso destrava 1 (backup), 9 e 15.
3. **Depois:** 4 (alerta inteligente) e 5 (SRE de bolso) juntam tudo na Condessa. Em seguida 7, 8, 10 e 11 (todos P).
4. **Sob decisão:** 12, 13, 14, 16, 18. **Só se faltar:** 17, 19. **Projeto à parte:** 20.

## Fontes (pesquisa 2026-10-28)
- Beszel vs Netdata: instapods.com/apps/beszel/vs/netdata ; VictoriaMetrics vs Prometheus: dbi-services.com/blog/prometheus-vs-victoriametrics
- Gatus vs Uptime Kuma (Gatus v5.37, Kuma 2.5.3): bitdoze.com/uptime-kuma-vs-gatus
- restic 0.19.1 / Kopia 0.23.1 / Borg 1.4.5: techfuelhq.com/homelab/restic-vs-borg-vs-kopia-2026 ; wz-it.com/en/blog/restic-borg-kopia-backup-comparison
- VictoriaLogs vs Loki: truefoundry.com/blog/victorialogs-vs-loki ; docs.victoriametrics.com/victorialogs/faq
- Trivy/TeamPCP (CVE-2026-33634): microsoft.com/en-us/security/blog/2026/03/24/… ; safedep.io/trivy-teampcp-supply-chain-compromise
- Cobrança de runner self-hosted (adiada): github.blog/changelog/2025-12-16-… ; resources.github.com/actions/2026-pricing-changes-for-github-actions
- Runner self-hosted em repo público: docs do GitHub "Adding self-hosted runners" ; synacktiv.com/publications/github-actions-exploitation-self-hosted-runners
- SOPS vs Infisical: infisical.com/docs/documentation/getting-started/concepts/deployment-models ; devtoollab.com/blog/best-secrets-management-tools
