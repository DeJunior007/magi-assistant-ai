# Brief — SDD `condessa-celular` (app Android nativo) — 2026-10-21

## Pedido do Pedro (decisões fixas)
- No celular quem aparece é **a Condessa** (cabelo rosa, a mesma do HUD: pisca, mexe a boca ao falar,
  olha, reage). A **Ayanami é o cérebro invisível** (API central no node 2): o Pedro nunca fala com ela direto.
- **App Android nativo (APK)**, não PWA. Celular Android. Instalado fora da Play Store, com
  **atualização automática pelo próprio app** (a Ayanami serve o APK novo; o CI gera e publica).
- **Voz:** palavra de ativação **"Condessa"** (com app aberto e, se viável, em segundo plano com
  serviço em primeiro plano + notificação), **botão do fone Bluetooth** chama a Condessa e a resposta
  sai no fone, e **digitar**. Segurar-para-falar continua como recaída.
- **Tela principal = opção A do design** (Claude Design, artefato "Condessa no celular — 3 ideias",
  artboard A): ela em tela cheia sobre fundo escuro com brilho rosa; topo com estado (OUVINDO/PENSANDO/
  FALANDO) e "PC ● ONLINE"; legenda grande da fala dela embaixo com onda de voz; atalhos em pílulas
  (TV da sala, Notícias · N, Tarefas); base com botão grande de falar (dica "CONDESSA" OU SEGURE),
  teclado e "mais" (gaveta com TV, notícias, servidor, tarefas, ajustes). Cores do HUD: fundo #07060b/
  #120c18, lilás #b392f0, rosa #f2a7c3; fontes Rajdhani (rótulos), JetBrains Mono (estado), Inter (texto).
- **MVP primeiro, lapidar depois** ("pro MVP tá bom, começa com ela"): animação básica no MVP —
  respiração, piscada (olhos B1→B2→B3), boca pela amplitude da fala (C1/C2/C3), estados
  ouvindo/pensando/falando; olhar, reações e humor completos ficam para depois.
- **TV no app**: hoje nenhuma TV apareceu porque o `magi-casa` não está rodando/pareado no PC
  (pendência C1.S2 com o Pedro). O app mostra as TVs que a Ayanami conhece (`/v1/casa/estado`) e um
  estado vazio útil ("nenhuma TV pareada — no PC: magi-casa descobrir") em vez de nada.

## O que já existe (não reinventar)
- Repo `/home/pedrojr/Documentos/magi-assistant-ai` (PÚBLICO no GitHub: nenhum segredo/IP/nome de
  tailnet em commit). SDD da Ayanami: `specs/ayanami-central/` (requirements, design, spec §1–§17,
  tasks com tudo o que foi feito e Sobras). Contrato do elo `magi/elo/` (§1), API REST/WS/SSE (§2:
  pareamento por código, tokens por dispositivo, `/v1/turno` com áudio webm/opus e resposta
  SSE + áudio ogg, `/v1/eventos` SSE, `/v1/feed`, `/v1/casa/*`, `/v1/servidor`, `/v1/tarefas`,
  `/v1/push/*`, confirmações), modo nuvem quando o PC está off.
- **PWA atual** em `ayanami/pwa/` (P1.x/P2.x): vira recaída/legado; o app nativo usa a mesma API.
- **Retrato em partes** do HUD: `hud/wired/portrait.py` (`PARTS_ORDER`, ordem de desenho, estados,
  piscada, boca pela fala, olhar) e a arte em `~/.local/share/magi/condessa/` (`portrait.toml`, `parts/*.png`,
  `eyes/*.png`, `mouth/*.png`, todas 1024×1024 camadas sobrepostas). Ordem de pintura: back, back_tip,
  tail_l(+_tip), tail_r(+_tip), arm_l, arm_r, body, head, eyes/<id>, mouth/<id>, lock_l, lock_r,
  bangs_c (ou bangs), clip. Estados em `portrait.toml` [states]/[speech]/[gaze].
  A arte é do Pedro (não é material com copyright de terceiros), mas **não vai para o repo público**:
  o app baixa a arte da Ayanami (rota autenticada nova) na 1ª abertura e guarda em cache.
- Ayanami no ar: node 2, `https://<host>.ts.net` via Tailscale (o celular precisa do app Tailscale
  ligado); domínio `ayanami.dekasis.com.br` só aponta para o IP do tailnet. CI/CD da Ayanami no
  GitHub Actions (imagens ghcr + deploy por SSH).
- Palavra de ativação do PC: ver como o satélite/núcleo faz hoje (`magi/satellite/`, wake word
  "Condessa") — reaproveitar o modelo se for openWakeWord/ONNX.

## A decidir no SDD (com padrão)
Kotlin + Jetpack Compose (padrão) vs Flutter; motor de wake word no Android (openWakeWord ONNX com
onnxruntime-android — padrão — vs Porcupine com chave); serviço em primeiro plano para ouvir em segundo
plano (bateria!) — padrão: só com app aberto + atalho/Bluetooth em segundo plano, segundo plano opcional;
build do APK no CI (GitHub Actions) com assinatura (keystore em secret) e publicação na Ayanami
(`/v1/app/versao`, `/v1/app/apk`); notificações (FCM exige Google; alternativa: SSE/WebSocket em serviço
ou UnifiedPush/ntfy) — decidir mantendo baixo consumo; rota da arte do retrato; minSdk.

## Formato
Igual aos SDDs do repo (`specs/condessa-overlay/`, `specs/ayanami-central/`): requirements (EARS, D* com
padrão, "precisa do Pedro"), design, spec (assinaturas, rotas novas na Ayanami, formatos, CA-M…), tasks
(regras para o agente com as proibições do repo, ≤ 50–60k por tarefa, teto 128k, grafo, ondas,
Lê/Escreve/Depende de/Orçamento/Pronto/Paralelo). Código Android em `android/` no mesmo repo.
