# Design — Condessa no celular (app Android nativo)

Implementa [requirements.md](requirements.md). Seções citadas por `§`; "Ayanami §n" = 
`specs/ayanami-central/spec.md`. Versões conferidas em 2026-10-21 (fontes no fim); as marcadas
"fixar no S0" são as últimas estáveis conhecidas e a S0 grava a exata no `libs.versions.toml`.

## 1. Onde mora hoje (o que o app reaproveita)

```
celular (PWA /app) ──HTTPS Bearer──▶ Ayanami (node 2, tailscale serve :443 → 127.0.0.1:8740)
                                       ├─ /v1/turno ─▶ modo pc: WS ─▶ magi-core (PC) ─▶ STT/LLM/TTS
                                       │              modo nuvem: escuta/fala na própria Ayanami
                                       ├─ /v1/eventos (SSE: turno.texto, turno.fim, evento, estado, confirma)
                                       ├─ /v1/casa/* ─▶ WS ─▶ magi-casa (PC) ─▶ TVs
                                       └─ push.enviar (fila) ─▶ Web Push (pywebpush, VAPID)
```

- API e escopos: Ayanami §2 (o token `celular` já tem `conversa`, `casa`, `tarefas`, `feed`;
  `/v1/servidor` aceita `conversa`). Pareamento por código de 6 dígitos (§2.2).
- Retrato: `hud/wired/portrait.py` (`PartsAssets`, `PartsPortrait`, `PARTS_ORDER`,
  `MOUTH_LEVELS = (0.18, 0.72)`, `MOUTH_HOLD = 0.07`, `BLINK_EVERY = (3, 6)`, `BLINK_LEN = 0.12`,
  `PARTS_FPS 60/40/6`), arte em `~/.local/share/magi/condessa/` (≈ 72 MB em PNG 1024²: `parts` 15 MB,
  `eyes` 26 arquivos 32 MB, `mouth` 20 arquivos 25 MB).
- Wake word: `magi/satellite/wake.py` (`OpenWakeWordDetector` só ONNX, blocos de 80 ms = 1280
  amostras a 16 kHz, `WakeSpotter` com limiar, `patience`, recarga 2 s e portão de energia −50 dBFS
  com pré-rolagem de 16 blocos). Modelo próprio `condessa.onnx` (400 KB) + `melspectrogram.onnx` +
  `embedding_model.onnx`; config do Pedro: limiar 0,6, `patience` 3 (spike S4: 0 falso/h nos
  negativos reservados).
- PWA (`ayanami/pwa/`): telas e regras que o app copia em comportamento (PTT §14.4, resposta §14.5,
  TV §14.2, estados globais §14.3). Sobras que o app resolve: áudio com Bearer só tocava no fim
  (P1.2 item 1 — no nativo o OkHttp manda o cabeçalho e o ExoPlayer toca em streaming); fala do
  Pedro "(voz)" (P1.2 item 4 → D9); `TurnoFim` sai antes do áudio no modo pc (Y6.4 item 7).

## 2. Arquitetura

```
                ┌──────────── celular (Android) ─────────────┐
                │  :app  (Compose, telas, navegação, DI manual)│
                │    TelaA · Gaveta · TV · Notícias · Tarefas  │
                │    Servidor · Ajustes · Parear · Confirma    │
                │      │ StateFlow<UiEstado>                   │
                │  ┌───┴──────────┬───────────┬────────────┐  │
                │  │ :retrato     │ :voz      │ :rede      │  │
                │  │ assets+cache │ gravador  │ ApiAyanami │  │
                │  │ Animador     │ wake word │ SSE        │  │
                │  │ (puro, JVM)  │ BT/Media3 │ Saude      │  │
                │  │ Pintor       │ player+RMS│ Atualizador│  │
                │  └──────────────┴───────────┴────────────┘  │
                │  Keystore(token) · DataStore · WorkManager  │
                └──────────────────┬──────────────────────────┘
                     HTTPS (só *.ts.net) │ app Tailscale (VPN)
                ═════════════ tailnet ══╪════════════════════════
                                        ▼
        ┌──────────── node 2 ───────────────────────────────┐
        │ Ayanami API ── /v1/app/* (APK) ── /v1/retrato/*    │
        │      │  push.enviar ──Web Push──▶ ntfy (D5a)  ─────┼──▶ app ntfy ─▶ app (UnifiedPush)
        │      └─ WS ────────────────────────────────────────┼──┐
        └────────────────────────────────────────────────────┘  │
                                                                 ▼
        ┌──────────── PC / casa ───────────┐   GitHub Actions ─SSH─▶ /opt/ayanami/dados/app/
        │ magi-core (turno modo pc)         │   (APK assinado + versao.json)
        │ magi-casa ─▶ TVs                  │
        └──────────────────────────────────┘
```

Módulos Gradle em `android/` (um projeto, quatro módulos para isolar o que é testável na JVM):

| Módulo | Papel | Dependências principais |
| --- | --- | --- |
| `:app` | `MainActivity` (uma só), telas Compose, `ViewModel`s, navegação, notificações, `PackageInstaller` | Compose BOM, Navigation Compose, WorkManager, UnifiedPush connector |
| `:retrato` | `PortraitToml` (parser), `Animador` (puro: estado → olho/boca/respiração por instante), `RetratoCache` (download/verificação), `Pintor` (Canvas) | Compose UI graphics |
| `:voz` | `Gravador` (`AudioRecord` 16 kHz), `CodificadorOpus` (`MediaCodec` → Ogg), `WakeWord` (onnxruntime), `Vad`, `SessaoMidia` (Media3), `Tocador` (ExoPlayer + `AmplitudeProcessor`), `RotaAudio` (BT) | Media3, onnxruntime-android |
| `:rede` | `ApiAyanami` (OkHttp + kotlinx.serialization), `Sse` (okhttp-sse com `Last-Event-ID`), `Conectividade` (VPN/DNS/`/saude`), `Atualizador` (versão, download, sha256, certificado) | OkHttp, kotlinx.serialization, coroutines |

Pilha (D1 a): Kotlin 2.3.x (≥ 2.3.20), AGP 9.x (Kotlin embutido no AGP 9), Gradle ≥ 9.1, Compose BOM
**2026.09.00**, Media3 **1.11.1**, onnxruntime-android **1.27.0**, OkHttp 5.x, kotlinx.serialization
1.9.x, coroutines 1.10.x, DataStore 1.1.x, WorkManager 2.10.x, UnifiedPush connector 3.x (fixar no
S0). `minSdk 29`, `targetSdk 36`, `compileSdk 36` (D2; a Play exige 36 desde 31/08/2026 — não se
aplica a APK lateral, mas segue-se para pegar o comportamento atual). DI manual (um `Grafo` no
`Application`), sem Hilt: o app é pequeno e o build fica mais rápido.

## 3. Máquina de estados da Condessa

Estado de UI derivado de eventos locais (o app sabe melhor que o servidor quando está gravando ou
tocando); o servidor só dá `modo`, texto e fim.

```
                 wake/BT/segurar            soltar | VAD fim | 15 s
   ┌─────────┐ ──────────────────▶ ┌────────┐ ─────────────────────▶ ┌─────────┐
   │DORMINDO │                     │OUVINDO │                         │PENSANDO │
   │(espera) │ ◀── cancelar/<400ms─│        │                         │         │
   └─────────┘                     └────────┘                         └────┬────┘
        ▲   ▲                                         1º bloco de áudio   │ turno.fim sem áudio
        │   └──── turno.fim + fim do áudio (+1,5 s) ◀── ┌─────────┐ ◀────────┘ (texto: legenda e
        │                                               │FALANDO  │             volta a DORMINDO)
        └──── erro / 50 s sem turno.fim ────────────────└─────────┘
```

- `DORMINDO` usa `[states] sleeping` (olhos B14; à noite, 23h–7h, B15 fechados) e rótulo "EM ESPERA";
  com o app aberto ela respira e pisca (acordada-parada com olhos B1 nos primeiros 30 s após um
  turno, como o HUD). `OUVINDO` = `listening`, `PENSANDO` = `thinking` (B13/C7), `FALANDO` =
  `speaking` com a boca pela amplitude.
- `turno.texto` em `PENSANDO` já mostra a legenda (texto chega antes do áudio, Y6.4 item 7).
- Um turno por vez: wake/BT durante `FALANDO` interrompe a fala (para o player) e vai a `OUVINDO`
  (*barge-in* simples); durante `PENSANDO` é ignorado.
- O `Animador` (em `:retrato`, puro) recebe `(estado, nivel, agora)` e devolve `Quadro(olhos,
  boca, dyRespiracao, alphaPiscada)`: porta direta de `_eye_target`, `mouth_id` e `breath` do
  `portrait.py` (sem `gaze`, reações e `shapes` no MVP). Piscada: próxima em `uniform(3, 6)` s,
  duração 120 ms, meio (B2) no 1º e 3º terço, fechado (B3) no meio. Testes JVM com relógio falso
  comparam a sequência com uma tabela gerada do Python (`portrait.py`, mesma semente).

### 3.1 Boca sincronizada com o áudio

O `Tocador` (ExoPlayer, Media3 1.11.1) toca `GET /v1/turno/{id}/audio` (`audio/ogg;codecs=opus`,
em streaming; o cabeçalho `Authorization` vai pelo `OkHttpDataSource`). Um `AudioProcessor`
próprio (`AmplitudeProcessor`, passa o PCM adiante sem mudar, como o `TeeAudioProcessor`) calcula o
RMS a cada 20 ms, normaliza (pico móvel de 1,5 s, piso −50 dBFS → 0..1) e publica num
`StateFlow<Float>` com o carimbo do *presentation time* do bloco. Como o processador roda antes do
buffer do `AudioTrack`, o nível é atrasado pela latência de saída (`AudioTrack.getTimestamp`; no BT
A2DP ≈ 150–250 ms) antes de chegar ao `Animador`. Assim boca e onda andam com o som que sai do
fone, não com o que foi decodificado. `MOUTH_HOLD` 70 ms evita piscar entre bocas. A mesma série
alimenta a onda da legenda.

## 4. Pipeline de voz

```
AudioRecord 16 kHz mono (VOICE_RECOGNITION; fone BT: comunicação via setCommunicationDevice)
   │ blocos de 80 ms (1280 amostras int16)
   ├─▶ [escuta ligada] Portão de energia (−50 dBFS, pré-rolagem 1,28 s)
   │       └─▶ melspectrogram.onnx ─▶ embedding_model.onnx ─▶ condessa.onnx ─▶ WakeSpotter(0,6, patience 3)
   │                                                                           │ disparo
   ├─▶ [gravando] Vad (silero_vad.onnx ou energia) ─ fim após 800 ms de silêncio, máx 15 s ◀┘ (bip)
   │       └─▶ CodificadorOpus (MediaCodec "audio/opus" 24 kb/s) ─▶ Ogg em memória (≤ 50 KB)
   ▼
POST /v1/turno (multipart `audio`, audio/ogg;codecs=opus — D7 a) ─▶ 202 {turno, modo}
SSE /v1/eventos: turno.ouvido (D9) → linha do Pedro · turno.texto → legenda · turno.fim
GET /v1/turno/{id}/audio ─▶ ExoPlayer ─▶ AmplitudeProcessor ─▶ boca/onda ─▶ saída (fone ou alto-falante)
```

- **Por que gravar e mandar (D6 a), não `SpeechRecognizer`:** a Ayanami já tem STT nos dois modos
  (Whisper no PC, nuvem na Ayanami), a transcrição fica igual à do PC e nada passa pelo Google. O
  `SpeechRecognizer` (on-device só em alguns aparelhos; o serviço padrão é do Google) fica como
  recaída futura.
- **Wake word (D3 a):** porta Kotlin do `OpenWakeWordDetector` + `WakeSpotter`; os três `.onnx`
  vêm da Ayanami junto com a arte (rota da §7) — o `condessa.onnx` é do Pedro e não vai ao repo nem
  ao APK. Sessões ORT com 1 thread, `ORT_SEQUENTIAL`, `NNAPI` desligado (os modelos são minúsculos;
  CPU é mais previsível). Existe a lib comunitária `openwakeword-android-kt`; o design copia a ideia
  mas implementa as ~200 linhas aqui para manter o portão e a `patience` iguais ao PC.
- **Eco:** enquanto `FALANDO`, o wake word passa o limiar para 0,9 e usa `AcousticEchoCanceler`
  quando o aparelho tiver; no fone não há eco.
- **Segundo plano (D4 a, fase L):** `EscutaService` com `foregroundServiceType="microphone"` +
  `FOREGROUND_SERVICE_MICROPHONE`. No Android 14+ um FGS com microfone **não pode ser iniciado com o
  app em segundo plano** (permissão *while-in-use*); por isso o serviço é ligado num toque visível
  (ajuste ou tela A) e continua quando o app sai da tela. Reiniciar após *boot* não é permitido para
  `microphone` → depois de reiniciar o celular, a escuta volta quando o Pedro abrir o app. Para quando
  bateria < 20 % ou `PowerManager.isPowerSaveMode`. O indicador verde de microfone do Android fica
  aceso o tempo todo — esperado e explicado no ajuste.
- **Custo estimado (a medir no S1):** portão de energia corta o modelo no silêncio; com som, as três
  redes custam ≈ 2–5 ms por bloco de 80 ms num núcleo pequeno (≈ 3–6 % de um núcleo). Meta ≤ 3 %/h
  de bateria (critério 4). Não há número publicado para openWakeWord no Android; o S1 mede com
  `dumpsys batterystats` contra uma linha de base.

## 5. Bluetooth

- **Botão (D12 a):** `SessaoMidia` = `MediaSessionService` do Media3 com um `Player` próprio
  (`ForwardingPlayer` do ExoPlayer de respostas) e `MediaSession.Callback.onMediaButtonEvent`:
  `KEYCODE_HEADSETHOOK`/`MEDIA_PLAY_PAUSE` curto → `OUVINDO`; durante `FALANDO` → para a fala. O
  Android entrega o botão à **última sessão de mídia que tocou**; por isso a sessão fica ativa (e o
  FGS `mediaPlayback` com notificação "Condessa pronta") enquanto o app estiver aberto e por 10 min
  depois da última fala. Se o Pedro tocar música noutro app, o botão vai para lá — limitação aceita.
- **Segurar o botão:** fones mandam `ACTION_VOICE_COMMAND`; a `MainActivity` registra o filtro
  `android.intent.action.VOICE_COMMAND` e abre direto em `OUVINDO` (com a tela bloqueada usa
  `setShowWhenLocked`). O Android pergunta uma vez qual app usar.
- **Microfone e saída:** turno pelo fone usa o perfil de chamada (HFP/SCO, 16 kHz *wideband*
  quando houver) via `AudioManager.setCommunicationDevice` (API 31+; no 29–30 `startBluetoothSco`),
  e a resposta sai pelo mesmo fone. Depois do turno o app solta o dispositivo de comunicação
  (`clearCommunicationDevice`) para o fone voltar ao A2DP. Ajuste "saída de áudio": automático /
  sempre alto-falante.
- **Bip:** `ToneGenerator` curto no início e fim da escuta (como o satélite), pelo mesmo caminho.

## 6. Notificações (D5 a)

```
Evento (Ayanami) ─▶ push.enviar ─▶ assinatura tipo "unifiedpush" ─▶ POST endpoint ntfy (node 2,
tailnet) com corpo Web Push cifrado (RFC 8291, aes128gcm, VAPID) ─▶ app ntfy (distribuidor) ─▶
broadcast UnifiedPush ─▶ ReceptorPush (:app) decifra (chaves p256dh/auth do app) ─▶ Notification
```

- O app gera par P-256 + `auth` de 16 bytes (Keystore para a privada não exportável quando
  possível; senão cifrada pela chave do Keystore), registra no distribuidor (connector UnifiedPush),
  recebe o endpoint e chama `POST /v1/push/assinar` com `{"endpoint","keys":{"p256dh","auth"},
  "tipo":"unifiedpush"}` — o mesmo formato do `PushSubscription.toJSON()` que o `pywebpush` já usa;
  só muda a origem do endpoint. Payload igual ao §15 da Ayanami (≤ 3 KB).
- **Servidor ntfy no node 2**: contêiner `binwiederhier/ntfy` no Compose da Ayanami, só em
  `127.0.0.1` publicado pelo `tailscale serve` noutra porta; `auth-default-access: deny-all` + token
  de escrita só para a Ayanami; tópicos aleatórios por assinatura. Cabe na cota enxuta do node 2
  (≈ 20 MB RAM).
- **Consumo:** o app ntfy mantém uma conexão (WebSocket/JSON stream) — um só socket para todos os
  apps UnifiedPush; precisa ser liberado da otimização de bateria. Com o Tailscale sempre ligado o
  custo extra é pequeno, a medir no S3.
- **Recaídas:** sem distribuidor instalado → WorkManager a cada 30 min lê `GET /v1/feed` + confirmações
  pendentes (só avisos `tarefa`/`noticia`; `confirma` expira em 120 s e não cabe nisso) e o app avisa
  "instale o ntfy para avisos na hora". FCM (D5 b) fica fora: exige projeto Firebase, `google-services.json`
  (não pode ir ao repo público) e o Google vê os metadados. O UnifiedPush tem distribuidor FCM
  embutido — não usado.
- Canais: `confirma` (alta), `lembrete` (alta), `tarefa`, `monitor`, `noticia` (baixa), `operacao`,
  `escuta` (FGS, mínima), `midia` (FGS da sessão, mínima). Com o app visível o `ReceptorPush` não
  mostra notificação (o SSE já entregou; dedupe pelo `id` do evento).

## 7. Arte do retrato

- **Na Ayanami:** `PUT /v1/retrato` (token `pc`, escopo novo `retrato-enviar`) recebe um `.tar.zst`
  da pasta `~/.local/share/magi/condessa/` + `models/wakeword/{condessa,melspectrogram,embedding_model,
  silero_vad}.onnx`, enviado por `magi ayanami retrato enviar` (D11 a). A Ayanami guarda em
  `/opt/ayanami/dados/retrato/<versao>/` (fora do git, fora do backup público) e gera, num job da
  fila `lenta`, os pacotes **512 px e 768 px** em WebP com perda (q 90, alfa) — só os arquivos que o
  MVP usa (§7.1). `versao` = sha256 do tar.
- **Rotas:** `GET /v1/retrato/versao` → `{"versao","lados":[512,768],"pacotes":{"512":{"sha256",
  "bytes"},…}}`; `GET /v1/retrato/pacote?lado=768` → `application/zip` (com `ETag` = sha256, `Range`).
  Escopo novo `retrato` (padrão para `celular`; o PWA não usa).
- **No app:** `RetratoCache` baixa na 1ª abertura (com Wi-Fi ou confirmação no 4G), confere sha256,
  extrai em `filesDir/retrato/<versao>/` (interno, `noBackup`), apaga a versão antiga e checa a
  versão ao abrir (uma requisição pequena). Sem arte → R1.5.

### 7.1 Renderização no Compose

- Escolha do lado: 768 se a altura útil do retrato ≥ 1100 px, senão 512 (D10). Decodifica com
  `ImageDecoder` direto no tamanho (`setTargetSize`), `ARGB_8888`, para `ImageBitmap`.
- **Conjunto do MVP** (≈ 30 bitmaps): `parts` (≤ 14), olhos B1, B2, B3, B13, B14, B15, bocas C1, C2, C3,
  C7. Em 768², 2,25 MB cada → ≈ 68 MB; por isso **pré-composição** como o HUD: `back+back_tip`,
  `arm_l+arm_r+body` (já feito no `portrait.py`, "um drawPixmap em vez de três"), `lock_l+lock_r+bangs_c+clip`
  viram 3 bitmaps no carregamento → ≈ 20 bitmaps, ≈ 45 MB em 768 e ≈ 20 MB em 512 (RNF-C3). Olhos e
  bocas são recortados na *bounding box* não transparente (≈ 15 % da área) e desenhados com
  deslocamento → menos memória e menos *overdraw*.
- **Desenho:** um `Canvas` (ou `Modifier.drawWithCache`) com `drawImage` por camada, `translate` da
  respiração no grupo do busto/cabeça; leitura do relógio por `withFrameNanos` num `LaunchedEffect`
  que só invalida a fase de desenho (o estado é lido dentro do `draw`, sem recompor). HWUI desenha
  bitmaps na GPU; ~20 `drawImage` grandes por quadro estão bem dentro de 60 fps em aparelho médio.
  Taxa: 60 fps falando/piscando, 30 parada, 8 dormindo (pula quadros quando o `Quadro` não muda,
  como o `_key` do HUD). Fundo (gradiente + brilho rosa) num bitmap estático.
- **Fase L:** pivôs de cauda/cabeça (`TAIL_PIVOTS`, `HEAD_PIVOT`, `NECK_PIVOT`) com `rotate`, olhar com
  deslocamento de íris, reações; malhas (`deform`) só se o S4 mostrar folga (via `drawVertices` ou
  `RuntimeShader` API 33+).

## 8. Atualização automática (D8 a)

```
tag android-vX.Y.Z ─▶ GitHub Actions: gradle :app:assembleRelease (keystore de secret)
   ─▶ apksigner verify --print-certs ─▶ sha256sum ─▶ versao.json
   ─▶ scp (mesma chave/host do deploy da Ayanami) ─▶ /opt/ayanami/dados/app/{condessa-<vc>.apk,versao.json}
app: WorkManager 6 h / ao abrir ─▶ GET /v1/app/versao ─▶ versionCode > atual?
   ─▶ GET /v1/app/apk (Range, retoma) ─▶ cacheDir ─▶ sha256 confere?
   ─▶ getPackageArchiveInfo(GET_SIGNING_CERTIFICATES): mesmo certificado e mesmo pacote?
   ─▶ espera DORMINDO ─▶ PackageInstaller.Session (MODE_FULL_INSTALL)
       API 31+: setRequireUserAction(USER_ACTION_NOT_REQUIRED); API 34+: setRequestUpdateOwnership(true)
   ─▶ STATUS_PENDING_USER_ACTION → notificação "toque para atualizar" → Intent de confirmação
```

- `versao.json`: `{"versionCode":12,"versionName":"0.3.0","sha256":"…","bytes":n,"minimo":10,
  "notas":"…","publicado":"…Z","cert_sha256":"…"}`. A Ayanami só lê e serve (rotas na §9).
- Instalação silenciosa só vale quando o próprio app é o "instalador de registro"; a 1ª instalação
  vem do navegador, então a 1ª atualização pede um toque, e as seguintes podem ser silenciosas (com
  `setRequestUpdateOwnership` no 14+). Em qualquer caso o Android recusa um APK com assinatura
  diferente — a checagem própria é defesa extra (e evita baixar/instalar lixo).
- `versionCode` = número da execução do CI (monotônico); `versionName` da tag. O CI falha se o
  `versionCode` não for maior que o publicado.
- Perda do keystore = reinstalar e parear de novo: cópia de segurança fora do repo (precisa do Pedro).

## 9. Mudanças na Ayanami (todas aditivas, RNF-C7)

| Rota / mudança | Escopo | Detalhe |
| --- | --- | --- |
| `GET /v1/app/versao` | `conversa` | `200` `versao.json`; `404` se nada publicado |
| `GET /v1/app/apk` | `conversa` | `200`/`206` `application/vnd.android.package-archive`, `ETag`, `Range` |
| `GET /v1/retrato/versao` | `retrato` (novo, padrão do `celular`) | §7 |
| `GET /v1/retrato/pacote?lado=512\|768` | `retrato` | `application/zip`; `409` se o pacote ainda está sendo gerado |
| `PUT /v1/retrato` | `retrato-enviar` (novo, só `pc`) | `.tar.zst`, `X-Sha256`; ≤ 200 MB em streaming; job gera os pacotes |
| `POST /v1/turno` aceita `audio/ogg;codecs=opus` | `conversa` | D7 a; mesma regra de 1 MiB/15 s; o STT já decodifica por `ffmpeg` |
| SSE `turno.ouvido` `{"turno","texto"}` | `conversa` | D9 a; transcrição da fala do Pedro (PC e nuvem) |
| `POST /v1/push/assinar` aceita `"tipo":"unifiedpush"` | `conversa` | guarda o tipo; `push.enviar` igual (Web Push); 404/410 apaga |
| Serviço `ntfy` no Compose | — | §6; token de escrita no `.env` |
| `/saude` | — | ganha `app.versao` (versionCode publicado) e `retrato.versao` (sem segredo) |

Auditoria: `PUT /v1/retrato` e download do APK gravam `auditoria` (dispositivo, bytes). Rate limit
geral (60/min) não conta `/v1/app/apk` nem `/v1/retrato/pacote` (1 por hora por dispositivo).

## 10. CI do APK

- Workflow `.github/workflows/android.yml`: dispara em tag `android-v*` e em PR que toca `android/`
  (só build + testes JVM, sem assinar). JDK 21 (Temurin), `gradle/actions/setup-gradle`, cache.
- Passos: `./gradlew :retrato:test :voz:test :rede:test :app:testDebugUnitTest lint` → na tag,
  decodifica `ANDROID_KEYSTORE_B64` para arquivo temporário, `assembleRelease`, `apksigner verify`,
  confere tamanho ≤ 25 MB, gera `versao.json`, `scp` + `ssh mv` atômico (reaproveita o host/usuário/
  chave do deploy da Ayanami; mesma pendência de *fingerprint* do host das Sobras Y0.7).
- Nada de APK como artefato público do Actions (repo público; D8 a); logs sem caminho do tailnet.
- `splits.abi` só `arm64-v8a`; `isMinifyEnabled = true` com regras para onnxruntime e kotlinx.serialization.

## 11. Medição (critérios de sucesso)

- Latência: o app grava no log local (anel de 200 linhas, sem texto) `t_soltar`, `t_202`,
  `t_turno_texto`, `t_1o_audio`; tela oculta "Diagnóstico" (7 toques na versão) mostra p50/p90.
- fps: `JankStats` em debug e um Macrobenchmark `FrameTimingMetric` com a tela A falando um áudio
  fixo de 30 s.
- Bateria: `adb shell dumpsys batterystats --reset` → 2 h tela desligada → `dumpsys batterystats
  <pacote>`; três cenários (sem escuta, FGS de mídia, FGS de microfone).

## 12. Riscos e spikes

| Id | Pergunta | Saída | Risco se falhar |
| --- | --- | --- | --- |
| **S0** | Esqueleto: `android/` compila no CI com as versões fixadas; APK vazio ≤ 8 MB; instala por `PackageInstaller` a partir da Ayanami no celular do Pedro (1º toque + 2ª silenciosa?) | `libs.versions.toml`, nota com minSdk final (D2) | Update manual |
| **S1** | `condessa.onnx` no onnxruntime-android: mesma nota que no PC para 10 gravações (± 0,02); ms por bloco; %/h com FGS microfone | tabela + decisão do limiar no celular | Porcupine (D3 b) ou só BT/botão |
| **S2** | Botão do fone com app em segundo plano/tela bloqueada no fone do Pedro: `MediaSession` x `VOICE_COMMAND`; SCO 16 kHz chega limpo ao STT? | qual caminho funciona | D12 b ou só app aberto |
| **S3** | ntfy no node 2 + UnifiedPush: entrega com tela desligada/Doze em ≤ 30 s; consumo do app ntfy | nota + número | Recaída WorkManager; reconsiderar FCM |
| **S4** | Retrato em 768/512 no Compose: fps falando e memória no celular do Pedro | números; lado padrão | Cair para 512 ou menos camadas |
| **S5** | Latência ponta a ponta no 4G modo PC/nuvem com Ogg Opus 24 kb/s | p50/p90 | Pré-aquecer conexão; mandar áudio em blocos |

Outros riscos: fabricantes (Xiaomi/Samsung) matam FGS e o app ntfy — instruções de "não otimizar
bateria" no 1º uso; Android 14+ endurece instalação lateral (*restricted settings*) — o S0 prova o
fluxo; arte vazar por backup do Android — `allowBackup=false` e pasta `noBackupFilesDir`; o PWA e o
app ao mesmo tempo dão dois dispositivos `celular` (pushes duplicados) — o app sugere "sair" do PWA.

## Fontes (versões, 2026-10-21)

- Compose BOM 2026.09.00 — https://developer.android.com/develop/ui/compose/bom/bom-mapping
- Media3 1.11.1 (10/09/2026) — https://developer.android.com/jetpack/androidx/releases/media3
- Kotlin 2.3.20 — https://blog.jetbrains.com/kotlin/2026/03/kotlin-2-3-20-released/
- AGP 9.0.1 (Kotlin embutido, Gradle ≥ 9.1) — https://developer.android.com/build/releases/agp-9-0-0-release-notes
- Target API 36 na Play desde 31/08/2026 — https://developer.android.com/google/play/requirements/target-sdk
- onnxruntime-android 1.27.0 — https://central.sonatype.com/artifact/com.microsoft.onnxruntime/onnxruntime-android
- FGS `microphone` e restrição *while-in-use* — https://developer.android.com/develop/background-work/services/fg-service-types
- openwakeword-android-kt — https://github.com/Re-MENTIA/openwakeword-android-kt
- UnifiedPush (distribuidor, ntfy, FCM embutido) — https://unifiedpush.org/kdoc/
