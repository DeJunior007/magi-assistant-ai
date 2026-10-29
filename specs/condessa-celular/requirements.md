# Requisitos — Condessa no celular (app Android nativo)

Fonte: [brief.md](brief.md) (pedido do Pedro de 2026-10-21, decisões fixas) e o SDD da Ayanami
(`specs/ayanami-central/`, spec §1–§2, §14–§15, *Sobras* P1.x/P2.x/Y6.x). Este arquivo é o **PRD**.
Arquitetura em [design.md](design.md); contratos e números em `spec.md`; implementação em `tasks.md`
(os dois ainda não escritos). Critérios em EARS:

- **O app DEVE …** — sempre vale. **QUANDO** gatilho, **o app DEVE** … — reação a evento.
- **ENQUANTO** estado, **o app DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Glossário

| Termo | Significado |
| --- | --- |
| **Condessa** | A personagem que o Pedro vê e com quem fala (cabelo rosa, a mesma do HUD). |
| **Ayanami** | API central no node 2 (`https://<host>.ts.net`, só no tailnet). Cérebro invisível: o Pedro nunca fala "com a Ayanami". |
| **Modo PC / modo nuvem** | O turno vai ao `magi-core` do PC (ligado) ou é atendido pela própria Ayanami (PC off), spec Ayanami §6. |
| **Retrato em partes** | Arte 2.5D em camadas 1024×1024 (`parts/`, `eyes/`, `mouth/`, `portrait.toml`), a mesma do `hud/wired/portrait.py`. |
| **Tela A** | Opção A do Claude Design ("Condessa no celular — 3 ideias"): ela em tela cheia, estado no topo, legenda + onda, pílulas, botão grande de falar. |
| **FGS** | *Foreground service* do Android (serviço em primeiro plano com notificação fixa). |
| **Turno** | Uma fala do Pedro e a resposta dela (`POST /v1/turno` → SSE `turno.texto`/`turno.fim` + áudio ogg). |

## Problema

O PWA (`ayanami/pwa/`, P1.x/P2.x) funciona, mas não é a Condessa: mostra um rosto estático por
estado (`rosto/*.webp`), só grava segurando o botão, não acorda pela palavra "Condessa", não atende o
botão do fone Bluetooth, depende do autoplay do Chrome para tocar a voz (Sobra P1.2: áudio com
Bearer lido em blob, só toca no fim do stream) e o Web Push passa pelo FCM do Chrome. No sofá ou na
rua, o Pedro não tem a presença que tem no PC: ela piscando, mexendo a boca e reagindo.

## Objetivo

Um app Android nativo (APK, fora da Play Store) em que **a Condessa** aparece animada em tela cheia
(tela A), ouve por "Condessa", pelo botão do fone ou segurando o botão, responde com voz no fone e
legenda grande, controla a TV, mostra notícias, tarefas e o estado do servidor numa gaveta, avisa
por notificação e **se atualiza sozinho** com o APK que a Ayanami serve. Fala só com a API da
Ayanami pelo Tailscale; nenhum segredo, IP ou arte no repositório público.

## Escopo

| Fase | Entra |
| --- | --- |
| **MVP (M)** | Tela A com ela animada básica (respiração, piscada B1→B2→B3, boca C1/C2/C3 pela amplitude, estados dormindo/ouvindo/pensando/falando); falar segurando, por "Condessa" com o app aberto e pelo botão do fone BT; digitar; legenda e onda; TV (pílula + gaveta, estado vazio útil); gaveta com notícias, tarefas, servidor e ajustes; pareamento por código; notificações; auto-update; detecção de Tailscale/Ayanami/PC; arte baixada da Ayanami com cache. |
| **Depois (L)** | Olhar (`[gaze]`, íris), reações (`Reactor`), humor (happy/confused/alert), cabelo em pêndulo e malhas como o HUD; wake word em segundo plano (FGS `microphone`, opcional nos ajustes); widgets na tela inicial; atalho no bloco de Configurações rápidas; formatos de boca por sílaba (`shapes`). |
| **Fora** | Play Store, iOS, Wear OS; falar direto com o PC sem a Ayanami; arte, modelo de voz ou chaves no repo; abrir a Ayanami para a internet. |

O PWA continua no ar como recaída/legado (mesma API) e não é removido.

## Usuários e cenários

Um usuário: o Pedro, num celular Android dele (modelo e versão em "O que precisa do Pedro").

1. **Sofá com fone BT.** App em segundo plano, tela bloqueada. Pedro aperta o botão do fone → bip
   curto no fone → fala "apaga a TV da sala" → a voz dela responde no fone e a TV desliga. Com o app
   aberto, "Condessa, …" faz o mesmo sem tocar no celular.
2. **4G na rua com Tailscale.** Tailscale ligado; abre o app; "PC ● ONLINE" no topo; pergunta sobre
   uma tarefa; resposta em voz e legenda. Notificação de "pesquisa pronta" chega com o app fechado.
3. **PC desligado → modo nuvem.** Topo mostra "NUVEM" no lugar de "PC ● ONLINE"; conversa continua
   (modo nuvem da Ayanami); TV mostra "a casa está fora do ar" (o `magi-casa` roda no PC).
4. **Sem TV pareada.** `GET /v1/casa/estado` vem com `tvs: []`: pílula "TV da sala" vira "TV —
   parear" e a gaveta mostra "Nenhuma TV pareada — no PC: `magi-casa descobrir`".
5. **Tailscale desligado.** Ayanami não resolve: faixa "Sem conexão com a Ayanami — ligue o
   Tailscale" com botão que abre o app Tailscale; a Condessa fica dormindo; texto digitado fica na
   fila local e sai quando a conexão volta (até 10 min).

## Critérios de sucesso

Medidos no celular do Pedro, build `release`, conforme o design §11.

1. **Latência de turno** (soltar o botão / fim da fala → 1º som dela): p50 ≤ 3,5 s e p90 ≤ 6 s em
   Wi-Fi modo PC; p50 ≤ 5 s no 4G. 1º texto da legenda p50 ≤ 2,5 s. 20 turnos por cenário.
2. **Animação**: ≥ 55 fps (p95 do tempo de quadro ≤ 18 ms) falando e piscando; parada ≤ 30 fps
   (respiração) e dormindo ≤ 10 fps; nenhum quadro > 50 ms em 60 s (`FrameMetrics`/Macrobenchmark).
3. **Boca**: atraso entre o áudio e a troca de boca ≤ 80 ms (filmagem a 120 fps, 5 frases).
4. **Bateria**: app em segundo plano sem wake word ≤ 0,5 %/h atribuído ao app; com wake word em
   segundo plano (fase L) ≤ 3 %/h (`dumpsys batterystats`, 2 h, tela desligada).
5. **Wake word**: ≥ 90 % de acerto em 20 "Condessa" a 1 m com o app aberto; ≤ 1 falso/2 h em TV ligada
   (mesma meta do spike S4 do PC).
6. **APK**: ≤ 25 MB (só `arm64-v8a`), sem a arte; arte baixada ≤ 15 MB na resolução padrão.
7. **Atualização**: versão nova publicada → app atualizado em ≤ 24 h sem o Pedro abrir menu
   (um toque de confirmação do Android é aceito).
8. **Uma semana** usando o app em vez do PWA, sem voltar ao PWA por falta de função (nota do Pedro).

## Requisitos funcionais

### R1 — Condessa animada

- R1.1 O app DEVE mostrar a Condessa em tela cheia na tela A, sobre fundo escuro (`#07060b`→`#120c18`)
  com brilho rosa (`#f2a7c3`), desenhando as camadas do retrato na mesma ordem do HUD: `back`,
  `back_tip`, `tail_l`(+`_tip`), `tail_r`(+`_tip`), `arm_l`, `arm_r`, `body`, `head`, `eyes/<id>`,
  `mouth/<id>`, `lock_l`, `lock_r`, `bangs_c` (ou `bangs`), `clip`.
- R1.2 ENQUANTO acordada, o app DEVE animar respiração (sobe-e-desce do busto, `breath_px`/
  `breath_period` do `portrait.toml`) e piscada a cada 3–6 s por 120 ms (olhos meio → fechado → meio,
  do `blink` do estado; padrão B2/B3 sobre B1).
- R1.3 ENQUANTO falando, o app DEVE trocar a boca pela amplitude do áudio que está tocando:
  `< 0,18` → C1, `< 0,72` → C2, senão C3 (`[speech] mouths`), cada boca no ar ≥ 70 ms.
- R1.4 O app DEVE ter os estados `dormindo`, `ouvindo`, `pensando`, `falando`, com olhos/boca do
  `[states]` (`sleeping`, `listening`, `thinking`, `speaking`) e o rótulo no topo (EM ESPERA /
  OUVINDO / PENSANDO / FALANDO) em JetBrains Mono.
- R1.5 SE a arte ainda não foi baixada ou falhou, ENTÃO o app DEVE mostrar uma silhueta/placeholder
  rosa com o estado e continuar funcionando (voz e texto não dependem da arte).
- R1.6 (L) O app DEVE acrescentar olhar (`[gaze]`), reações e humor como o `PartsPortrait`.
- R1.7 QUANDO a tela desliga ou o app vai ao fundo, o app DEVE parar o laço de animação.

### R2 — Voz: segurar, wake word, Bluetooth

- R2.1 QUANDO o Pedro segura o botão de falar, o app DEVE gravar (mono, 16 kHz) até soltar ou 15 s;
  gravação < 400 ms é descartada; arrastar para fora cancela (mesma regra do PWA §14.4).
- R2.2 ENQUANTO o app estiver em primeiro plano e a escuta estiver ligada, o app DEVE detectar
  "Condessa" no aparelho com o mesmo modelo do PC (`condessa.onnx` + `melspectrogram.onnx` +
  `embedding_model.onnx`, limiar 0,6, `patience` 3, portão de energia) e então gravar até o silêncio
  (VAD) ou 15 s; desiste se ninguém falar em 5 s (`wake_no_speech_ms`).
- R2.3 QUANDO o botão do fone BT é apertado (play/pausa ou *hook*; segurar = comando de voz), o app
  DEVE abrir um turno de voz com o microfone do fone e tocar a resposta no fone, inclusive com o app
  em segundo plano e tela bloqueada (dentro do que o Android permite, D4).
- R2.4 ONDE "ouvir em segundo plano" estiver ligado (fase L, desligado por padrão), o app DEVE
  manter um FGS do tipo `microphone` com notificação fixa ("Condessa ouvindo — tocar para pausar")
  e parar a escuta quando a bateria estiver < 20 % ou em economia de energia.
- R2.5 O microfone NÃO DEVE ficar aberto fora de: gravação de turno, escuta de wake word com app
  aberto, ou FGS do R2.4. O som do turno nunca é guardado no aparelho depois do envio.
- R2.6 QUANDO um turno de voz começa ou termina por wake word/BT, o app DEVE tocar um bip curto
  (como o satélite) e, durante a fala dela, abaixar o próprio wake word (não acordar com a voz dela).

### R3 — Conversa e legenda

- R3.1 O app DEVE mandar o turno por `POST /v1/turno` (áudio Opus ou `{"texto"}`), ouvir o SSE
  `/v1/eventos` e tocar `GET /v1/turno/{id}/audio` assim que houver bytes (streaming, sem esperar o fim).
- R3.2 O app DEVE mostrar a fala dela como legenda grande (Inter) na base, com onda de voz animada
  pela mesma amplitude da boca, e a última fala do Pedro acima, pequena (transcrição, D9).
- R3.3 QUANDO o Pedro toca o teclado, o app DEVE abrir um campo de texto; turno de texto responde só
  em legenda, salvo "voz nas respostas de texto" ligada (pref `voz_em_texto`).
- R3.4 O app DEVE mostrar no topo "PC ● ONLINE" (modo PC) ou "NUVEM" (modo nuvem), pelo `modo` do
  `202` e por `GET /saude` (`online.pc`).
- R3.5 QUANDO chega `confirma` (SSE ou notificação), o app DEVE mostrar o cartão de confirmação com
  dois toques para aceitar (`POST /v1/confirma/{pedido}`), nunca aceitar da notificação (DS17).
- R3.6 SE não vier `turno.fim` em 50 s, ENTÃO o app DEVE voltar a dormindo e dizer "Ela não respondeu;
  tenta de novo?".
- R3.7 O app DEVE guardar o histórico do dia (texto) no aparelho, apagado à meia-noite.

### R4 — TV

- R4.1 O app DEVE listar as TVs de `GET /v1/casa/estado` e atualizar pelo SSE `estado`; a pílula
  "TV da sala" usa a `tv_padrao` (preferência) ou a primeira TV.
- R4.2 O controle DEVE mostrar só os botões das `caps` (ligar/desligar com segundo toque em 3 s, vol ±
  com repetição a 200 ms, mudo, canal ±, HDMI, apps, d-pad, digitar), via `POST /v1/casa/acao`.
- R4.3 SE `tvs` vier vazio, ENTÃO o app DEVE mostrar "Nenhuma TV pareada — no PC: `magi-casa
  descobrir`" e um botão "Como parear" (texto curto, sem rede).
- R4.4 SE a casa estiver offline (`online=false`/`503 casa_offline`), ENTÃO os botões DEVEM ficar
  cinza com "a casa está fora do ar" (PC desligado ou `magi-casa` parado).
- R4.5 O app DEVE aceitar o volume do celular (teclas físicas) como volume da TV ENQUANTO o controle
  da TV estiver aberto.

### R5 — Gaveta: notícias, tarefas, servidor, ajustes

- R5.1 O botão "mais" DEVE abrir uma gaveta com TV, Notícias, Tarefas, Servidor e Ajustes.
- R5.2 Notícias: cards de `GET /v1/feed` (rolagem com `antes=`), última página em cache local; a
  pílula mostra "Notícias · N" com N = cards novos desde a última visita.
- R5.3 Tarefas: lista por estado (`GET /v1/tarefas`), progresso, detalhe e cancelar (`DELETE`).
- R5.4 Servidor: `GET /v1/servidor` (CPU, RAM, disco, Minecraft no ar/jogadores/TPS, alertas, estado
  `ok|velho|ausente|corrompido`) e o resumo de `GET /saude` (fila, último backup, online).
- R5.5 Ajustes: nome do dispositivo, notificações e silêncio (`PUT /v1/dispositivo/preferencias`),
  TV padrão, voz nas respostas de texto, escuta por "Condessa" (app aberto / segundo plano), saída de
  áudio, versão + "procurar atualização", baixar a arte de novo, **sair** (`DELETE /v1/dispositivo`).

### R6 — Pareamento e conta

- R6.1 SE não houver token, ENTÃO o app DEVE abrir a tela Parear: 6 dígitos (ou QR do HUD com
  `c=`), nome sugerido `celular-pedro`, `POST /v1/pareamento/trocar`.
- R6.2 O endereço da Ayanami DEVE ser digitado/lido do QR no pareamento (nunca compilado no APK).
- R6.3 QUANDO qualquer rota der `401`, o app DEVE apagar o token e voltar a Parear.
- R6.4 Um aparelho = um token (`ayn_celular_…`); reinstalar exige parear de novo.

### R7 — Notificações

- R7.1 O app DEVE receber os mesmos avisos do Web Push (§15: `confirma`, `lembrete`, `tarefa`,
  `monitor`, `noticia`, `operacao`) com o app fechado, respeitando silêncio e limites do servidor.
- R7.2 Cada `tipo` DEVE ter um canal de notificação Android próprio (o Pedro silencia por canal);
  `confirma` e `lembrete` com importância alta.
- R7.3 Tocar a notificação DEVE abrir a tela certa (`confirma`, tarefa, notícia); a notificação não
  traz dado sensível (só `titulo` ≤ 40 e `resumo` ≤ 120, como o payload de hoje).
- R7.4 ENQUANTO o app estiver aberto, avisos chegam pelo SSE e NÃO DEVEM duplicar como notificação.
- R7.5 O transporte padrão NÃO DEVE depender do Google (D5).

### R8 — Atualização automática

- R8.1 O app DEVE consultar `GET /v1/app/versao` ao abrir e a cada 6 h (WorkManager, só com rede).
- R8.2 QUANDO houver `versionCode` maior, o app DEVE baixar `GET /v1/app/apk`, conferir o sha256 do
  arquivo e o certificado de assinatura (igual ao do app instalado) e só então instalar por
  `PackageInstaller`; qualquer diferença → apaga o arquivo e não instala.
- R8.3 O app DEVE pedir uma vez a permissão "instalar apps desconhecidos" (`REQUEST_INSTALL_PACKAGES`),
  explicando o porquê; recusada → mostra "atualização disponível" com botão.
- R8.4 SE `minimo` > versão instalada, ENTÃO o app DEVE bloquear turnos com "atualize para continuar".
- R8.5 O app NÃO DEVE instalar no meio de um turno nem de uma fala (espera ficar dormindo).

### R9 — Offline e erros

- R9.1 O app DEVE distinguir: **sem rede**, **Tailscale desligado** (sem VPN ativa / nome `.ts.net`
  não resolve), **Ayanami fora** (VPN ok, `/saude` falha), **PC off** (modo nuvem) e **casa fora**,
  com uma faixa e uma ação para cada (abrir Tailscale, tentar de novo).
- R9.2 Detecção por `GET /saude` (timeout 4 s) ao abrir, ao voltar ao primeiro plano, a cada 30 s
  com a tela aberta e quando a rede muda (`NetworkCallback`).
- R9.3 SE sem conexão, ENTÃO turnos de texto DEVEM ir a uma fila local (≤ 10 min, ≤ 5 itens) e sair
  quando voltar; voz e TV ficam desabilitados com o motivo.
- R9.4 SSE caiu → reconecta 1 → 30 s com `Last-Event-ID`.
- R9.5 Todo erro mostra frase curta em pt-BR; nenhum stack trace na tela.

### R10 — Segurança

- R10.1 O token DEVE ficar cifrado com chave AES-GCM do **Android Keystore** (não exportável); nunca
  em log, crash report, backup do Android (`allowBackup=false`, `dataExtractionRules` vazias) nem no repo.
- R10.2 A arte do retrato DEVE vir só da Ayanami (rota autenticada) e ficar no armazenamento interno
  do app; nunca no APK, no repo ou em pasta pública.
- R10.3 O app DEVE falar só HTTPS com o host do tailnet (`network_security_config` sem tráfego em
  claro); nenhum endpoint público, analytics, crash report externo ou SDK de terceiros com rede.
- R10.4 O APK, o keystore e os nomes do tailnet NÃO DEVEM ir a commit; keystore só em secret do CI.
- R10.5 O app NÃO DEVE pedir permissões além de: `INTERNET`, `RECORD_AUDIO`, `POST_NOTIFICATIONS`,
  `BLUETOOTH_CONNECT`, `FOREGROUND_SERVICE`(+`_MICROPHONE`, `_MEDIA_PLAYBACK`), `REQUEST_INSTALL_PACKAGES`,
  `WAKE_LOCK`, `ACCESS_NETWORK_STATE`, `RECEIVE_BOOT_COMPLETED` (só se o R2.4 estiver ligado).

## Requisitos não funcionais

| Id | Tema | Requisito |
| --- | --- | --- |
| RNF-C1 | Plataforma | Kotlin + Jetpack Compose; `minSdk 29` (Android 10), `targetSdk`/`compileSdk 36` (D2). |
| RNF-C2 | Tamanho | APK ≤ 25 MB, só `arm64-v8a`; R8/shrink ligado. |
| RNF-C3 | Memória | ≤ 200 MB PSS com a tela A aberta; bitmaps do retrato ≤ 64 MB. |
| RNF-C4 | Idioma | Tudo em pt-BR; fontes Rajdhani, JetBrains Mono, Inter empacotadas (OFL). |
| RNF-C5 | Testes | Lógica pura (máquina de estados, escolha de olho/boca, parser SSE, verificação do update) em testes JVM sem aparelho; nada de rede real nos testes. |
| RNF-C6 | Repo público | Nenhum segredo, IP, nome de tailnet, arte ou APK em commit; exemplos com valores falsos. |
| RNF-C7 | Ayanami | As mudanças na API são aditivas: o PWA continua funcionando sem mudar. |
| RNF-C8 | Acessibilidade | Botões ≥ 48 dp, `contentDescription` em pt-BR, legenda respeita o tamanho de fonte do sistema. |
| RNF-C9 | Bateria | Nenhum *wake lock* fora de turno; nenhum polling < 15 min com o app fechado; SSE só com app visível. |

## Decisões em aberto (precisam do Pedro)

- **D1 — Tecnologia.** (a) Kotlin + Jetpack Compose; (b) Flutter. **Padrão: (a)** — Media3,
  `PackageInstaller`, FGS e onnxruntime são APIs Android nativas; Flutter exigiria canais para quase tudo.
- **D2 — minSdk.** (a) 29 (Android 10: encoder Opus no `MediaCodec`/`MediaMuxer`); (b) 31 (Android
  12: `setRequireUserAction` no update e áudio BT moderno); (c) 26. **Padrão: (a) 29**, sobe para 31 se
  o celular do Pedro for ≥ 12 (simplifica BT e update).
- **D3 — Motor da wake word.** (a) openWakeWord ONNX com onnxruntime-android, mesmo `condessa.onnx`
  do PC; (b) Porcupine (chave da Picovoice, modelo treinado no console deles); (c) `SpeechRecognizer`
  contínuo. **Padrão: (a)** (sem chave, modelo já treinado e medido no S4).
- **D4 — Ouvir em segundo plano.** (a) Só com app aberto + botão BT/atalho em segundo plano; FGS
  `microphone` opcional nos ajustes (desligado); (b) FGS sempre; (c) nunca. **Padrão: (a)**.
- **D5 — Notificações.** (a) UnifiedPush com servidor ntfy próprio no node 2 (só tailnet) e o app
  ntfy como distribuidor; a Ayanami manda Web Push cifrado (o `pywebpush` de hoje) ao endpoint;
  (b) FCM (exige projeto Firebase e Google Play Services); (c) SSE num FGS próprio; (d) só ao abrir.
  **Padrão: (a)**, com recaída (d) + WorkManager a cada 30 min se o ntfy não estiver instalado.
- **D6 — Áudio do turno.** (a) Gravar no app e mandar à Ayanami (STT do PC/nuvem, como hoje); (b)
  `SpeechRecognizer` do Android e mandar texto. **Padrão: (a)** (mesma voz/STT do PC, transcrição
  própria, sem Google); (b) só como recaída se o envio de áudio falhar no 4G.
- **D7 — Formato do áudio.** (a) A Ayanami aceita também `audio/ogg;codecs=opus` (o app grava Ogg
  Opus); (b) o app gera WebM/Opus com `MediaMuxer`. **Padrão: (a)** (mudança aditiva pequena).
- **D8 — Onde fica o APK.** (a) Só na Ayanami (CI copia por SSH para `/opt/ayanami/dados/app/`);
  (b) GitHub Releases (repo público). **Padrão: (a)**.
- **D9 — Transcrição da fala do Pedro.** (a) Novo SSE `turno.ouvido` `{"turno","texto"}` (resolve a
  Sobra P1.2 item 4, "(voz)"); (b) seguir mostrando "(voz)". **Padrão: (a)**.
- **D10 — Resolução da arte.** (a) Ayanami gera WebP 512 px (cabe em ~15 MB) e 768 px; o app escolhe
  pelo tamanho da tela; (b) baixar as 1024 px e reduzir no aparelho. **Padrão: (a) 768 px** em telas
  ≥ 1080 px de largura, 512 nas menores.
- **D11 — Como a arte chega à Ayanami.** (a) Comando no PC `magi ayanami retrato enviar` →
  `PUT /v1/retrato` (token `pc`, escopo novo `retrato-enviar`); (b) `scp` manual para o node 2.
  **Padrão: (a)**.
- **D12 — Botão BT com app em segundo plano.** (a) `MediaSession` (Media3) ativa enquanto o app
  estiver aberto ou falou nos últimos 10 min + atender `VOICE_COMMAND` (segurar o botão); (b) virar
  "app assistente padrão" (`VoiceInteractionService`); (c) só com app aberto. **Padrão: (a)**; (b) só
  se o spike S2 mostrar que (a) perde o botão para o Spotify/YouTube.

## O que precisa do Pedro

1. Modelo do celular e versão do Android (fecha D2) e o fone BT que vai usar (spike S2).
2. Tailscale no celular já logado no tailnet (já está, pelo PWA) e o app **ntfy** instalado (D5 a).
3. Aprovar a criação do keystore de assinatura (gerado uma vez; cópia de segurança fora do repo) e
   os secrets `ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_SENHA`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_SENHA`
   no GitHub.
4. Primeira instalação manual do APK (baixar da Ayanami pelo navegador com o Tailscale ligado) e
   permitir "instalar apps desconhecidos" para o app.
5. Rodar `magi ayanami retrato enviar` no PC (D11) depois da rota existir.
6. Parear o `magi-casa` com as TVs (pendência C1.S2) para a TV aparecer no app.
7. Decidir D1–D12 (ou aceitar os padrões) e dar a nota da semana (critério 8).
