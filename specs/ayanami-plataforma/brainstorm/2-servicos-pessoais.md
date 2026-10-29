# Brainstorm 2 — serviços self-hosted pessoais que a Ayanami orquestra e expõe por MCP/voz

Data: 2026-10-28. Lente: o que instalar no node 2 (8 vCPU, 23 GiB, 221 GB livres, sem GPU, tudo no
tailnet) para que a Condessa use por **tool MCP**, **comando de voz** ou **evento proativo**.
Contexto completo em `contexto.md`.

## Como ler

- **Valor** e **esforço**: P (≤ 1 dia), M (2–4 dias), G (semana ou mais, ou exige operação contínua).
- Os números de CPU/RAM são **estimativas de planejamento** (docs, relatos da comunidade e
  experiência), não medições no node 2. Antes de subir qualquer coisa, a medição de verdade é
  `docker stats` mais o vigia da Ayanami.
- "Custo": o software é sempre gratuito. O custo real é disco, backup (B2 ~US$ 7/TB/mês quando
  existir) e, se houver, API paga dentro do teto de US$ 5/mês.
- Regra que vale para todos: porta só no tailnet, nada público; segredo em `.env` fora do git; o
  vigia monitora o container; o restic inclui o volume (exceto o que for cache).
- ★ = Top 5 por valor/esforço.

## Top 5 (resumo)

| Ideia | Serviço | Para quê | Esforço | RAM em repouso |
|---|---------|----------|---------|----------------|
| ★2 | **SearXNG** | busca web privada e gratuita para `pesquisar` e para a voz | P | ~200 MiB |
| ★3 | **Miniflux** | RSS como fonte das notícias da Ayanami, com o Postgres que já existe | P | ~50 MiB |
| ★4 | **Gatus** (ou Uptime Kuma) | vigia de fora dos sites do node 1 e da Vercel, com aviso por voz | P | ~30 MiB |
| ★5 | **llama.cpp noturno** (Qwen3-4B Q4) | resumo e classificação em lote sem gastar o teto de US$ 5 | M | 0 (sobe só no lote) |
| ★6 | **E-mail IMAP só leitura** | resumo diário da caixa ("chegou algo que importa?") | M | ~50 MiB (worker) |

Somando os 5 (mais o ntfy, que já está planejado): **~350 MiB em repouso**. No pico do lote
noturno, ~4 GiB e 6 vCPU durante ~1 h na madrugada. Cabe com folga.

---

## Ideias, por valor/esforço

### 1. ntfy: push para o celular (já planejado, pré-requisito, fora do Top 5)
- **O que é:** servidor de push por HTTP (Go), com app Android que funciona sem Google (UnifiedPush).
- **Uso:** é o **canal proativo** de quase todas as ideias abaixo ("o gold-crm caiu", "chegou o
  boleto", "resumo da manhã pronto"). Substitui o Telegram, que o vigia ainda não tem (sem token).
- **Recursos:** ~20–40 MiB, CPU ~0, disco < 100 MB (cache de mensagens).
- **Risco:** só no tailnet, então o celular precisa do Tailscale ligado para receber; aceitável.
  Usar token de acesso por tópico.
- **Esforço:** P. **Do Pedro:** instalar o app ntfy e assinar os tópicos.

### ★2. SearXNG: busca web privada (Top 5)
- **O que é:** metabuscador que agrega Brave, DuckDuckGo, Bing, Mojeek, Wikipedia etc. e devolve
  JSON (precisa de `formats: [html, json]` no `settings.yml`).
- **Uso:** tool MCP `web.buscar(q, tempo?)`. É o motor da tarefa longa `pesquisar` e do modo nuvem
  ("Condessa, quando sai o patch do FIFA?"). Já existem servidores MCP prontos (`mcp-searxng`,
  `searxng-simple-mcp`), mas o caminho natural é uma tool a mais no `/mcp/` da Ayanami, chamando a
  API JSON.
- **Recursos:** repouso ~150–250 MiB (mais Valkey ~20 MiB), pico ~0,5 vCPU por rajada, disco < 1 GB.
- **Custo:** zero. Troca API de busca paga, o que **protege o teto de US$ 5**.
- **Risco:** IP de datacenter (Contabo) leva captcha ou bloqueio do Google, então desligar o Google
  e preferir Brave, DDG, Bing, Mojeek e Wikipedia. As consultas saem com o IP da VPS, não com o do
  Pedro, o que é bom para privacidade.
- **Esforço:** P. **Do Pedro:** nada.

### ★3. Miniflux: leitor RSS que alimenta as notícias (Top 5)
- **O que é:** leitor RSS minimalista (Go) com API REST completa. Usa Postgres, e dá para usar um
  banco separado no **Postgres que já existe**. Escolhido no lugar do FreshRSS (PHP, mais pesado,
  sem ganho para uso por API).
- **Uso:** o worker de notícias passa a puxar `entries?status=unread` do Miniflux, em vez de cada
  coletor buscar a fonte sozinho. O Miniflux cuida de ETag, retry, scraping de texto completo e
  feeds do YouTube e do Reddit. Voz: "Condessa, assina o feed do blog X" (tool `rss.assinar`) e
  "o que tem de novo do Godot?". Ao lido/descartado na Condessa corresponde o `mark read` no
  Miniflux, o que fecha o laço com a clusterização que já existe.
- **Recursos:** repouso ~30–60 MiB, pico ~0,2 vCPU no refresh, disco ~1–3 GB/ano com texto completo
  (configurar a retenção).
- **Risco:** baixo. **Esforço:** P (o serviço) e M (refatorar o coletor de notícias para consumir
  dele). **Do Pedro:** a lista inicial de feeds (OPML, se tiver).

### ★4. Gatus (ou Uptime Kuma): vigia externo do node 1 e dos sites (Top 5)
- **O que é:** monitor de disponibilidade. O **Gatus** é configurado por YAML (cabe no git e na CI,
  sem clicar em UI) e é bem leve. O **Uptime Kuma 2.x** tem UI mais bonita, mas a configuração mora
  no banco.
- **Uso:** checa só leitura (HTTP, TLS, DNS) MultiVideos, gold-crm, wedding (node 1), AotMine e
  tensura-mine (Vercel) e o próprio `magi.`/`ayanami.`. Evento proativo: a Condessa avisa por voz
  ou HUD "o gold-crm não responde há 3 min" e "o certificado do wedding vence em 7 dias". Tool
  `servicos.status()` para "tá tudo de pé?".
- **Recursos:** Gatus ~20–40 MiB; Kuma ~120–250 MiB. CPU ~0. Disco < 200 MB.
- **Risco:** zero para o node 1 (só lê de fora). Detecta queda de produção de cliente antes do
  cliente, que é o valor mais alto da lista.
- **Esforço:** P. **Do Pedro:** confirmar a lista de URLs e o que é crítico.

### ★5. LLM local em CPU (llama.cpp `llama-server`) para lote noturno (Top 5)
- **O que é:** `llama-server` (API compatível com OpenAI) com **Qwen3-4B Q4_K_M** (padrão) e,
  opcional, um 7–8B Q4_K_M para tarefas que pedem mais qualidade. Preferido ao Ollama porque é mais
  enxuto e dá controle fino de threads, mas o Ollama também serve.
- **Uso:** só fila `lenta`/`agendada`, entre 02h e 06h: resumo das notícias do dia, triagem do
  e-mail (ideia 6), tags dos documentos (ideia 8), "resumo da manhã" pronto às 07h e entregue pelo
  ntfy. **Nunca** em tempo real de voz, que continua com o Claude no modo nuvem e com o Qwen no PC.
- **Velocidade esperada em 8 vCPU compartilhadas (a medir com `llama-bench`):**
  - geração 4B Q4: ~10–20 tok/s; 8B Q4: ~5–10 tok/s;
  - processamento de prompt 4B: ~40–100 tok/s (é o gargalo no resumo de textos longos);
  - conta de lote: 200 artigos × (800 tokens de entrada + 120 de saída) com o 4B dá ~45 min de
    prompt + ~25 min de geração, **~1h10 por noite**.
  - Referências: relatos de ~15 tok/s (4B) e ~8 tok/s (8B) em i5-12400; vCPU de VPS costuma render
    menos.
- **Recursos:** repouso 0 (o container sobe só no lote, por profile ou job). Pico 4B ~3 GiB, 8B
  ~6 GiB com 8k de contexto; `cpus: 6` e `nice` para deixar 2 vCPU livres para Kokoro e Whisper. O
  job pausa se a fila `rapida` tiver trabalho. Disco ~2,5 GB (4B) + ~5 GB (8B).
- **Custo:** zero. Tira do teto de US$ 5 todo o trabalho que não precisa de qualidade de ponta.
- **Risco:** qualidade inferior em PT-BR, então fazer avaliação A/B contra o Claude em 30 amostras
  antes de trocar. Disputa de CPU, mitigada pela janela e pelo limite de cgroup.
- **Esforço:** M. **Do Pedro:** aprovar a janela noturna.

### ★6. E-mail só leitura via IMAP: resumo diário (Top 5)
- **O que é:** não é um serviço novo, é um worker da Ayanami que lê IMAP (Gmail com senha de app,
  ou outro provedor), **sem nunca enviar nem apagar**, só com `BODY.PEEK` para não marcar como lido.
- **Uso:** lote noturno ou de hora em hora: classifica (llama.cpp local) em importante / boleto /
  promo / ruído e guarda remetente, assunto, resumo e embedding e5 no pgvector. Voz: "Condessa,
  chegou alguma coisa importante?" e "acha o e-mail da Contabo sobre a fatura" (tool
  `email.buscar`). Proativo: "boleto da internet vence amanhã".
- **Recursos:** ~50 MiB no worker, pico ~0,3 vCPU mais o LLM no lote. Disco ~0,5–2 GB/ano guardando
  só resumos e cabeçalhos, sem o corpo inteiro.
- **Risco:** **o mais sensível da lista** (a senha de app dá leitura total da caixa). Mitigações:
  senha de app revogável, segredo só no `.env` do node 2, conta IMAP só leitura se o provedor
  permitir, corpo do e-mail **não** vai para o Claude salvo pedido explícito (resumo feito local).
- **Esforço:** M. **Do Pedro:** gerar a senha de app (Gmail exige 2FA) e dizer quais rótulos ou
  pastas ler.

### 7. Paperless-ngx: documentos com OCR e RAG próprio
- **O que é:** gestor de documentos com OCR (Tesseract, pacote `por`), tags automáticas e API REST.
- **Uso:** pasta `consume` alimentada pelo Syncthing (ideia 10) ou por foto do celular. A Ayanami
  indexa o texto OCR no **pgvector com e5-small**, o que dá um RAG local sem a dependência do
  Gemini que o Searchless-ngx tem. Voz: "quando vence o IPVA?", "acha o contrato do aluguel",
  "quanto paguei de luz em agosto?". Proativo: "documento novo: boleto R$ 189, vence dia 5".
  Existe MCP de comunidade (PaperlessMCP, 43 tools), mas basta expor 2–3 tools pela Ayanami.
- **Recursos:** repouso ~0,7–1,2 GiB (web, worker, Redis), +~1 GiB se ligar Tika/Gotenberg (docx e
  e-mail). Pico de OCR 1–2 vCPU por documento. Disco ~2× o tamanho dos originais (original +
  arquivo PDF/A).
- **Risco:** documentos pessoais (RG, contratos), então backup criptografado (restic) é
  obrigatório.
- **Esforço:** M. **Do Pedro:** juntar e escanear os documentos iniciais (a parte chata, feita uma
  vez só).

### 8. Radicale: agenda, contatos e tarefas (CalDAV/CardDAV)
- **O que é:** servidor CalDAV/CardDAV mínimo (Python, arquivos em disco, versionável).
- **Uso:** voz "marca dentista quinta 15h" (tool `agenda.criar`), "o que tenho amanhã?", lembrete
  proativo 30 min antes via ntfy/HUD. As tarefas (VTODO) viram lista de compras e to-do pessoal
  ("adiciona café na lista"). No Android: DAVx5 + Tasks.org.
- **Recursos:** ~20–40 MiB, CPU ~0, disco < 50 MB.
- **Alternativa sem servidor:** ler o Google Agenda pela URL ICS secreta (só leitura). Mais fácil,
  mas não cria eventos e mantém o dado no Google. Baïkal é equivalente, mas é PHP e não tem ganho.
- **Esforço:** M (migrar agenda e contatos e configurar o celular). **Do Pedro:** decidir se sai do
  Google Agenda; DAVx5 é pago (barato) na Play Store e gratuito no F-Droid.

### 9. Audiobookshelf: servir os audiolivros que o PC já gera
- **O que é:** servidor de audiolivros e podcasts com app Android e progresso sincronizado.
- **Uso:** o pipeline do audiolivro (Kokoro + Qwen no PC) publica o MP3/M4B na biblioteca, e o
  Pedro ouve no celular, de qualquer lugar, com marcador. Voz: "Condessa, continua o livro" (tool
  pela API: posição atual). Também assina podcasts e pode baixá-los à noite.
- **Recursos:** ~100–200 MiB, CPU baixa (sem transcodificar), disco = tamanho da biblioteca.
- **Esforço:** P. **Do Pedro:** instalar o app. Sinergia direta com o que já existe.

### 10. Syncthing: cola de arquivos entre PC, celular e node 2
- **O que é:** sincronização P2P de pastas, sem servidor central nem conta.
- **Uso:** pastas `inbox-docs` (vai para o Paperless), `audiolivros` (vai para o Audiobookshelf),
  `notas`. Evento: "arquivo novo na inbox" dispara um job. Não precisa de tool MCP; é
  infraestrutura.
- **Recursos:** ~50–150 MiB, pico de CPU só no hash inicial. Disco = as pastas.
- **Esforço:** P. **Do Pedro:** instalar no celular (Syncthing-Fork) e escolher as pastas.
- **Descartados aqui:** Nextcloud (PHP, Redis, cron, ~1 GiB e manutenção constante, contra a regra
  de "nada manual") e Seafile (mais leve, mas não justifica para uma pessoa).

### 11. Karakeep (ex-Hoarder) ou Readeck: "guarda esse link"
- **O que é:** read-later e bookmarks com captura da página, busca de texto completo e tags por IA
  (aceita endpoint compatível com OpenAI, ou seja, o llama.cpp da ideia 5).
- **Uso:** compartilhar do celular ou falar "Condessa, guarda esse vídeo pra depois". No fim de
  semana: "o que eu salvei e não li?" e resumo noturno dos salvos. O Karakeep tem MCP próprio
  (verificar a versão).
- **Recursos:** Karakeep ~0,8–1,2 GiB (web + Chrome headless + Meilisearch), pico ~1 vCPU por
  captura. **Readeck** (Go, binário único) ~30–80 MiB: preferir se o peso importar.
- **Esforço:** P. **Do Pedro:** nada além do hábito.

### 12. Memos: notas rápidas por voz
- **O que é:** notas curtas estilo timeline (Go, SQLite), com API.
- **Uso:** "Condessa, anota: ideia de fase pro tensura-mine…". A nota vai para o Memos e é indexada
  no pgvector. "O que eu anotei sobre o MultiVideos semana passada?" vira RAG. Diferente da
  "memória" da Ayanami (fatos sobre o Pedro): aqui é caderno.
- **Recursos:** ~30–60 MiB, disco mínimo.
- **Esforço:** P. **Alternativa:** pasta Markdown via Syncthing (compatível com Obsidian), sem
  serviço nenhum.
- **Descartados:** Outline (exige S3/MinIO, Redis e OIDC obrigatório; pesado para uma pessoa) e
  Docmost (wiki colaborativa, sobra para uso pessoal).

### 13. Vaultwarden: cofre de senhas (sem acesso da Ayanami)
- **O que é:** servidor compatível com Bitwarden (Rust), ~20–50 MiB.
- **Uso:** **de propósito, nenhuma tool MCP.** A Condessa nunca lê senha. Só evento: "backup do
  cofre ok" e alerta se o container cair.
- **Risco:** é o serviço que mais dói se perder. Backup restic diário + export criptografado
  mensal. No tailnet, o app funciona offline com cache e sincroniza quando o Tailscale conecta.
- **Esforço:** P. **Do Pedro:** migrar as senhas (export do gerenciador atual) e guardar a senha
  mestra fora de tudo. Valor alto para o Pedro, baixo para a Ayanami.

### 14. Actual Budget (ou Firefly III): finanças por voz
- **O que é:** Actual é orçamento envelope, local-first (Node, ~80–150 MiB). Firefly III é
  contabilidade completa (PHP, ~300–400 MiB + importador).
- **Uso:** "gastei 45 no mercado" lança a transação. "Quanto sobrou de lazer esse mês?" Proativo:
  "você passou 80% do orçamento de delivery". Já há MCPs de comunidade para o Actual (via
  `@actual-app/api`, ele não tem REST).
- **Risco:** **não há sync bancário brasileiro** nativo (GoCardless e SimpleFIN não cobrem o BR).
  Importar OFX/CSV do Nubank ou Inter é manual, o que fere a regra de "nada manual". Open Finance via
  agregador (Pluggy, Belvo) é pago. Dado financeiro sensível.
- **Esforço:** M. **Do Pedro:** disciplina de lançar ou exportar o extrato. Vale só se ele quiser
  orçamento de verdade.

### 15. Immich: fotos com busca semântica em CPU
- **O que é:** Google Fotos self-hosted. Busca por CLIP ("praia ao pôr do sol"), rostos, mapa.
- **Uso:** "Condessa, mostra fotos do aniversário da minha mãe de 2024" chama a API de busca
  inteligente e mostra no HUD ou no celular. Proativo: "há 5 anos…".
- **Recursos (atenção):** servidor ~0,5–1 GiB + Postgres próprio (VectorChord, não dá para dividir
  com o pgvector da Ayanami) ~300 MiB + **ML ~1,5–3 GiB quando carregado** (descarrega após ociosidade).
  O guia indica no mínimo 6 GiB e recomenda 8 GiB para a pilha completa. **Pico: indexação inicial
  em CPU leva horas a dias** para dezenas de milhares de fotos. Configurar concorrência 1 e rodar o
  ML só à noite, fora da janela do llama.cpp. Disco: biblioteca + ~15–20% de miniaturas, e é aqui
  que os 221 GB acabam.
- **Custo:** backup em B2 escala com a biblioteca (~US$ 7/TB/mês).
- **Risco:** fotos íntimas e de família. Disco e backup são o gargalo, não a CPU.
- **Esforço:** M. **Do Pedro:** tamanho real da biblioteca e decidir se o celular passa a fazer
  backup para lá.

### 16. Home Assistant: casa além das TVs
- **O que é:** hub de automação residencial. Desde a 2025.2 tem **servidor MCP oficial** (na
  2026.10 virou um botão), e existe o `ha-mcp` de comunidade (90+ tools).
- **Uso:** o `magi-casa` delega ao HA luzes, tomadas, ar e sensores; a Condessa fala com o MCP do
  HA (com confirmação, como hoje nas TVs).
- **Problema de topologia:** na VPS, o HA **não enxerga a LAN** (mDNS, Bluetooth, Zigbee). Só
  funcionam integrações de nuvem (Tuya, SmartThings…) ou o uso de um subnet router do Tailscale
  em casa, e o PC desligado derruba isso. O lugar certo do HA é **em casa** (Raspberry ou mini PC),
  com a Ayanami chamando pelo tailnet.
- **Recursos:** ~300–600 MiB. **Esforço:** M–G. **Do Pedro:** inventário de dispositivos. Só vale
  se houver mais do que as TVs.

### 17. n8n (ou Node-RED): automações visuais
- **O que é:** n8n tem gatilho MCP embutido e é fair-code (Sustainable Use License, livre para uso
  pessoal); ~250–450 MiB. Node-RED é mais leve (~80–150 MiB), com MCP só de comunidade.
- **Uso:** "receitas" sem código (webhook → planilha → ntfy).
- **Avaliação:** **sobreposição alta** com a fila procrastinate e os workers da Ayanami. O Pedro
  programa, e automação em código fica versionada, testada e deployada pela CI. Só faz sentido se
  ele quiser montar fluxos sem abrir o repo. Huginn: descartado (Ruby, parado, pesado).
- **Esforço:** P para subir, mas é uma segunda fonte de verdade para manter.

### 18. Jellyfin (sem *arr): mídia própria
- **O que é:** servidor de mídia.
- **Uso:** "toca o episódio 3 na TV da sala" combina com o `magi-casa` (cast para as TVs).
- **Recursos:** ~200–400 MiB parado. **Transcodificação em CPU é cara** (um stream 1080p H.264 pode
  ocupar 3–6 vCPU). Só é viável com direct play (o cliente toca o arquivo original).
- **Legalidade:** Jellyfin com mídia própria é legal. **Sonarr, Radarr e Prowlarr baixando torrent
  numa VPS Contabo: não.** Pirataria, notificação de copyright e risco de a Contabo suspender o
  servidor (que tem o node 1 de clientes na mesma conta). Descartado.
- **Esforço:** M. Valor baixo para o objetivo "cérebro da Ayanami".

### 19. Changedetection.io: complemento dos monitores de preço
- **O que é:** detecta mudança em páginas, com Playwright para sites com JS.
- **Uso:** os monitores de preço e disponibilidade da Ayanami delegam a ele os sites difíceis (JS,
  login). O webhook de mudança vira evento na Condessa.
- **Recursos:** ~100 MiB + navegador ~300–600 MiB quando usa Playwright.
- **Avaliação:** só vale se os monitores atuais falharem em sites com JS. **Esforço:** P.

---

## Recursos somados (cenário "tudo do Top 5 + 7, 9, 10, 12, 13")

| Bloco | Repouso | Pico |
|-------|---------|------|
| Ayanami hoje | ~320 MiB | — |
| ntfy + SearXNG + Miniflux + Gatus + worker IMAP | ~350 MiB | ~1 vCPU |
| Paperless-ngx | ~1 GiB | 2 vCPU (OCR) |
| Audiobookshelf + Syncthing + Memos + Vaultwarden | ~350 MiB | baixo |
| llama.cpp 4B (só 02–06h) | 0 | ~3 GiB, 6 vCPU |
| **Total** | **~2 GiB de 23** | **~6 GiB, à noite** |

Sobram ~15 GiB e a maior parte da CPU de dia, o que permite o Immich (ideia 15) depois, se o disco
e o backup couberem. O limite real **não é RAM nem CPU, é disco e backup** (fotos e documentos) e o
**tempo do Pedro** para alimentar dados iniciais.

## Ordem sugerida

1. ntfy (pré-requisito) → 2. SearXNG → 3. Gatus → 4. Miniflux → 5. llama.cpp noturno com A/B
contra o Claude → 6. IMAP (depende do 5 para o resumo ficar local) → depois Audiobookshelf,
Syncthing + Paperless, Radicale, conforme o Pedro topar alimentar os dados.

## Decisões que só o Pedro toma

- E-mail: autoriza senha de app só leitura? Quais pastas ou rótulos?
- Agenda: sai do Google Agenda (Radicale) ou fica só leitura via ICS?
- Fotos: tamanho da biblioteca e se o backup do celular vai para o node 2 (disco e B2).
- Finanças: quer orçamento com lançamento manual ou deixa de fora?
- Casa: tem dispositivos além das TVs? Se sim, HA em casa, não na VPS.

## Fontes consultadas (out/2026)

- llama.cpp em CPU: [bestllmfor.com, LLM local sem GPU](https://bestllmfor.com/guide/llm-local-cpu-sans-gpu/),
  [OpenBenchmarking llama.cpp](https://mail.openbenchmarking.org/result/2511187-PTS-LLAMACPP54&export=html),
  [itsfoss, 8 modelos sem GPU](https://itsfoss.com/testing-local-llms-without-gpu),
  [Radxa forum benchmarks](https://forum.radxa.com/t/llama-cpp-benchmarks/27813)
- Immich: [requisitos de hardware (ZimaSpace, secundária)](https://shop.zimaspace.com/pt/pages/immich-hardware-requirements);
  conferir a página oficial em immich.app antes de subir.
- Paperless MCP/RAG: [PaperlessMCP](https://mcpservers.org/servers/barryw/paperlessmcp),
  [Fast.io, MCP para documentos 2026](https://fast.io/resources/best-mcp-servers-document-management/)
- SearXNG MCP: [mcp-searxng](https://glama.ai/mcp/servers/ihor-sokoliuk/mcp-searxng),
  [searxng-simple-mcp](https://mcpservers.org/servers/Sacode/searxng-simple-mcp)
- n8n/Node-RED MCP: [n8n MCP Server Trigger](https://hackceleration.com/resources/integrations/n8n/mcp-server-trigger),
  [FlowFuse MCP nodes](https://flowfuse.com/changelog/2025/10/mcp-nodes/)
- Home Assistant MCP: [ha-mcp](https://mcpservers.org/ko/servers/zorak1103/ha-mcp),
  [guia raspberry.tips](https://raspberry.tips/en/?p=11213)
- Actual Budget MCP: [actual-mcp](https://mcpservers.org/tr/servers/s-stefanov/actual-mcp),
  [glama, integrações Actual](https://glama.ai/mcp/servers/integrations/actual-budget)
- Karakeep: [requisitos de hardware](https://shop.zimaspace.com/pages/karakeep-hardware-requirements),
  [selfhosting.sh](https://selfhosting.sh/apps/hoarder/)
