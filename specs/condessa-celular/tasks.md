# Tarefas — Condessa no celular (app Android nativo)

Implementa [requirements.md](requirements.md), [design.md](design.md) e [spec.md](spec.md). Cada tarefa é
feita por **um agente** com janela de **até 128k tokens** (teto duro), salvo as marcadas **precisa do
Pedro**. O orquestrador (Pedro ou a sessão principal) só lança uma tarefa quando todas as de *Depende de*
estão no `main`. Fases: **M** = mudanças na Ayanami e no PC (Python), **A** = app Android (`android/`),
**F** = precisa do Pedro (celular, keystore, arte, node 2).

**Ondas** (cada onda roda junta; a seguinte começa quando a anterior está no `main`):
**1** A0.1, M1.1, M1.2, M1.5, M1.6, M1.7 · **2** A0.2, M1.3, M1.4 · **3** A0.3, A1.1, A2.1, A3.1 ·
**4** A1.2, A2.2, A3.2, A5.1, A6.1 · **5** A3.3, A4.1 · **6** A4.2 · **7** A4.3, A4.4 ·
**8** F.1 *Pedro*, F.2 *Pedro*, F.3 *Pedro* · **9** F.4 *Pedro* → F.5.

**Decisões:** valem os padrões D1a–D12a do requirements e as DSC1–DSC10 da spec. Versões marcadas
**(S0)** na spec §1 são fixadas pela A0.2, que corrige a tabela da spec no mesmo commit. Desde
2026-10-28 o node 2 inteiro é da Ayanami (o ntfy não precisa caber no perfil enxuto).

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*): spec por `spec §`, design por `design §`, requisitos por
   `R`/`RNF-C`/`D`. Leia a spec por trecho (`grep -n "^## \|^### " specs/condessa-celular/spec.md`).
   Siga também `specs/DECISOES-2026-10-10.md` e as regras da rodada em `.git/regras-rodada.txt`.
2. **Orçamento planejado ≤ 50–60k tokens**; teto duro 128k. Perto de **90k**: pare, faça commit do que
   está verde e anote o resto em *Sobras*.
3. **Contratos primeiro:** as interfaces da spec §2 nascem como stubs na A0.2 (docstring/KDoc
   "dono: <ID>"); as tarefas seguintes preenchem sem mudar assinatura (mudou? atualize a spec §2 no
   mesmo commit e anote em *Sobras*). Não leia o código de outras tarefas além das assinaturas.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*. O
   `AndroidManifest.xml` do `:app` e o `libs.versions.toml` são da A0.2: dependência ou componente
   faltando → anote em *Sobras* (a A0.2 já declara tudo o que a spec lista).
5. **Arquivos grandes por trecho** (`grep -n` + `sed -n`): `hud/wired/portrait.py`, `magi/core/turn.py`,
   `magi/common/contracts.py`, `ayanami/turnos.py`, `ayanami/push.py`, `specs/ayanami-central/spec.md`.
6. **Testes curtos.** Python: `uv run pytest -q -x tests/<área>` (confira o código de saída) e `uv run
   ruff check <seus arquivos>`. Android: `cd android && ./gradlew --offline -q :<módulo>:test` (ou
   `:app:testDebugUnitTest`) só dos módulos tocados. Relógio, `rng`, rede e microfone **sempre
   injetados**; nada de `sleep`/`Thread.sleep` real acima de 50 ms.
7. **Nada ao vivo nos testes:** sem celular, emulador, rede real, TV, LLM pago nem modelo ONNX real
   (detector falso; o ORT só é exercitado no F.3). Ayanami falsa = `AyanamiFalsa` (`MockWebServer`,
   spec §13); Python com ASGI em memória e, marcado `pg`, só o `ayanami-pg-teste`
   (`deploy/ayanami/pg-teste.sh`), nunca o `magi-pg` (54329).
8. **Proibições** (código, script, teste e comando do agente):
   - **repo público**: nenhum segredo, token `ayn_…`, keystore, senha, IP, nome do tailnet, arte do
     retrato, `.onnx` do Pedro nem APK em commit, log, teste ou *Sobras*; exemplos com
     `ayanami.exemplo.ts.net` e chaves falsas fixas;
   - **nada no node 1** (MultiVideos, wedding, gold-crm) e nada no Minecraft parado do node 2
     (`/opt/minecraft`);
   - **nada de `ssh`, `scp`, `adb install`, deploy real** no node 2 ou no celular por agente: a infra é
     código; aplica o Pedro nas tarefas F;
   - **sem `uv sync`/`uv lock`** (faltou pacote: `uv sync --extra ayanami --extra ayanami-ml` e avise);
     o `magi-core` está em produção: não reinicie nada;
   - **arquivos do HUD/tray do Pedro intocados** (`hud/alternar.py`, `hud/gamerhud-watch.py`,
     `hud/install.sh`, `hud/steam-mangohud.sh`, `hud/magi_tray.py`, `hud/system/autostart/*`,
     `tests/hud/*`) e `ayanami/workers/backup.py`, `tests/ayanami/test_backup_jobs.py` (mudança local
     do Pedro); `hud/wired/portrait.py` só leitura;
   - nada de `qdbus`/`gdbus`/`dbus-send` para KGlobalAccel/KWin; nada de `docker compose down`,
     `DROP`, `TRUNCATE`; nada de `git stash`, worktree, `--amend`, `rebase`, `push`.
9. **Toolchain Android no usuário**: SDK em `~/Android/Sdk` (já existe: `platforms/android-36.1`,
   `build-tools/36.1.0`, `37.0.0`; **sem** `cmdline-tools`); JDK 21 em `/usr/lib/jvm/java-21-openjdk`
   (o padrão do sistema é o 25). Nada com `sudo`, nada em `/opt` ou `/usr`. `android/local.properties`
   nunca vai a commit. Rodar o Gradle com `JAVA_HOME=/usr/lib/jvm/java-21-openjdk`.
10. **Uma tarefa = um commit** no `main`, mensagem com o ID (`A2.1: animador do retrato`) e a linha
    final `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, sempre `git commit -m … --
    <seus caminhos>` (nunca `git commit` puro; no `tasks.md` só os seus hunks com `git add -p`).
11. **RNF-C7:** o PWA não muda; `node --test 'tests/ayanami/pwa/*.mjs'` e `tests/ayanami` seguem verdes.

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~6k,
`design.md` ~8k, `spec.md` ~14k (por §: §1 ~1,5k, §2 ~2k, §3 ~2,5k, §4 ~2k, §5 ~2k, §6–§8 ~2k, §9 ~2,5k,
§10–§13 ~2k).

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
M1.1 escopos+/v1/app ─┬─ M1.3 retrato (rotas+job) ── M1.4 magi-retrato (PC) ─┐
                      │                                                      ├─ F.3 arte + S1/S2/S4 (Pedro)
M1.2 ogg + turno.ouvido ───────────────────────────────────────────────────┐ │
M1.5 push unifiedpush ─┬──────────────────────────────── F.2 ntfy + S3 (Pedro)│
M1.6 ntfy compose ─────┘                                       ▲            │ │
M1.7 ci-deploy "app" ──┐                                       │            │ │
A0.1 toolchain ── A0.2 esqueleto ─┬─ A0.3 CI android (+M1.7) ──┼── F.1 1ª instalação/keystore/S0 (Pedro)
                                  ├─ A1.1 rede/api ─┬─ A1.2 SSE+conectividade ─┐  │
                                  │                 ├─ A2.2 cache+pintor ◀─ A2.1 animador
                                  │                 ├─ A5.1 atualizador ─────────── F.1
                                  │                 └─ A6.1 push ──────────────── F.2
                                  ├─ A3.1 voz lógica ── A3.2 voz Android ─┬─ A3.3 BT
                                  │                                       │
                                  └─ A4.1 máquina+orquestrador (+A1.2, A3.2) ── A4.2 tela A (+A2.2)
                                                       A4.2 ─┬─ A4.3 gaveta/TV ─┐
                                                             └─ A4.4 ajustes/parear ─ F.1
                                           tudo + F.1–F.3 ── F.4 validação (Pedro) ── F.5 docs
```

## Fase M — Ayanami e PC (Python)

- [x] **M1.1 Escopos, rotas `/v1/app/*` e `/saude`** — `auth.py`: `ESCOPOS_PADRAO` (`retrato` no
  celular, `retrato-enviar` no pc) e as 6 linhas novas do `ESCOPO_DE_ROTA` (spec §9.1, DSC4);
  `app.py`: `"app_android"` e `"retrato"` em `ROTEADORES` (só a tupla); `ayanami/api/app_android.py`
  (§9.2: `versao.json` validado, APK com `Range`/`If-Range`/`ETag`/`416`, limite 6/h fora do 60/min);
  `ayanami/api/retrato.py` como stub com `router` vazio ("dono: M1.3"); `[app] dir` em `config.py` e
  no `ayanami.example.toml`; `/saude` com `app.versao` e `retrato.versao` (lê `/dados/app/versao.json`
  e `/dados/retrato/atual`).
  - Lê: spec §7 (formato `versao.json`), §9.1, §9.2, §9.3 (só a linha do `/saude`); `ayanami/api/auth.py` (linhas 37–95, 265–295), `ayanami/api/app.py` (`ROTEADORES`), `ayanami/api/limites.py` (assinaturas), `ayanami/api/saude.py`, `ayanami/api/backup.py` (padrão de arquivo grande), `ayanami/config.py` (`grep -n "push\|class "`)
  - Escreve: `ayanami/api/auth.py` (só `ESCOPOS_PADRAO`/`ESCOPO_DE_ROTA`), `ayanami/api/app.py` (só `ROTEADORES`), `ayanami/api/app_android.py`, `ayanami/api/retrato.py` (stub), `ayanami/api/limites.py` (só a isenção/limite por hora), `ayanami/api/saude.py`, `ayanami/config.py` (só `[app]`), `deploy/ayanami/ayanami.example.toml` (só `[app]`), `tests/ayanami/api/test_app_android.py`, `tests/ayanami/api/test_auth.py` (só as linhas novas, se a tabela for enumerada lá)
  - Depende de: —
  - Orçamento: ~50k
  - Pronto: CA-M27 (parte de escopos), CA-M28 e CA-Y9 verdes; `tests/ayanami` verde.
  - Paralelo: M1.2, M1.5, M1.6, M1.7, A0.1 (cuidado: Y6.5b mexe no lifespan do `app.py`; aqui só a tupla)

- [x] **M1.2 Turno com Ogg Opus e SSE `turno.ouvido`** — spec §9.4 e §9.5 (DSC5): `MIME_AUDIO` aceita
  `audio/ogg`; `Conversor.audio_para_pcm` com alias `webm_para_pcm`; `TurnoFim.ouvido` no elo e no
  `schema.py`; a ponte do PC preenche `ouvido`; `turnos.py` publica `turno.ouvido` (nuvem/long-poll
  após o STT; PC antes do `turno.texto`). Fixture `tests/ayanami/fixtures/turno.ogg` (≤ 4 KB, seno
  gerado por `ffmpeg` uma vez; o teste não chama `ffmpeg`).
  - Lê: spec §5.3 (tabela SSE), §9.4, §9.5; Ayanami spec §1.2 (só `TurnoFim`) por trecho; `ayanami/api/turno.py`; `ayanami/turnos.py` (linhas 50–120, 290–460); `magi/elo/mensagens.py` (`TurnoFim`), `magi/elo/schema.py` (`grep -n turno_fim`), `magi/elo/ponte.py` (linhas 40–190)
  - Escreve: `ayanami/api/turno.py`, `ayanami/turnos.py` (só conversor, `_fechar`/STT e publicação), `magi/elo/mensagens.py` (só `TurnoFim.ouvido`), `magi/elo/schema.py` (só o campo), `magi/elo/ponte.py` (só `ouvido`), `tests/ayanami/test_turno_ogg.py`, `tests/ayanami/fixtures/turno.ogg`, `tests/elo/test_ponte.py` (só o caso `ouvido`)
  - Depende de: —
  - Orçamento: ~55k
  - Pronto: CA-M32, CA-M33 verdes; `tests/elo`, `tests/ayanami` e `node --test 'tests/ayanami/pwa/*.mjs'` verdes. O `magi-core` só pega a mudança da ponte quando o Pedro reiniciar (anotar na mensagem do commit).
  - Paralelo: M1.1, M1.5, M1.6, M1.7, A0.1

- [ ] **M1.3 Retrato na Ayanami** — `PUT /v1/retrato`, `GET /v1/retrato/{versao,pacote,modelos}` (spec
  §9.3) no `ayanami/api/retrato.py`; `ayanami/retrato.py` (`ORDEM_PINTURA`, validação do tar com filtro
  `data`, geração 512/768 WebP + manifesto §4.1, `modelos.zip`, ponteiro `atual`, mantém 2 versões);
  job `retrato.gerar` (fila `lenta`, lock `retrato`) em `ayanami/workers/retrato.py` + uma linha `Def`
  em `ayanami/fila.py`; auditoria; evento `operacao` na falha. Confere WebP no Pillow (sem `uv sync`).
  - Lê: spec §4.1, §9.3; design §7, §7.1; `ayanami/api/backup.py` (upload em streaming e sha256), `ayanami/fila.py` (linhas 100–160), `ayanami/workers/` (um worker pequeno como modelo), `hud/wired/portrait.py` (`grep -n "PARTS_ORDER\|_tip\|lock_\|bangs\|clip"`)
  - Escreve: `ayanami/retrato.py`, `ayanami/api/retrato.py`, `ayanami/workers/retrato.py`, `ayanami/fila.py` (só a linha `Def`), `tests/ayanami/test_retrato.py`, `tests/ayanami/api/test_retrato_api.py`
  - Depende de: M1.1 (escopos, stub da rota)
  - Orçamento: ~60k
  - Pronto: CA-M27 (parte retrato), CA-M29, CA-M30, CA-M31 verdes (arte sintética gerada no teste; nunca a do Pedro).
  - Paralelo: A0.2, M1.4

- [ ] **M1.4 `magi-retrato` no PC** — spec §12 (DSC8): `magi/elo/retrato.py` (`enviar`, `estado`;
  tar só com caminhos permitidos; `zstd`; `PUT` com `X-Sha256`; credenciais do `magi-backup`) e a linha
  `magi-retrato` no `[project.scripts]`.
  - Lê: spec §12; `magi/elo/backup.py` (cliente HTTP, credenciais, `dormir`; por trecho), `magi/satellite/wake.py` (`grep -n "wake_\|WakeSettings"`)
  - Escreve: `magi/elo/retrato.py`, `pyproject.toml` (só a linha do script), `tests/elo/test_retrato_cli.py`
  - Depende de: M1.1 (contrato da rota; o teste usa servidor falso)
  - Orçamento: ~35k
  - Pronto: CA-M38 verde; `uv run magi-retrato --help` funciona (sem `uv sync`: `uv run python -m magi.elo.retrato --help` se o script ainda não estiver instalado).
  - Paralelo: A0.2, M1.3

- [x] **M1.5 Push `unifiedpush` no servidor** — spec §9.6: migração `003_push_tipo.sql`;
  `Assinar.tipo` com checagem de `[push] ntfy_hosts` (`422 endpoint_proibido`); `Assinatura.tipo` e TTL
  mínimo 60 s no envio; `ntfy_hosts` em `config.py` e no exemplo.
  - Lê: spec §6 (só o corpo do `assinar`), §9.6; `ayanami/api/push.py`; `ayanami/push.py` (linhas 270–360, 560–600); `ayanami/migrations/001_base.sql` (`push_assinaturas`); `ayanami/migrar.py` (assinaturas)
  - Escreve: `ayanami/migrations/003_push_tipo.sql`, `ayanami/api/push.py`, `ayanami/push.py` (só `Assinatura`, leitura e TTL), `ayanami/config.py` (só `[push] ntfy_hosts`), `deploy/ayanami/ayanami.example.toml` (só `ntfy_hosts`), `tests/ayanami/test_push_unifiedpush.py`
  - Depende de: —
  - Orçamento: ~45k
  - Pronto: CA-M34 verde (`pg`); `tests/ayanami/test_push.py` e `tests/ayanami/api/test_push_api.py` verdes sem mudar asserção.
  - Paralelo: M1.1 (os dois tocam `config.py` e o exemplo em seções diferentes: commit com `git add -p`), M1.2, M1.6, M1.7, A0.1

- [x] **M1.6 ntfy no Compose** — spec §10 (DSC6): serviço `ntfy` no `compose.yml`, `deploy/ayanami/ntfy/
  server.yml` (placeholder, sem host real), porta 8443 no `tailscale.sh`, `NTFY_BASE_URL` no
  `env.example`, seção "ntfy" no fim do runbook (ACL `up*`, usuário `celular`, liberar o app ntfy da
  otimização de bateria).
  - Lê: spec §10; `deploy/ayanami/compose.yml` (cabeçalho e um serviço), `deploy/ayanami/compose.node2.yml` (cabeçalho), `deploy/ayanami/host/tailscale.sh`, `tests/deploy/` (`grep -ln compose`), `docs/ayanami/runbook.md` (`grep -n "^#"`)
  - Escreve: `deploy/ayanami/compose.yml` (só o serviço `ntfy` e os volumes), `deploy/ayanami/ntfy/server.yml`, `deploy/ayanami/host/tailscale.sh` (só a linha 8443), `deploy/ayanami/env.example` (só `NTFY_BASE_URL`), `docs/ayanami/runbook.md` (só a seção nova, no fim), `tests/deploy/test_compose_ntfy.py`
  - Depende de: —
  - Orçamento: ~30k
  - Pronto: CA-M35 e o teste estático do compose existente (CA-Y29) verdes.
  - Paralelo: M1.1, M1.2, M1.5, M1.7, A0.1

- [x] **M1.7 Verbo `app` no `ci-deploy.sh`** — spec §11 (DSC7): `app <vc> <sha> <b64url>` com APK no
  stdin, validação em python3, `mv` atômico, 3 APKs, `flock` próprio; `deploy`/`saude` intactos.
  - Lê: spec §7 (`versao.json`), §11 (último item); `deploy/ayanami/host/ci-deploy.sh`; `tests/deploy/` (`grep -ln ci-deploy`)
  - Escreve: `deploy/ayanami/host/ci-deploy.sh`, `tests/deploy/test_ci_deploy_app.py`
  - Depende de: —
  - Orçamento: ~35k
  - Pronto: CA-M36 verde; testes existentes do `ci-deploy.sh` verdes.
  - Paralelo: M1.1, M1.2, M1.5, M1.6, A0.1

## Fase A — App Android (`android/`)

- [x] **A0.1 Toolchain no usuário** — confere JDK 21 (`/usr/lib/jvm/java-21-openjdk`) e o SDK em
  `~/Android/Sdk`; baixa as *command-line tools* do site oficial para `~/Android/Sdk/cmdline-tools/latest`
  (sem `sudo`; confere o sha256 publicado), `sdkmanager --licenses` (só se já aceitas pelo Android
  Studio; senão anota para o Pedro) e instala `platforms;android-36` e `build-tools;36.0.0` se o AGP
  pedir; documenta variáveis (`ANDROID_HOME`, `JAVA_HOME`) e comandos; `.gitignore` com
  `android/local.properties`, `android/**/build/`, `android/.gradle/`, `*.jks`, `*.keystore`, `*.apk`.
  - Lê: spec §1 (cabeçalho, DSC2), regra 9
  - Escreve: `docs/android/toolchain.md`, `.gitignore` (só as linhas Android)
  - Depende de: —
  - Orçamento: ~20k
  - Pronto: `~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager --list_installed` mostra plataforma 36 e build-tools; nada fora de `~`; doc com os comandos que rodaram.
  - Paralelo: M1.x

- [ ] **A0.2 Esqueleto Gradle e versões (S0 no PC)** — projeto `android/` da spec §1 com os 4
  módulos, wrapper, `libs.versions.toml` com as versões **(S0)** conferidas no Maven (grava a exata e
  corrige a tabela da spec §1), `AndroidManifest.xml` completo (permissões R10.5, `allowBackup=false`,
  `dataExtractionRules`, `network_security_config`, `VOICE_COMMAND`, serviços `SessaoMidia`/`ReceptorPush`/
  `EscutaService` (L, desabilitado), `FileProvider` não), fontes OFL + licenças, ícone próprio
  geométrico, `App`/`Grafo`/`MainActivity` mínimos, **stubs de todas as interfaces e tipos da spec §2**
  ("dono: <ID>"), signingConfig por env, `splits.abi`, R8 com regras.
  - Lê: spec §1, §2, §8.1 (cabeçalho); design §2, §10; requirements R10.5, RNF-C1–C2
  - Escreve: `android/**` exceto `src/main/kotlin/**/{logica,android}/*` de outros donos (aqui só stubs), `specs/condessa-celular/spec.md` (só a tabela de versões da §1)
  - Depende de: A0.1
  - Orçamento: ~60k
  - Pronto: CA-M1 e CA-M2 verdes; `./gradlew :app:assembleDebug` gera APK ≤ 8 MB (anota o tamanho).
  - Paralelo: M1.3, M1.4

- [ ] **A0.3 CI do APK** — `.github/workflows/android.yml` da spec §11 (testar em PR/main; publicar em
  tag com keystore de secret, `apksigner`, teto 25 MB, `versao.json`, envio pelo verbo `app`).
  - Lê: spec §11; `.github/workflows/ayanami.yml` (job `deploy`, linhas 100–140)
  - Escreve: `.github/workflows/android.yml`, `tests/deploy/test_android_workflow.py`
  - Depende de: A0.2, M1.7
  - Orçamento: ~30k
  - Pronto: CA-M37 verde; `actionlint` se instalado (senão anota).
  - Paralelo: A1.1, A2.1, A3.1

- [ ] **A1.1 Cliente da Ayanami** — `ApiAyanami` (OkHttp + kotlinx.serialization) implementando
  `ClienteAyanami`, `Modelos` (corpos da Ayanami §2.2 e spec §9), `ErroAyanami` com frases pt-BR,
  interceptor de host/HTTPS, `Cofre` (Keystore AES-GCM), `AyanamiFalsa` em `testFixtures`.
  - Lê: spec §2 (`ClienteAyanami`, `ErroAyanami`), §8.1, §9.2–§9.3 (corpos), §13; Ayanami spec §2.2 (tabela de rotas) por trecho
  - Escreve: `android/rede/src/main/**/{logica/Modelos.kt,android/ApiAyanami.kt,android/Cofre.kt}`, `android/rede/src/testFixtures/**`, `android/rede/src/test/**` (testes destes)
  - Depende de: A0.2
  - Orçamento: ~60k
  - Pronto: CA-M4, CA-M25, CA-M39 verdes.
  - Paralelo: A0.3, A2.1, A3.1

- [ ] **A1.2 SSE e conectividade** — `ParserSse`, `SseCliente` (`FonteEventos`, `Last-Event-ID`,
  1→30 s, vigia de `ping` 45 s), `Conectividade` (`classificar` puro + `NetworkCallback`, DNS do host,
  `/saude` 4 s, a cada 30 s com a tela visível).
  - Lê: spec §3.3, §5.3; requirements R9.1–R9.4
  - Escreve: `android/rede/src/main/**/{logica/ParserSse.kt,logica/Diagnostico.kt,android/SseCliente.kt,android/Conectividade.kt}`, testes deles
  - Depende de: A1.1
  - Orçamento: ~45k
  - Pronto: CA-M17 e CA-M7 (parte `classificar`) verdes.
  - Paralelo: A2.2, A3.2, A5.1, A6.1

- [ ] **A2.1 Animador do retrato (puro)** — `PortraitToml` (subconjunto: `[states]`, `[speech]`,
  `breath_*`, `blink`), `Manifesto`, `Animador` (spec §4.3) e `scripts/retrato_sequencia.py` (roda o
  `portrait.py` em modo puro com o LCG do `java.util.Random`) + fixture `tests/fixtures/retrato/sequencia.json`.
  - Lê: spec §4.1 (manifesto), §4.3; design §3, §7.1; `hud/wired/portrait.py` por trecho (`grep -n "def eye_frame\|def mouth\|def breath\|_eye_target\|BLINK\|MOUTH\|class PartsPortrait"`)
  - Escreve: `android/retrato/src/main/**/logica/*`, `android/retrato/src/test/**`, `scripts/retrato_sequencia.py`, `tests/fixtures/retrato/sequencia.json`
  - Depende de: A0.2
  - Orçamento: ~55k
  - Pronto: CA-M10, CA-M11, CA-M13 (parte `fpsAlvo`) verdes; o script não importa Qt (lê constantes com `ast` ou replica as funções puras e diz isso no cabeçalho).
  - Paralelo: A0.3, A1.1, A3.1

- [ ] **A2.2 Cache e pintura do retrato** — `RetratoCache` (spec §4.2: lado, `Range`, sha, zip seguro,
  troca e limpeza, 4G pergunta; mesmo fluxo para `modelos.zip`) e `Pintor` (Compose, `drawWithCache`,
  `withFrameNanos`, para fora de `STARTED`, placeholder rosa R1.5, fundo estático).
  - Lê: spec §4.1–§4.3, §2 (`RetratoFonte`); design §7.1
  - Escreve: `android/retrato/src/main/**/android/*`, testes deles
  - Depende de: A1.1, A2.1
  - Orçamento: ~55k
  - Pronto: CA-M12 e CA-M13 (parte invalidação) verdes.
  - Paralelo: A1.2, A3.2, A5.1, A6.1

- [ ] **A3.1 Voz: lógica pura** — `PortaoEnergia`, `WakeSpotter` (porta de `magi/satellite/wake.py`),
  `VadEnergia`, regras de gravação (400 ms, 15 s, 5 s, 800 ms), `OggOpusEscritor` (DSC10) e o teste
  Python cruzado `tests/ayanami/test_ogg_android.py` (lê `android/voz/src/test/resources/ogg/escrito.ogg`
  gerado pelo teste Kotlin; pula sem `ffprobe`).
  - Lê: spec §5.1, §5.2; `magi/satellite/wake.py` (linhas 30–200); `tests/satellite/` (`grep -ln WakeSpotter`, só os casos)
  - Escreve: `android/voz/src/main/**/logica/*`, `android/voz/src/test/**`, `tests/ayanami/test_ogg_android.py`
  - Depende de: A0.2
  - Orçamento: ~55k
  - Pronto: CA-M14, CA-M15, CA-M16 verdes.
  - Paralelo: A0.3, A1.1, A2.1

- [ ] **A3.2 Voz: Android** — `Gravador` (`AudioRecord`), `CodificadorOpus` (`MediaCodec` → escritor),
  `WakeWordOnnx` (ORT 1 thread, modelos do `modelos.zip`), `Tocador` (ExoPlayer + `OkHttpDataSource` +
  `AmplitudeProcessor` com atraso de saída), `Bip`, `PipelineVoz` real; microfone só nos 3 casos do R2.5.
  - Lê: spec §2 (`PipelineVoz`), §5.1–§5.3; design §3.1, §4
  - Escreve: `android/voz/src/main/**/android/{Gravador,CodificadorOpus,WakeWordOnnx,Tocador,AmplitudeProcessor,Bip,PipelineVozReal}.kt`, testes deles
  - Depende de: A3.1, A1.1 (cabeçalho de auth)
  - Orçamento: ~60k
  - Pronto: teste JVM do `AmplitudeProcessor` (RMS/normalização/atraso com PCM sintético) e CA-M19 (parte "microfone só nos 3 casos") verdes; `:voz:assembleRelease` com R8 sem aviso de classe do ORT.
  - Paralelo: A1.2, A2.2, A5.1, A6.1

- [ ] **A3.3 Bluetooth** — `SessaoMidia` (Media3, FGS `mediaPlayback`, 10 min), `onMediaButtonEvent`,
  `VOICE_COMMAND` na `MainActivity` (só o tratamento do `Intent`), `RotaAudio` (SCO/`setCommunicationDevice`,
  ajuste de saída).
  - Lê: spec §5.4; design §5
  - Escreve: `android/voz/src/main/**/android/{SessaoMidia,RotaAudio}.kt`, `android/app/src/main/**/MainActivity.kt` (só `AcaoInicial` do `Intent`), testes deles
  - Depende de: A3.2
  - Orçamento: ~45k
  - Pronto: CA-M19 verde.
  - Paralelo: A4.1

- [ ] **A4.1 Máquina da Condessa e orquestrador** — `MaquinaCondessa` (spec §2, regras), `Orquestrador`
  (liga `PipelineVoz`, `ClienteAyanami`, `FonteEventos` à máquina; dedupe por `id`; medições do design §11
  no anel de 200), histórico do dia não (A4.4).
  - Lê: spec §2, §5.3; design §3, §11
  - Escreve: `android/app/src/main/**/estado/*`, `android/app/src/test/**/estado/*`
  - Depende de: A1.2, A3.2
  - Orçamento: ~55k
  - Pronto: CA-M3 e CA-M18 verdes.
  - Paralelo: A3.3

- [ ] **A4.2 Tela A** — tema (§3.1), tela A (§3.2: retrato, topo, faixa, legenda, onda, pílulas, base,
  teclado), faixas da §3.3, `FilaTexto`, `NavHost` com as rotas da §3.4 (telas da gaveta como stubs
  "dono: A4.3/A4.4"), paisagem.
  - Lê: spec §3.1–§3.4; brief (tela A); requirements R1.4, R3.2–R3.4, R9
  - Escreve: `android/app/src/main/**/ui/{tema,telaa}/*`, `android/app/src/main/**/ui/Navegacao.kt`, `android/app/src/main/**/MainActivity.kt` (só `setContent`), testes deles
  - Depende de: A4.1, A2.2
  - Orçamento: ~60k
  - Pronto: CA-M5, CA-M6 e CA-M7 (parte fila) verdes.
  - Paralelo: —

- [ ] **A4.3 Gaveta, TV, notícias, tarefas, servidor, confirma** — §3.4 (gaveta e telas), R4, R5.2–R5.4,
  R3.5 (2 toques), `RotaDeUrl`, volume físico na TV.
  - Lê: spec §3.3 (linhas TV), §3.4; requirements R3.5, R4, R5.1–R5.4; Ayanami spec §2.2 (linhas casa/feed/tarefas/servidor)
  - Escreve: `android/app/src/main/**/ui/{gaveta,tv,noticias,tarefas,servidor,confirma}/*`, `android/app/src/main/**/ui/RotaDeUrl.kt`, testes deles
  - Depende de: A4.2
  - Orçamento: ~60k
  - Pronto: CA-M8 e CA-M9 verdes.
  - Paralelo: A4.4

- [ ] **A4.4 Ajustes, parear, histórico e diagnóstico** — R5.5 (tabela §8.2, sincroniza preferências),
  R6 (parear com endereço digitado, 401 → parear), R3.7 (histórico + `TrabalhoMeiaNoite`), tela
  Diagnóstico (7 toques), "baixar a arte de novo", "procurar atualização" (chama o `Atualizador`), "sair".
  - Lê: spec §3.4 (Parear, Diagnóstico), §8.2; requirements R3.7, R5.5, R6
  - Escreve: `android/app/src/main/**/ui/{ajustes,parear,diagnostico}/*`, `android/app/src/main/**/estado/Historico.kt`, testes deles
  - Depende de: A4.2, A5.1
  - Orçamento: ~55k
  - Pronto: CA-M26 verde; Compose UI do parear (código errado → frase; sucesso → token no `Cofre` falso).
  - Paralelo: A4.3

- [ ] **A5.1 Atualizador** — `VerificaApk` (puro), `Atualizador` (`:rede`), `Instalador` e `TrabalhoVersao`
  (`:app/update`), permissão de instalar, espera `DORMINDO`, bloqueio por `minimo`.
  - Lê: spec §2 (`Atualizador`, `VerificaApk`), §7; design §8
  - Escreve: `android/rede/src/main/**/{logica/VerificaApk.kt,android/Atualizador.kt}`, `android/app/src/main/**/update/*`, testes deles
  - Depende de: A1.1
  - Orçamento: ~50k
  - Pronto: CA-M23 e CA-M24 verdes.
  - Paralelo: A1.2, A2.2, A3.2, A6.1

- [ ] **A6.1 Notificações** — `ReceptorPush` (connector UnifiedPush), `DecifradorWebPush` (RFC 8291 com
  `javax.crypto`), `Canais`, `TrabalhoAvisos` (recaída sem distribuidor), `scripts/gerar_vetor_webpush.py`
  (chaves falsas fixas, `pywebpush` só local) + fixture.
  - Lê: spec §6; design §6; Ayanami spec §15 (payload) por trecho
  - Escreve: `android/app/src/main/**/push/*`, `android/app/src/test/**/push/*`, `android/app/src/test/resources/webpush/*`, `scripts/gerar_vetor_webpush.py`
  - Depende de: A1.1
  - Orçamento: ~55k
  - Pronto: CA-M20, CA-M21, CA-M22 verdes.
  - Paralelo: A1.2, A2.2, A3.2, A5.1

## Fase F — Precisa do Pedro

- [ ] **F.1 Keystore, 1ª instalação e S0 no celular (precisa do Pedro)** — Pedro: modelo/versão do
  Android (fecha D2), aprova e gera o keystore (`keytool -genkeypair -alias condessa -keyalg RSA
  -keysize 4096 -validity 10000`, guardado fora do repo com cópia de segurança), cria os 4 secrets
  `ANDROID_*`, aplica o `ci-deploy.sh` novo no node 2 (runbook), deploy da M1.1, tag `android-v0.1.0`,
  baixa o APK pelo navegador com o Tailscale, permite "instalar apps desconhecidos", pareia; tag
  `android-v0.1.1` → mede a 1ª atualização (um toque) e a 2ª (silenciosa?). O agente escreve a nota.
  - Lê: spec §7, §11, §14; `docs/android/toolchain.md`
  - Escreve: `docs/spikes/condessa-celular-s0.md`, `specs/condessa-celular/tasks.md` (marcar e *Sobras*)
  - Depende de: A0.3, A4.4, A5.1, M1.1, M1.7
  - Orçamento: ~20k do agente + Pedro
  - Pronto: CA-M40.
  - Paralelo: F.2, F.3

- [ ] **F.2 ntfy no node 2 e S3 (precisa do Pedro)** — deploy com o serviço `ntfy`, `tailscale serve`
  8443, ACL do runbook, `[push] ntfy_hosts` no `ayanami.toml` real, app ntfy no celular com o servidor
  próprio e usuário `celular`, otimização de bateria desligada para ntfy e Condessa; 10 pushes com a tela
  desligada; consumo em 2 h.
  - Lê: spec §6, §10; runbook seção "ntfy"
  - Escreve: `docs/spikes/condessa-celular-s3.md`, `specs/condessa-celular/tasks.md` (marcar)
  - Depende de: M1.5, M1.6, A6.1, F.1
  - Orçamento: ~15k do agente + Pedro
  - Pronto: CA-M42 (ou decisão do Pedro pela recaída).
  - Paralelo: F.3

- [ ] **F.3 Arte, voz e S1/S2/S4 no celular (precisa do Pedro)** — Pedro roda `magi-retrato enviar`
  (envia a arte e os `.onnx`); app baixa; mede wake word (10 gravações vs PC, ms/bloco, 20 "Condessa" a
  1 m), botão do fone (MediaSession × VOICE_COMMAND, SCO limpo), fps/memória da tela A em 768 e 512.
  - Lê: spec §4, §5, §14; design §12
  - Escreve: `docs/spikes/condessa-celular-s1-s2-s4.md`, `specs/condessa-celular/tasks.md` (marcar e *Sobras*)
  - Depende de: M1.2, M1.3, M1.4, A3.3, A4.2, F.1
  - Orçamento: ~20k do agente + Pedro
  - Pronto: CA-M41, CA-M43 (falhas viram tarefas novas no fim deste arquivo).
  - Paralelo: F.2

- [ ] **F.4 Validação e semana de uso (precisa do Pedro)** — critérios de sucesso 1–8 (latência S5 em
  Wi-Fi/4G e modo PC/nuvem, fps, boca filmada a 120 fps, bateria, wake word, tamanho do APK,
  atualização em ≤ 24 h, uma semana sem voltar ao PWA).
  - Lê: requirements *Critérios de sucesso*; design §11; notas S0–S4
  - Escreve: `docs/spikes/condessa-celular-validacao.md`, `specs/condessa-celular/tasks.md`
  - Depende de: F.1, F.2, F.3 e todas as M*/A*
  - Orçamento: ~25k do agente + uma semana do Pedro
  - Pronto: CA-M44.
  - Paralelo: —

- [ ] **F.5 Documentação** — `docs/GUIA.md` (instalar o app, parear, ntfy, Tailscale, "como parear a
  TV", atualizar), `README.md` (seção curta do app), `docs/PROXIMOS-PASSOS.md` (fase L: olhar, reações,
  wake word em segundo plano, widgets). Só o que a F.4 confirmou.
  - Lê: `README.md`, `docs/GUIA.md`, `docs/PROXIMOS-PASSOS.md` por trecho; notas das F.1–F.4
  - Escreve: `README.md`, `docs/GUIA.md`, `docs/PROXIMOS-PASSOS.md` (só as seções do app)
  - Depende de: F.4
  - Orçamento: ~30k
  - Pronto: os comandos citados existem (`magi-retrato --help`); links internos válidos.
  - Paralelo: —

---

## Cobertura dos critérios (CA-M1..M44)

| CA | Tarefa | CA | Tarefa |
| --- | --- | --- | --- |
| M1, M2 | A0.2 | M23, M24 | A5.1 |
| M3, M18 | A4.1 | M25, M4, M39 | A1.1 |
| M5, M6 | A4.2 | M26 | A4.4 |
| M7 | A1.2 (`classificar`) + A4.2 (fila) | M27 | M1.1 (+ M1.3 retrato) |
| M8, M9 | A4.3 | M28 | M1.1 |
| M10, M11 | A2.1 | M29–M31 | M1.3 |
| M12 | A2.2 | M32, M33 | M1.2 |
| M13 | A2.1 (`fpsAlvo`) + A2.2 (invalidação) | M34 | M1.5 |
| M14–M16 | A3.1 | M35 | M1.6 |
| M17 | A1.2 | M36 | M1.7 |
| M19 | A3.3 (+ A3.2 microfone) | M37 | A0.3 |
| M20–M22 | A6.1 | M38 | M1.4 |
| M40 | F.1 | M41, M43 | F.3 |
| M42 | F.2 | M44 | F.4 |

Critérios de sucesso 1–8 (ao vivo): F.3 (2, 3, 5), F.1 (6, 7), F.4 (todos).

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)

- **M1.2:** `ayanami/app/elo.schema.json` (fora do *Escreve*) regenerado com `python -m magi.elo.schema`
  por causa do campo `TurnoFim.ouvido` (o `test_schema_deterministico_e_igual_ao_arquivo` compara);
  `magi/elo/schema.py` não precisou mudar (gera dos dataclasses). O `magi-core` só preenche `ouvido`
  depois que o Pedro reiniciar.

- **M1.1**: `ayanami/api/retrato.py` nasce com as 4 rotas do `ESCOPO_DE_ROTA` como `rota_stub` (501,
  "dono: M1.3") e não com `router` vazio — o `test_rotas_da_app_batem_com_a_tabela` exige rota para
  cada linha. Fora do *Escreve*: `ayanami/api/auditoria.py` ganhou `"app"` e `"retrato"` em `TIPOS`
  (sem isso `registrar(tipo="app")` levanta). Para a M1.3: os downloads do retrato chamam
  `ctx.limites.por_download(request, disp, etag)` (o 60/min já os isenta) e podem usar
  `app_android.servir_arquivo` (ETag/Range/If-Range/416); `/saude` lê `<dados>/retrato/atual`
  (arquivo com a versão ou link para a pasta). No `tests/ayanami` completo, falhas só de trabalho em
  curso de outras tarefas (`test_turno_ogg` da M1.2; `NTFY_BASE_URL` no `env.example` vs `test_config`).

- **M1.6** (fora do *Escreve*, necessários para o "Pronto"): `compose.node2.yml` ganhou `ntfy`
  (cpuset 6,7, 0.25 CPU, 64m sem swap; soma do perfil 6592 MiB) para o perfil enxuto;
  `tests/deploy/test_ayanami_compose.py` (CA-Y29 com `ntfy`: porta, limites, sem `.env`, volumes) e
  `tests/deploy/test_ayanami_host.py` (serve 8443 e idempotência) ajustados. O `[push] ntfy_hosts` do
  exemplo é da M1.5; o runbook (§10, passo 1) manda pôr o host real no `ayanami.toml` do node 2.

- **A0.1** (Pedro): `/usr/lib/jvm/java-21-openjdk` está vazio (só `man/`; pacote do JDK 21 não
  instalado). Até reinstalar (`sudo dnf install java-21-openjdk-devel`, se o F44 tiver), o Gradle usa
  `JAVA_HOME=/opt/android-studio/jbr` (JBR 21.0.10); a regra 9 e a A0.2 devem ler esse caminho.
  Licenças: só `android-sdk-license` aceita; as outras 7 ficam para o Pedro (`sdkmanager --licenses`).
