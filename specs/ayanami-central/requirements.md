# Requisitos — Ayanami central (nuvem da Condessa, casa e celular)

Fonte: pedido do Pedro de 2026-10-12 (a Condessa vira controladora da casa, "baixar ela no
celular", usar o node 2 da Contabo como a API central **Ayanami**), o levantamento da infra Contabo
(`MultiVideos/INFRA.md`, `sdd/remocao-lfm/`), `persona/ayanami.md` e `docs/PROXIMOS-PASSOS.md` §6
(satélite no Raspberry Pi) e §10 (voz local/Kokoro). Este arquivo é o **PRD**. Arquitetura em
[design.md](design.md); contratos e números em [spec.md](spec.md); implementação em
[tasks.md](tasks.md). Critérios em EARS:

- **X DEVE …** — sempre vale. **QUANDO** gatilho, **X DEVE** … — reação a evento.
- **ENQUANTO** estado, **X DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Glossário

| Termo | Significado |
| --- | --- |
| Ayanami | A **API central** no node 2 da Contabo: API HTTP, fila de tarefas, workers, backups, MCP. O nome deixa de ser só o agente de notícias; o coletor de notícias vira um dos workers dela (a persona de `persona/ayanami.md` continua valendo para o texto das notícias). |
| Node 2 | VPS Contabo 8 vCPU, ~23 GB RAM, sem GPU, hoje sem uso (status a confirmar, D-P1). |
| PC | O computador do Pedro, onde rodam `magi-core`, satélite, HUD e `magi-pg` (`127.0.0.1:54329`). |
| `magi-casa` | Processo novo na LAN (user unit; PC no início, Raspberry Pi depois) que fala com as TVs e se liga **de saída** à Ayanami. |
| Tailnet | A rede privada Tailscale do Pedro (PC, node 2, celular). Padrão de acesso (D2). |
| Dispositivo | Cliente registrado na Ayanami com token próprio: PC (`magi-core`), `magi-casa`, celular, cliente MCP. |
| Modo nuvem | A Condessa atendendo pela Ayanami quando o `magi-core` do PC está fora do ar. |
| Tarefa | Trabalho assíncrono na fila da Ayanami (pesquisa longa, lembrete, monitor, coleta, backup…). |
| Ação de casa | Comando para TV (ligar, volume, app…). "Desligar" é `danger` (pede confirmação). |

## Problema

1. A Condessa só existe no PC: com o PC desligado, ou longe dele, o Pedro não fala com ela.
2. A casa tem smart TVs (Samsung Tizen; TCL com Android/Google TV; Roku em vista) e a Condessa não
   controla nenhuma; cada TV tem um app/controle diferente.
3. Trabalho longo (pesquisa, "me avisa quando…", coleta de notícias a cada 2 h) roda no PC ou não
   existe; desligar o PC para tudo, e não há fila com repetição, prazo nem aviso de fim.
4. Não há backup nenhum do `magi-pg` (memória, gosto, atas, custos, notícias) nem das configs.
5. Não há como o Claude Code/Claude Desktop consultar notícias, tarefas ou estado da Condessa.
6. O node 2 (8 vCPU/23 GB) está parado desde que o MultiVideos tirou Whisper/LFM dele.

## Objetivo

Três lugares, um contrato:
- **Ayanami (nuvem, node 2):** API central privada (atrás do tailnet), com fila de tarefas
  assíncronas, workers por classe, backups cifrados fora da Contabo, servidor MCP e um modo nuvem
  da Condessa para quando o PC está desligado.
- **Casa (`magi-casa`, LAN):** uma interface única `TvDriver` para Samsung, Roku e Android/Google
  TV, chamada pela voz no PC (local, sem nuvem) e pelo celular (via Ayanami).
- **Celular (Android, PWA):** chat, apertar-para-falar, voz, controle remoto das TVs, feed da
  Ayanami, status das tarefas e notificações push.

## Escopo

**Dentro**, por fase (a ordem dos números não é a ordem obrigatória; A2 não depende da nuvem):

| Fase | Entrega |
| --- | --- |
| A0 | Node 2 confirmado, limpo e no tailnet; firewall; acesso SSH (precisa do Pedro). |
| A1 | Ayanami base: API, registro de dispositivos e tokens, Postgres 16 + pgvector próprio, fila, workers, healthcheck, alerta Telegram, deploy Compose em `/opt/ayanami`, CI quando houver secrets. |
| A2 | `magi-casa` + `TvDriver` (Samsung, Roku, Android TV), descoberta, pareamento, intents `tv.*` e `ActionTool` no PC. |
| A3 | Backups: dump noturno do `magi-pg` empurrado pelo PC, configs, base da Ayanami; restic cifrado externo; restore testado. |
| A4 | Workers: notícias saem do PC; tarefas longas do agente; lembretes; monitores; aviso no PC/celular. |
| A5 | Celular: PWA instalável, chat, PTT, voz, controle de TV, feed, tarefas, Web Push. |
| A6 | Roteamento da conversa PC↔nuvem e modo nuvem. |
| A7 | Servidor MCP (Streamable HTTP, token com escopos). |
| A8 | Convergência de memória PC↔nuvem (só depois da D6). |

**Fora** (agora): wake word no celular; app nativo/Flutter (D4); satélite de voz remoto; espelho
web do HUD; integração com o `condessa-engine`; Home Assistant e outros dispositivos (luz, ar,
tomada); qualquer porta pública além de SSH no node 2 (salvo D2); STT ao vivo na nuvem; GPU;
qualquer mudança no node 1 em produção (MultiVideos/wedding/gold-crm).

## Usuários e cenários

Usuário único: o **Pedro** (dono, único com acesso). Clientes técnicos: `magi-core`, `magi-casa`,
o celular dele, Claude Code/Claude Desktop pelo MCP.

1. **Voz no PC, na sala ao lado:** "Condessa, liga a TV da sala e abre o YouTube" → roteador local
   (`tv.*`) → `magi-casa` no mesmo PC → TV. Funciona com a internet caída.
2. **No sofá, pelo celular:** "Condessa, abre a Netflix na TV da sala e baixa o volume" (PTT no
   PWA) → Ayanami → `magi-core` do PC (ligado) → `magi-casa` → TV; ela responde em voz no celular.
3. **Controle remoto na mão:** abre o PWA, aba TV, aperta volume −, mudo, HDMI 2, sem falar.
4. **PC desligado, no ônibus:** "quais as notícias de hoje?" → modo nuvem responde com o boletim da
   Ayanami, em texto e voz. Pedido de TV nessa hora recebe "a casa está fora do ar" (D10).
5. **Pesquisa longa:** "pesquisa os melhores monitores OLED de 27 até R$ 4 mil e me avisa" →
   vira tarefa; o Pedro fecha o app; chega push "Pesquisa pronta" e a Condessa conta no PC quando
   ele volta.
6. **"Me avisa quando…":** "me avisa quando o Hollow Knight Silksong baixar de R$ 60 na Steam" →
   monitor agendado; push e aviso proativo quando bater.
7. **Backup noturno:** às 03:30 o PC envia o dump do `magi-pg`; a Ayanami cifra e manda ao storage
   externo; no dia 1 de cada mês um restore de teste roda sozinho e o resultado vai ao Telegram.
8. **Claude Code:** no terminal, o Pedro pergunta "o que a Ayanami tem de notícia de Frieren?" ou
   "lista as tarefas pendentes" e o Claude Code consulta pelo MCP da Ayanami.

## Critérios de sucesso

1. **TV pela LAN (voz no PC):** fim da fala → TV reage com p90 ≤ **1,5 s** em comando conhecido
   (igual ao RNF-04), medido em 20 comandos por driver.
2. **TV pelo celular fora de casa (botão do PWA, 4G):** toque → TV reage com p90 ≤ **1,5 s**;
   **(voz no PWA):** fim da gravação → TV reage com p90 ≤ **4 s**. 20 medições cada.
3. **Disponibilidade da Ayanami:** ≥ **99%** no mês (healthcheck externo a cada 1 min pelo tailnet,
   a partir do PC enquanto ligado e de um verificador no próprio node 2 para o Telegram).
4. **Backup:** RPO ≤ **24 h** para `magi-pg`; restore de teste mensal automático **verde** 3 meses
   seguidos; um restore completo manual da Ayanami num diretório novo em ≤ **2 h** (RTO), anotado
   em `docs/ops/ayanami-restore.md`.
5. **Custo mensal novo:** storage de backup ≤ **US$ 3/mês**; modo nuvem dentro do sub-teto da D11;
   nenhum serviço pago novo além desses (o node 2 já é pago; valor com o Pedro).
6. **Node 2 folgado:** em repouso ≤ **10%** de CPU total e ≤ **6 GB** de RAM sem Ollama.
7. **Nada exposto:** varredura de portas na IP pública do node 2 mostra só SSH (e a porta UDP do
   Tailscale), salvo decisão D2 diferente.
8. **Uma semana de uso** com o celular e as TVs sem o Pedro voltar ao controle original por falha
   (nota dele no fim da validação ao vivo).

## Requisitos funcionais

### R1 — Ayanami: API e dispositivos

**R1.1** A Ayanami DEVE ser um serviço HTTP (FastAPI + uvicorn) com Postgres 16 + pgvector próprio,
em Docker Compose em `/opt/ayanami` no node 2, com `restart: unless-stopped`.
**R1.2** A Ayanami DEVE escutar só na interface do tailnet (e em 127.0.0.1); ONDE D2 = público,
DEVE ficar atrás de Caddy com TLS automático e a mesma autenticação.
**R1.3** Todo pedido à API DEVE levar um token de dispositivo; a Ayanami DEVE guardar só o hash do
token, o nome, o tipo, os escopos e o último uso de cada dispositivo.
**R1.4** QUANDO o Pedro revogar um dispositivo (CLI `ayanami dispositivo revogar <nome>`), a
Ayanami DEVE recusar o próximo pedido dele com 401 e fechar as conexões abertas dele em ≤ 5 s.
**R1.5** A Ayanami DEVE manter um canal de saída por dispositivo conectado (WebSocket, com recaída
long-poll) para empurrar comandos e eventos ao `magi-core` e ao `magi-casa`; o PC e a casa DEVEM
iniciar a conexão (nunca a nuvem abre conexão para a LAN).
**R1.6** A Ayanami DEVE expor `GET /saude` com o estado de banco, fila, workers, último backup e
dispositivos online, sem dado pessoal.
**R1.7** SE um dispositivo cair, ENTÃO a Ayanami DEVE marcá-lo offline em ≤ 30 s (batimento) e os
clientes DEVEM reconectar sozinhos com espera crescente (1 s → 60 s).

### R2 — Fila de tarefas

**R2.1** A Ayanami DEVE ter uma fila de tarefas persistente (biblioteca da D3) com: repetição com
espera crescente, agendamento (hora fixa e cron), prioridade, chave de idempotência, cancelamento e
tarefas de longa duração (≥ 30 min) sem perder o trabalho num reinício.
**R2.2** QUANDO um cliente criar uma tarefa com a mesma chave de idempotência de outra ainda viva,
a Ayanami DEVE devolver a existente em vez de criar outra.
**R2.3** Cada tarefa DEVE ter estado visível (`na_fila`, `rodando`, `ok`, `falhou`, `cancelada`),
progresso opcional (0–100 e uma frase), origem (dispositivo) e resultado (texto + dados).
**R2.4** QUANDO o Pedro pedir cancelamento (voz, PWA, MCP), a tarefa DEVE parar em ≤ 10 s se
estiver rodando e nunca começar se estiver na fila.
**R2.5** SE uma tarefa esgotar as repetições, ENTÃO a Ayanami DEVE marcá-la `falhou`, guardar o
erro sem segredos e avisar como em R9 (só se a tarefa pedia aviso).
**R2.6** A fila DEVE separar classes de worker: **rápida** (≤ 10 s, ex.: comando, consulta),
**lenta-CPU** (STT/TTS/embeddings em lote), **agendada** (coleta, backup, monitores), com limite
de concorrência por classe (spec).

### R3 — Workers: o que roda na nuvem

Prioridade e custo estimado (a spec fecha os números medidos):

| Prio | Worker | Fase | CPU/RAM estimados |
| --- | --- | --- | --- |
| 1 | Backup e restore de teste (R4) | A3 | picos de 1 vCPU, ≤ 300 MB |
| 1 | Coletor de notícias (sai do `magi-ayanami.timer` do PC) + cluster/classificação pela API do Gemini | A4 | picos de 1 vCPU a cada 2 h, ≤ 500 MB |
| 1 | Tarefas longas do agente: pesquisa, resumo, lembrete/agenda, monitor de preço/disponibilidade | A4 | ≤ 1 vCPU, ≤ 500 MB |
| 2 | Kokoro TTS em CPU (voz no modo nuvem e cache de frases) | A6 | ~1–2 vCPU por fala, ~1 GB |
| 2 | Progresso AniList/Steam | A4 | desprezível |
| 3 | STT em CPU (whisper.cpp/faster-whisper small) só para áudio longo assíncrono | A4+ | 2–4 vCPU durante a tarefa, ~1–2 GB |
| 3 | Embeddings locais em CPU (modelo ONNX multilíngue pequeno) para busca | A8 | ~1 GB |
| 4 | Ollama em CPU, só lote noturno não urgente (D8) | — | 5–8 GB, 45–140 s/chamada |

**R3.1** QUANDO o coletor de notícias da Ayanami estiver no ar, o PC DEVE receber as notícias novas
nas tabelas `news_*` do `magi-pg` (sincronização puxada pelo PC), sem mudar `news_query`,
`proactive/news.py` nem o "Rádio Ayanami".
**R3.2** SE o PC não receber notícias da Ayanami por > 6 h com internet, ENTÃO o `magi-ayanami.timer`
local DEVE voltar a coletar até a Ayanami responder de novo (recaída; nunca os dois ao mesmo tempo).
**R3.3** QUANDO o agente da Condessa receber um pedido que ela classifica como longo ("pesquisa e me
avisa", "me avisa quando…"), ele DEVE criar uma tarefa na Ayanami e responder que deixou na fila,
sem afirmar resultado.
**R3.4** O STT na nuvem NÃO DEVE ser usado em turno ao vivo; só em tarefa assíncrona.
**R3.5** Os workers DEVEM respeitar o `Budget` e a regra `free_tier` (Gemini recusa dado pessoal):
tarefa com dado pessoal só usa provedor autorizado para dado pessoal.

### R4 — Backups

**R4.1** QUANDO der 03:30 (configurável) e o PC estiver ligado, o PC DEVE gerar `pg_dump` do
`magi-pg` (só leitura, sem parar o banco) e das configs (`~/.config/magi/` sem chaves) e enviar à
Ayanami pelo tailnet. SE o PC estiver desligado, ENTÃO o envio DEVE ocorrer em ≤ 15 min depois do
próximo login.
**R4.2** A Ayanami DEVE fazer backup cifrado com restic do que recebeu e da base dela para o storage
externo (D7), com retenção da D15, e a senha do repositório restic NÃO DEVE ficar só no node 2.
**R4.3** QUANDO for dia 1 do mês, a Ayanami DEVE restaurar o último snapshot num Postgres
descartável, conferir contagem de linhas de tabelas-chave e o `restic check`, e apagar o
descartável; o resultado (verde/vermelho) DEVE ir ao Telegram.
**R4.4** SE um backup falhar ou não houver snapshot novo em 36 h, ENTÃO a Ayanami DEVE alertar no
Telegram e no celular.
**R4.5** Nenhum passo de backup DEVE rodar `docker compose down`, `rm` de volume ou `DROP` no
`magi-pg`; o restore de teste nunca toca o `magi-pg` do PC.

### R5 — MCP

**R5.1** A Ayanami DEVE expor um servidor MCP (SDK oficial Python, transporte Streamable HTTP) no
mesmo host, autenticado por token de dispositivo do tipo `mcp`.
**R5.2** O MCP DEVE oferecer, por escopo: `ler` — notícias (busca/últimas), tarefas (listar/ver),
estado da Condessa (PC online, casa online, TVs e estado), memória (só leitura, ONDE D6/D13
liberarem); `tarefas` — criar/cancelar tarefa; `casa` — ação de TV; `memoria-escrever` — gravar
fato na memória.
**R5.3** Ação de casa `danger` e escrita de memória pelo MCP DEVEM pedir confirmação do Pedro (push
no celular ou pergunta no PC) e expirar sem efeito em 2 min sem resposta.
**R5.4** Toda chamada MCP DEVE ir ao registro de auditoria (R10.3).

### R6 — Casa e TVs

**R6.1** O `magi-casa` DEVE oferecer uma interface única `TvDriver`: ligar, desligar, volume +/−,
mudo, definir volume, canal +/−, entrada/HDMI, abrir app, tecla do controle, digitar texto e ler
estado, cada driver declarando o que suporta (capacidades).
**R6.2** QUANDO pedirem uma ação que o driver não suporta (ex.: "definir volume 20" onde só há
volume ±), o `magi-casa` DEVE emular se der (repetir teclas, com limite) ou devolver "não suportado"
para a Condessa dizer, nunca fingir sucesso.
**R6.3** Drivers obrigatórios: **Samsung Tizen** (WebSocket remoto 8001/8002, token de pareamento;
ligar por Wake-on-LAN), **Roku** (ECP HTTP 8060, sem pareamento), **Android/Google TV** (protocolo
Android TV Remote v2 com pareamento por código; ADB pela rede como recaída). Bibliotecas candidatas
(`samsungtvws`, `rokuecp`, `androidtvremote2`) com versões e limites fixados no design.
**R6.4** O `magi-casa` DEVE descobrir TVs na LAN por SSDP/mDNS e listar as novas para o Pedro
nomear ("TV da sala"); o pareamento (token/certificado) DEVE ficar no keyring ou em arquivo `0600`,
nunca no git nem no log.
**R6.5** SE ligar pela rede não funcionar (TV em espera profunda, opção de rede desligada), ENTÃO o
`magi-casa` DEVE responder "não consegui ligar" com a causa provável, e a doc DEVE dizer qual
opção ligar na TV.
**R6.6** O roteador local DEVE ter intents `tv.*` (ligar, desligar, volume, mudo, app, entrada) com
alvo por nome da TV e uma TV padrão; o agente DEVE ter `ActionTool` equivalentes; "desligar" DEVE
ser `danger`.
**R6.7** QUANDO o `magi-core` e o `magi-casa` estiverem no mesmo PC/LAN, o comando DEVE ir direto,
sem passar pela Ayanami (funciona sem internet).
**R6.8** O `magi-casa` DEVE ficar ≤ 1% de CPU e ≤ 80 MB de RAM em repouso no PC, sem GPU.

### R7 — Celular (PWA)

**R7.1** A Ayanami DEVE servir um PWA instalável no Android (manifesto, service worker, ícone),
pelo HTTPS do tailnet (D2), com login por pareamento de dispositivo (código mostrado no PC/HUD ou
QR), sem senha reutilizada.
**R7.2** O PWA DEVE ter: chat com a Condessa (texto), apertar-para-falar (grava no navegador, envia
o áudio), resposta em texto e voz, controle remoto por TV (botões das capacidades do R6.1), feed da
Ayanami (notícias/cards), lista de tarefas (ver/cancelar) e o rosto dela leve (D5).
**R7.3** O áudio gravado DEVE ir só à Ayanami (e dela ao PC ou ao STT), não ser gravado em disco do
servidor além do tempo do turno, e ser apagado ao fim (como RNF-10).
**R7.4** SE o celular estiver fora do tailnet, ENTÃO o PWA DEVE mostrar "sem conexão com a
Ayanami — ligue o Tailscale" e manter visível o último feed em cache, sem quebrar.

### R8 — Roteamento da conversa e modo nuvem

**R8.1** QUANDO o celular mandar um turno e o `magi-core` estiver online, a Ayanami DEVE
encaminhar o turno ao PC (mesma memória, persona e ferramentas) e devolver a resposta ao celular;
o PC DEVE responder no satélite de origem (celular), não no headset (como o R22 do MVP).
**R8.2** ENQUANTO o `magi-core` estiver offline, a Ayanami DEVE atender em modo nuvem com a mesma
persona e só ferramentas que façam sentido lá: notícias, tarefas, lembretes, estado, casa (se o
`magi-casa` estiver online).
**R8.3** No modo nuvem, a resposta DEVE deixar claro, quando importar, que ela não tem a memória
completa do PC (ex.: "estou sem a memória do PC agora"), até a A8.
**R8.4** O modo nuvem DEVE contar gasto na mesma tabela `costs` (réplica) e respeitar o sub-teto
da D11; ao bater o teto, só comandos locais (TV, tarefas, feed).
**R8.5** QUANDO o PC voltar online, a Ayanami DEVE enviar a ele o resumo dos turnos do modo nuvem
para entrar na memória do PC (fonte da verdade, D6).

### R9 — Notificações

**R9.1** A Ayanami DEVE mandar Web Push (VAPID) ao PWA instalado: tarefa pronta, monitor que bateu,
lembrete, notícia "bomba", backup com falha, pedido de confirmação (R5.3).
**R9.2** QUANDO o PC estiver online, o mesmo aviso DEVE chegar também como aviso proativo da
Condessa (fila de proatividade existente, com as regras de silêncio/jogo dela); o celular recebe o
push mesmo assim, salvo ONDE `push_com_pc = false`.
**R9.3** O texto do push NÃO DEVE trazer dado sensível (só título e resumo curto); o detalhe abre
no PWA.
**R9.4** Avisos de operação (falha de backup, worker parado, disco > 85%) DEVEM ir ao Telegram,
padrão do node 1.

### R10 — Observabilidade e operação

**R10.1** Cada serviço DEVE logar em JSON com nível, sem tokens, chaves, áudio nem texto completo de
conversa (só ids e tamanhos).
**R10.2** A Ayanami DEVE ter um painel simples de filas (página no PWA ou `ayanami fila`):
contagem por estado e classe, tarefas lentas, últimas falhas.
**R10.3** A Ayanami DEVE manter registro de auditoria de ações de casa, MCP, dispositivos e
backups (quem, quando, o quê, resultado), por 90 dias.
**R10.4** Deploy DEVE ser `git pull` + `docker compose up -d` em `/opt/ayanami` (manual na A1;
GitHub Actions → ghcr.io → ssh quando o Pedro cadastrar os secrets), com smoke `GET /saude`.
**R10.5** SE o disco do node 2 passar de 85% ou um worker ficar sem batimento por 5 min, ENTÃO a
Ayanami DEVE alertar no Telegram.

## Requisitos não funcionais

| ID | Requisito | Meta |
| --- | --- | --- |
| RNF-A1 | Dado pessoal fora do PC | Só para a Ayanami do Pedro (self-hosted, D6) e provedores já autorizados; regra `free_tier` mantida. Muda o RNF-10 do MVP ("memória só local"): precisa do OK do Pedro (D6). |
| RNF-A2 | Trânsito | Tudo cifrado (WireGuard do Tailscale ou TLS); nenhuma API em HTTP aberto na internet. |
| RNF-A3 | Repouso | Backups cifrados (restic); segredos em `.env` `0600` fora do git ou keyring; nada de segredo em log. |
| RNF-A4 | Acesso | Token por dispositivo, revogável, com escopos; ACL do Tailscale só para os dispositivos do Pedro; firewall do node 2 nega toda entrada menos SSH e Tailscale. |
| RNF-A5 | Custo | Storage ≤ US$ 3/mês; modo nuvem no sub-teto da D11; sem serviço pago novo. |
| RNF-A6 | Node 2 | Repouso ≤ 10% CPU e ≤ 6 GB RAM; picos de workers lentos limitados a 4 vCPU e 12 GB (cgroups do Compose), deixando folga ao sistema. |
| RNF-A7 | PC | `magi-casa` + clientes novos ≤ 1% CPU e ≤ 100 MB em repouso; nada na GPU (RNF-03); nenhuma queda de FPS em jogo (RNF-12). |
| RNF-A8 | Latência | Critérios de sucesso 1–2; comando local no PC continua ≤ 1,5 s (RNF-04). |
| RNF-A9 | Casa sem nuvem | Sem internet ou com a Ayanami fora, voz no PC → TV funciona igual (R6.7). |
| RNF-A10 | PC sem nuvem | Sem a Ayanami, tudo que o PC faz hoje continua (voz, agente, HUD, notícias pela recaída R3.2); o que depende da nuvem avisa por frase em cache. |
| RNF-A11 | Proibições do repo | Nada de `qdbus`/`gdbus` para KGlobalAccel/KWin; nada de `docker compose down`/`rm`/`DROP` no `magi-pg`; nada no node 1 em produção sem tarefa "precisa do Pedro". |
| RNF-A12 | Reinício | Serviços com reinício automático (systemd/Compose); fila sobrevive a reinício do node 2 sem perder tarefas aceitas. |

## Decisões em aberto (precisam do Pedro)

- **D1 — Nome e endereço.** (a) `ayanami` no tailnet (`ayanami.<tailnet>.ts.net`); (b) subdomínio
  público `ayanami.smartcal.com.br`; (c) outro nome. **Padrão até ele decidir: (a).**
- **D2 — Rede.** (a) Tailscale em PC, node 2 e celular, nada público; (b) WireGuard próprio
  (mais trabalho, sem conta externa); (c) público com Caddy + TLS + token (mais exposição).
  **Padrão até ele decidir: (a).**
- **D3 — Fila.** (a) `procrastinate` (fila no próprio Postgres: retry, cron, prioridade, trava de
  idempotência, cancelamento; um serviço a menos); (b) `arq` (Redis, assíncrona, sem prioridade
  nativa); (c) `taskiq`/`dramatiq` (Redis/RabbitMQ). **Padrão até ele decidir: (a)**; Redis só
  entra se o design mostrar necessidade (pub/sub do R1.5).
- **D4 — App do celular.** (a) PWA; (b) PWA empacotado como APK por TWA; (c) app nativo/Flutter.
  **Padrão até ele decidir: (a)**, (b) depois se faltar algo.
- **D5 — Rosto no celular.** (a) sprite leve por estado (dormindo/ouvindo/pensando/falando);
  (b) retrato em partes no canvas; (c) sem rosto. **Padrão até ele decidir: (a).**
- **D6 — Memória.** (a) `magi-pg` do PC é a fonte da verdade, a Ayanami guarda réplica/backup e o
  que é dela; (b) a nuvem vira a fonte; (c) dividida por tipo. Inclui aceitar que memória e
  histórico saiam do PC para a Ayanami (muda o RNF-10). **Padrão até ele decidir: (a)**, com
  réplica só no backup cifrado até ele aceitar a réplica viva.
- **D7 — Storage de backup.** (a) Backblaze B2 (fora da Contabo: um incidente não leva VPS e
  backup juntos); (b) Contabo Object Storage; (c) os dois. **Padrão até ele decidir: (a).**
- **D8 — Ollama no node 2.** (a) não; (b) só lote noturno não urgente. **Padrão: (a).**
- **D9 — A TCL.** Google TV/Android TV ou Roku TV? Define o driver. **Padrão até ele decidir:** a
  descoberta (R6.4) identifica; o código já traz os dois drivers.
- **D10 — Quem roda o `magi-casa`.** (a) PC (TV pelo celular só com o PC ligado); (b) Raspberry Pi
  sempre ligado (comprar/configurar). **Padrão até ele decidir: (a)**, código pronto para (b).
- **D11 — Gasto do modo nuvem.** (a) sub-teto `nuvem` de US$ 2 dentro do teto geral (US$ 5);
  (b) teto separado; (c) modo nuvem sem LLM (só feed, TV, tarefas). **Padrão: (a).**
- **D12 — Canal de aviso.** (a) Web Push no PWA + Telegram só para operação; (b) tudo no Telegram;
  (c) ntfy self-hosted. **Padrão até ele decidir: (a).**
- **D13 — Escopos do MCP.** (a) `ler` + `tarefas` ligados; `casa` e `memoria-escrever` desligados até
  ele ligar; (b) tudo ligado com confirmação. **Padrão: (a).**
- **D14 — Voz no modo nuvem.** (a) mesma TTS da OpenAI (`marin`) com cache, Kokoro só se bater o
  teto ou a OpenAI cair; (b) sempre Kokoro na nuvem (custo zero, voz diferente). **Padrão: (a).**
- **D15 — Retenção.** (a) 7 diários, 4 semanais, 6 mensais; (b) 30 diários. **Padrão: (a).**

## O que precisa do Pedro

1. Confirmar no painel da Contabo que o node 2 existe e não está agendado para cancelar; passar
   host, usuário e chave SSH (não ficam em arquivo do repo).
2. Limpar (ou autorizar limpar) os restos do MultiVideos no node 2: `/opt/multivideos`,
   `docker-compose.node2.yml`, volumes Ollama/Whisper, `wg0`, regras `ufw` antigas.
3. Criar a conta Tailscale e instalar no PC, no node 2 e no celular; aprovar a ACL.
4. Na TV: ligar "controle por rede"/"ligar pela rede" (Samsung, Roku) e aceitar o pareamento na tela
   ou digitar o código (Android TV); dizer o nome de cada TV.
5. Escolher o storage (D7), criar bucket e chaves, guardar a senha do restic fora do node 2.
6. Criar o bot/canal do Telegram (ou reaproveitar o do node 1) e passar o token.
7. Cadastrar secrets do GitHub para o deploy (`AYANAMI_HOST`/`USER`/`SSH_KEY`) quando quiser CI.
8. Responder D1–D15 (ou aceitar os padrões).
9. Validação ao vivo (TV por voz, celular fora de casa, restore manual) e uma semana de uso.
