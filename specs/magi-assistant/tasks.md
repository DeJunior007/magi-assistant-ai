# Tarefas — Magui (MVP)

Implementa [design.md](design.md) e [requirements.md](requirements.md). Cada tarefa é feita por
**uma sessão de agente** com janela de até 128k tokens.

## Regras para o agente

1. **Leia só o pacote de contexto da tarefa** (campo *Lê*). Seções do design são citadas por `§`,
   requisitos por `R`. Não leia `docs/PRD.md`: os requisitos já cobrem o que importa.
2. **Orçamento planejado ≤ 60k tokens** por tarefa (leitura + código escrito + saída de testes).
   O resto da janela de 128k é margem para erros e correções.
3. **Contratos primeiro:** módulos de outras tarefas são usados pelo que está em
   `magi/common/contracts.py` (tarefa 1.0), sem ler o código deles.
4. **Arquivos grandes por trecho:** use `grep -n` e leitura por intervalo. Nunca leia
   `hud/gamerhud.py` inteiro (~20k tokens); as tarefas dizem quais funções abrir.
5. **Saída de testes curta:** `uv run pytest -q -x <arquivo>`; filtre logs longos com `tail`/`grep`.
6. **Se o pacote não bastar:** pare, anote no PR o que faltou e proponha dividir a tarefa.
   Não saia lendo o repositório.
7. **Uma tarefa = um commit (ou PR)**, com o ID da tarefa na mensagem.
8. **Não mexa na sessão ao vivo do usuário.** Testes usam D-Bus, PipeWire, KWin e KGlobalAccel
   falsos. Fora dos testes, só chamadas de **leitura**, ou de escrita já validadas nos spikes
   (`docs/spikes/S1.md`, `S2.md`). O KGlobalAccel roda dentro do KWin: um argumento D-Bus mal
   formado derruba a sessão inteira (aconteceu no S2). Valores do tipo `a(ai)` levam sempre 4 inteiros.
   Volume e mudo alterados precisam de arquivo de recuperação, porque o WirePlumber os guarda por app (S1).
9. **O Postgres de desenvolvimento (`magi-pg`, 127.0.0.1:54329) é compartilhado** por todos os agentes e pelo
   usuário. Nunca rode `docker compose down`, `docker rm` ou `DROP` fora de um schema temporário seu.

Estimativa usada: 1k tokens ≈ 3,5 KB de texto em português ou 4 KB de código.
Tamanho dos documentos: `design.md` ~5k · `requirements.md` ~5k · uma seção do design 0,3–1,5k.

Formato de cada tarefa:
**Lê** (pacote de contexto) · **Escreve** (arquivos) · **Depende de** · **Orçamento** · **Pronto** (critério verificável).

---

## Fase 0 — Base do projeto e spikes

- [x] **0.1 Projeto Python** — `uv` com Python 3.12, pacote `magi/`, `ruff`, `pytest`, CI no GitHub Actions.
  - Lê: §2, §11
  - Escreve: `pyproject.toml`, `magi/__init__.py`, `tests/test_smoke.py`, `.github/workflows/ci.yml`
  - Depende de: —
  - Orçamento: ~15k
  - Pronto: `uv run pytest` passa localmente e no CI.

- [x] **0.2 Config e segredos** — leitura do `config.toml` com recarga ao salvar; chaves no keyring; comando `magi-keys add <nome>`. *(R21.1, R21.4)*
  - Lê: §2, §4.7, R21
  - Escreve: `magi/common/config.py`, `magi/common/secrets.py`, `magi/cli/keys.py`, `config.example.toml`, `tests/common/test_config.py`
  - Depende de: 0.1
  - Orçamento: ~25k
  - Pronto: teste carrega o exemplo; nenhuma chave em arquivo.

- [x] **0.3 Banco** — Compose do `pgvector/pgvector:pg16` em `127.0.0.1` com memória limitada; migração com as tabelas do §7; executor de migrações. *(R11, RNF-02)*
  - Lê: §2 (linha do banco), §7
  - Escreve: `deploy/docker-compose.yml`, `magi/memory/migrations/001_init.sql`, `magi/memory/migrate.py`, `tests/memory/test_migrate.py`
  - Depende de: 0.1
  - Orçamento: ~25k
  - Pronto: `docker compose up -d` + migração criam o esquema; container ocioso < 80 MB.

- [x] **0.4 Spike S1: áudio no PipeWire** — captura com `sounddevice`; listar e mutar o `source-output` do Discord; baixar `sink-input`s com `pulsectl`.
  - Lê: §3.2, §5, §12
  - Escreve: `spikes/s1_audio.py`, `docs/spikes/S1.md` (resultado e decisão)
  - Depende de: 0.1
  - Orçamento: ~25k
  - Pronto: `docs/spikes/S1.md` diz o que funciona e o mecanismo escolhido.

- [x] **0.5 Spike S2: atalho** — testar `globalShortcutPressed/Released` do KGlobalAccel e o evdev do DualSense.
  - Lê: §3.3, §12
  - Escreve: `spikes/s2_ptt.py`, `docs/spikes/S2.md`
  - Depende de: 0.1
  - Orçamento: ~25k
  - Pronto: mecanismo de PTT decidido; se precisar do grupo `input`, documentado.

- [x] **0.6 Spike S3: modelos** — medir latência e custo de transcrição PT-BR, TTS feminina, agente e pesquisa; gerar amostras das vozes. **Precisa de mim** para ouvir e escolher a voz.
  - Lê: §4.7, §12, `config.example.toml`
  - Escreve: `spikes/s3_models.py`, `docs/spikes/S3.md`, seção `[tasks]` do `config.example.toml`
  - Depende de: 0.2
  - Orçamento: ~30k
  - Pronto: `[tasks]` preenchida com modelos e preços.

- [ ] **0.7 Spike S4: "Ei Magui"** — roteiro de gravação de ~50 amostras, treino do openWakeWord, medição de falsos disparos em 1 h de jogo. **Precisa de mim** para gravar e jogar.
  - Lê: §5, §12, `docs/spikes/S1.md`
  - Escreve: `spikes/s4_wake/` (roteiro, treino, medição), `docs/spikes/S4.md`, `magi/satellite/models/ei_magui.onnx`
  - Depende de: 0.4
  - Orçamento: ~35k
  - Pronto: modelo com ≤ 1 falso disparo/h (RNF-06).

## Fase 1 — Base de voz

- [x] **1.0 Contratos** — todas as interfaces entre módulos: eventos do protocolo (Wyoming + `magi-*`), estados do turno, `Transcript`, `Intent`/`Slot`, `ActionRequest`/`ActionResult`, protocolos de provedor e de repositório, mensagens do HUD. Serialização dos eventos com testes. *(R22.1)*
  - Lê: §3, §3.1, §4.1, §5, §6, §7
  - Escreve: `magi/common/contracts.py`, `magi/common/events.py`, `tests/common/test_events.py`
  - Depende de: 0.1
  - Orçamento: ~40k
  - Pronto: testes de ida e volta de todos os eventos e mensagens passam; docstring de cada contrato cita o requisito.

- [x] **1.1 Satélite: captura e wake word** — captura 16 kHz em blocos de 80 ms, openWakeWord por bloco, limiar recarregável, envio de `magi-wake`. *(R1.1, R1.2, R1.6)*
  - Lê: `contracts.py`, §5, `docs/spikes/S1.md`, `docs/spikes/S4.md`
  - Escreve: `magi/satellite/capture.py`, `magi/satellite/wake.py`, `magi/satellite/__main__.py`, testes com áudio gravado
  - Depende de: 1.0, 0.7
  - Orçamento: ~35k
  - Pronto: ativação em < 300 ms; CPU ociosa ≤ 2% de um núcleo (RNF-01).

- [x] **1.2 Satélite: VAD e envio** — Silero VAD, 700 ms de silêncio, máximo 15 s; `audio-start/chunk/stop` com metadados de tom (energia, taxa de fala). *(R1.5)*
  - Lê: `contracts.py`, §5, R1
  - Escreve: `magi/satellite/vad.py`, `magi/satellite/stream.py`, testes
  - Depende de: 1.1
  - Orçamento: ~30k
  - Pronto: frase falada chega inteira ao núcleo falso de teste.

- [x] **1.3 Satélite: atalho** — PTT pelo mecanismo do S2 (teclado; DualSense se viável). *(R1.3, R1.4, R1.7)*
  - Lê: `contracts.py`, §3.3, `docs/spikes/S2.md`
  - Escreve: `magi/satellite/ptt.py`, testes
  - Depende de: 1.2, 0.5
  - Orçamento: ~30k
  - Pronto: grava enquanto o atalho está pressionado.

- [x] **1.4 Núcleo: esqueleto e estados** — serviço asyncio, servidor Wyoming, máquina de estados do §3.1, interrupção por nova ativação, envio de `state` ao HUD (só o cliente, sem o HUD). *(R12.5)*
  - Lê: `contracts.py`, §3, §3.1
  - Escreve: `magi/core/service.py`, `magi/core/turn.py`, `magi/core/hud_client.py`, testes com satélite falso
  - Depende de: 1.0
  - Orçamento: ~40k
  - Pronto: teste percorre todos os estados, inclusive a interrupção.

- [x] **1.5 Transcrição** — provedor da config, vocabulário de dica (≤ 200 tokens), falha → "não peguei, repete?". *(R3.1, R3.2, R3.5, R3.6)*
  - Lê: `contracts.py`, §4.1 (linha `stt`), R3
  - Escreve: `magi/core/stt.py`, testes com provedor falso
  - Depende de: 1.4, 0.6
  - Orçamento: ~30k
  - Pronto: frase de teste transcrita; nenhum arquivo de áudio criado.

- [x] **1.6 Correções** — "não, eu falei X" salva o par e refaz o turno; correções aplicadas antes do roteador. *(R3.3, R3.4)*
  - Lê: `contracts.py`, §4.1 (linha `corrections`), §7 (tabela `corrections`), R3
  - Escreve: `magi/core/corrections.py`, `magi/memory/corrections_repo.py`, testes
  - Depende de: 1.4, 0.3
  - Orçamento: ~25k
  - Pronto: testes unitários e turno corrigido.

- [x] **1.7 Catálogo de jogos** — leitura dos `appmanifest_*.acf` de todas as bibliotecas da Steam; apelidos aprendidos; busca aproximada por nome.
  - Lê: `contracts.py`, §4.2, `hud/gamerhud.py` só a função `steam_game_name` (via `grep -n`)
  - Escreve: `magi/core/catalog.py`, testes com manifests de exemplo
  - Depende de: 1.0
  - Orçamento: ~25k
  - Pronto: "dedi cels" resolve para Dead Cells nos testes.

- [x] **1.8 Roteador local** — `intents.yaml`, normalização, `rapidfuzz`, slots pelo catálogo, faixa de dúvida "você quis dizer X?", conjunto inicial de frases de ouro. *(R4.1–R4.4)*
  - Lê: `contracts.py`, §4.2, §10 (linha de frases de ouro), R4
  - Escreve: `magi/core/router.py`, `magi/core/intents.yaml`, `tests/data/utterances.yaml`, `tests/core/test_router.py`
  - Depende de: 1.7
  - Orçamento: ~40k
  - Pronto: acerto ≥ 90% nas frases de ouro iniciais.

- [x] **1.9 Ações: jogos** — abrir por `steam://rungameid`, sugestões quando não achar, fechar com confirmação (SIGTERM; SIGKILL só com nova confirmação). *(R5.1–R5.5)*
  - Lê: `contracts.py`, §3.1 (estado `confirming`), R5, `hud/gamerhud-watch.py` só a função `steam_game`
  - Escreve: `magi/core/actions/games.py`, testes
  - Depende de: 1.4, 1.7
  - Orçamento: ~35k
  - Pronto: "abre o dedi cels" abre o jogo; "fecha o jogo" exige "confirma".

- [x] **1.10 Ações: HUD** — abrir/fechar HUD, tela de ociosidade, RGB Sync, pelos mecanismos existentes. *(R6.1)*
  - Lê: `contracts.py`, `hud/README.md`, `hud/magi-view.py`, `hud/system/bin/gamerhud`, `hud/gamerhud.py` só `main` (flags de linha de comando)
  - Escreve: `magi/core/actions/hud.py`, testes
  - Depende de: 1.4
  - Orçamento: ~25k
  - Pronto: cada comando funciona por voz. Detalhes de CPU/GPU/memória ficam para 1.15.

- [x] **1.11 Ações: volume e RGB** — volume e mudo via `pulsectl`; cor e brilho via SDK do OpenRGB (estender `hud/orgb.py` com escrita). *(R6.2–R6.4)*
  - Lê: `contracts.py`, `docs/spikes/S1.md`, `hud/orgb.py`, R6
  - Escreve: `magi/core/actions/system.py`, `hud/orgb.py` (escrita de cor), testes
  - Depende de: 1.4, 0.4
  - Orçamento: ~35k
  - Pronto: "volume 30", "muta", "RGB azul" funcionam; OpenRGB fora → aviso.

- [x] **1.12 Voz no núcleo** — TTS em streaming, cache de frases curtas (gerado no primeiro uso), envio de áudio ao satélite. *(R12.1, R12.2)*
  - Lê: `contracts.py`, §4.1 (linha `tts`), §4.7, R12
  - Escreve: `magi/core/tts.py`, `magi/core/phrases.yaml`, testes com provedor falso
  - Depende de: 1.4, 0.6
  - Orçamento: ~35k
  - Pronto: frase em cache sai sem chamada de rede.

- [x] **1.13 Voz no satélite** — reprodução pelo PipeWire, `magi-mouth` a cada 50 ms, ducking de Spotify e jogo, `playback-done`, corte na interrupção. *(R12.4, R12.5)*
  - Lê: `contracts.py`, §5, `docs/spikes/S1.md`
  - Escreve: `magi/satellite/playback.py`, `magi/satellite/ducking.py`, testes
  - Depende de: 1.2, 1.12
  - Orçamento: ~35k
  - Pronto: comando conhecido responde em ≤ 1,5 s (RNF-04).

- [x] **1.14 HUD: rosto isolado** — módulo de desenho do rosto em caracteres: 7 expressões, boca por nível (<0,15 "—", <0,5 "o", resto "O"), piscar e olhar, legenda em mincho; script de demonstração que salva PNGs. Sem tocar no `gamerhud.py`. *(R17.1–R17.6)*
  - Lê: §6, R17, `hud/gamerhud.py` só a classe `Theme` e a função `alpha` (via `grep -n`)
  - Escreve: `hud/face.py`, `hud/tools/face_demo.py`, `tests/hud/test_face.py`
  - Depende de: —
  - Orçamento: ~40k
  - Pronto: PNG de cada expressão gerado; teste do mapeamento da boca.

- [x] **1.15 HUD: ponte de mensagens** — cliente do socket Unix que roda numa thread e entrega as mensagens do §6 como sinais Qt; comando `detail` (CPU/GPU/memória). Sem tocar no `gamerhud.py`.
  - Lê: `contracts.py` (mensagens do HUD), §6
  - Escreve: `hud/hud_bridge.py`, `tests/hud/test_bridge.py`
  - Depende de: 1.0
  - Orçamento: ~30k
  - Pronto: teste com servidor falso entrega todas as mensagens.

- [x] **1.16 HUD: integração** — ligar `face` e `hud_bridge` ao `gamerhud.py`: rosto na metade direita da tela de ociosidade e pequeno no cabeçalho do painel; 30 fps só na região do rosto acordado, 1 quadro a cada 4 s dormindo; rosto fora do monitor do jogo. *(R17.2–R17.4, R17.7)*
  - Lê: `hud/face.py` (interface pública), `hud/hud_bridge.py` (interface pública), §6, e do `hud/gamerhud.py` só: `HUD.__init__`, `sample`, `animate`, `render_caches`, `paintEvent`, `build_idle`, `build_background`, `main` (≈ 8–10k)
  - Escreve: `hud/gamerhud.py` (alterações localizadas)
  - Depende de: 1.14, 1.15
  - Orçamento: ~55k
  - Pronto: HUD ocioso sem aumento de CPU medido; boca acompanha a voz.

- [x] **1.17 Serviços** — units systemd `--user` para satélite e núcleo com reinício automático; `hud/install.sh` instala também a Magui. *(RNF-11)*
  - Lê: §1 (tabela de processos), `hud/install.sh`
  - Escreve: `deploy/systemd/magi-satellite.service`, `deploy/systemd/magi-core.service`, `hud/install.sh`
  - Depende de: 1.1, 1.4
  - Orçamento: ~25k
  - Pronto: `kill -9` em qualquer processo é recuperado em ≤ 5 s.

- [x] **1.19 Montagem do núcleo** — `magi-core` monta as dependências a partir da config: registro de provedores (3.1), `HintedStt` (1.5), `Corrections` + `CorrectionHandler` (1.6), `SteamCatalog` (1.7), roteador (1.8), `Registry` com as ações (1.9–1.11, 2.1), `Speaker` (1.12), repositórios Postgres e migração com a dimensão da config. Fecha as lacunas achadas na 1.6: `TurnContext.previous_text` (+ horário) preenchido pelo `TurnMachine` por satélite, e "refazer turno" (`ActionResult.redo_text` tratado uma vez pelo `TurnPipeline`). *(R3.3)*
  - Lê: `contracts.py` (TurnContext, ActionResult, TurnDeps), APIs públicas de `magi/core/turn.py`, `magi/core/service.py`, `magi/core/stt.py`, `magi/core/corrections.py`, `magi/core/catalog.py`, `magi/core/router.py`, `magi/core/tts.py`, `magi/core/actions/*` (só `handlers`), `magi/providers/registry.py`, `magi/common/config.py`
  - Escreve: `magi/core/assemble.py`, `magi/core/service.py` (main), `magi/common/contracts.py` (campos novos), `magi/core/turn.py` (redo/previous), testes
  - Depende de: 1.5, 1.6, 1.8, 1.9, 1.10, 1.11, 1.12, 2.1, 3.1
  - Orçamento: ~55k
  - Pronto: `magi-core` sobe com a config real (provedores sem chave degradam com aviso); turno de ponta a ponta com satélite falso usa todas as peças; "não, eu falei X" refaz o turno.

- [ ] **1.18 Medição da fase 1** — script de desempenho do §10 (CPU/RAM ociosos por 10 min, latência p90 de 50 turnos).
  - Lê: §10, tabela RNF de `requirements.md`
  - Escreve: `tools/perf.py`, `docs/perf/fase1.md`
  - Depende de: 1.13, 1.17, 1.19
  - Orçamento: ~25k
  - Pronto: RNF-01, RNF-02 e RNF-04 medidos e dentro da meta.

## Fase 2 — Spotify

- [x] **2.1 MPRIS** — abrir o flatpak; tocar, pausar, próxima, anterior, volume; esperar o MPRIS até 15 s. *(R7.1, R7.3)*
  - Lê: `contracts.py`, §2 (linha Spotify), R7
  - Escreve: `magi/core/actions/spotify_mpris.py`, testes com D-Bus falso
  - Depende de: 1.4
  - Orçamento: ~30k
  - Pronto: comandos funcionam com o Spotify aberto ou fechado.

- [x] **2.2 Web API** — OAuth PKCE com tokens no keyring; busca por nome e reprodução no app local. **Precisa de mim** para criar o app de desenvolvedor e autorizar. *(R7.2)*
  - Lê: `contracts.py`, `magi/common/secrets.py` (interface), R7
  - Escreve: `magi/core/actions/spotify_api.py`, `magi/cli/spotify_login.py`, testes
  - Depende de: 2.1, 0.2
  - Orçamento: ~35k
  - Pronto: "toca Linkin Park" toca o artista.

- [x] **2.3 Importar gosto** — mais ouvidos (3 prazos) e recentes para `taste`. *(R8.2)*
  - Lê: `contracts.py`, §7 (tabelas de música), R8
  - Escreve: `magi/memory/taste_repo.py`, `magi/core/music/import_taste.py`, testes
  - Depende de: 2.2, 0.3
  - Orçamento: ~25k
  - Pronto: tabela preenchida na primeira execução.

- [ ] **2.4 Sinais de música** — pulo < 30 s, ouvida inteira, "essa é boa", "nunca mais". *(R8.3–R8.5)*
  - Lê: `contracts.py`, §7 (tabelas de música), R8
  - Escreve: `magi/core/music/signals.py`, testes
  - Depende de: 2.1, 2.3
  - Orçamento: ~30k
  - Pronto: sinais aparecem ao pular ou terminar faixas escolhidas pela Magui.

- [ ] **2.5 "Coloca uma boa"** — escolha por gosto + contexto (horário, gênero do jogo, pedido). *(R8.1)*
  - Lê: `contracts.py`, R8, R15.5 (gênero pelas tags), interfaces de 2.2–2.4
  - Escreve: `magi/core/music/pick.py`, testes
  - Depende de: 2.4
  - Orçamento: ~35k
  - Pronto: responde em ≤ 3 s e nunca escolhe faixa com "nunca mais".

## Fase 3 — Agente

- [x] **3.1 Provedores e KeyPool** — registro por tarefa; rodízio de chaves com espera progressiva; bloqueio de `personal=True` em cota gratuita. *(R21.1–R21.5)*
  - Lê: `contracts.py`, §4.7, R21
  - Escreve: `magi/providers/registry.py`, `magi/providers/keypool.py`, testes
  - Depende de: 0.2
  - Orçamento: ~30k
  - Pronto: teste simula 429 e troca de chave; teste do bloqueio.

- [x] **3.2 Orçamento** — custo por chamada, teto por voz e config, aviso em 80%, bloqueio em 100%, virada do mês. *(R16.1–R16.5)*
  - Lê: `contracts.py`, §4.6, §7 (tabela `costs`), R16
  - Escreve: `magi/core/budget.py`, `magi/memory/costs_repo.py`, testes
  - Depende de: 3.1, 0.3
  - Orçamento: ~30k
  - Pronto: testes de cada regra.

- [x] **3.3 Persona** — prompt fixo (~500 tokens) com os 5 traços e o tom por nível de humor; 10 perguntas de avaliação. *(R13.1, R13.2, R13.6)*
  - Lê: R13, R14, §4.3 (tabela do prompt)
  - Escreve: `magi/agent/persona.md`, `magi/agent/prompt.py`, `tests/agent/eval_persona.yaml`
  - Depende de: 1.0
  - Orçamento: ~20k
  - Pronto: prompt montado ≤ 1.500 tokens com perfil e memórias de exemplo.

- [x] **3.4 Grafo do agente** — LangGraph (modelo + ferramentas), limite de 4 passos, ferramentas perigosas devolvendo `needs_confirmation`; só as ferramentas `open_game`, `hud` e `volume`, reaproveitando as ações da fase 1. *(R11.3, R5.3)*
  - Lê: `contracts.py`, §4.3, `magi/agent/prompt.py` (interface), interfaces das ações em `magi/core/actions/`
  - Escreve: `magi/agent/graph.py`, `magi/agent/tools/base.py`, `magi/agent/tools/system.py`, testes com modelo falso
  - Depende de: 3.1, 3.2, 3.3, 1.9, 1.10, 1.11
  - Orçamento: ~45k
  - Pronto: pergunta geral respondida em ≤ 3 s (RNF-05).

- [ ] **3.5 Ferramentas de mídia** — `close_game` (confirmação), `rgb`, `spotify_play`, `spotify_control`, `spotify_pick`.
  - Lê: `contracts.py`, `magi/agent/tools/base.py`, interfaces das ações de jogos, sistema e Spotify
  - Escreve: `magi/agent/tools/media.py`, testes
  - Depende de: 3.4, 2.5
  - Orçamento: ~35k
  - Pronto: cada ferramenta chamada corretamente pelo modelo falso.

- [ ] **3.6 Resposta curta e completa** — até 2 frases faladas; resposta completa e links como `subtitle`/`card` no HUD. *(R12.3)*
  - Lê: `contracts.py` (mensagens do HUD), §6, R12
  - Escreve: `magi/core/compose.py`, testes
  - Depende de: 3.4
  - Orçamento: ~25k
  - Pronto: card com links aparece no HUD.

- [ ] **3.7 Visão** — `screenshot(window|screen)` só sob pedido; apaga após envio. *(R9.1–R9.4)*
  - Lê: `contracts.py`, R9, `magi/agent/tools/base.py`
  - Escreve: `magi/agent/tools/vision.py`, testes
  - Depende de: 3.4
  - Orçamento: ~30k
  - Pronto: "que bicho é esse?" responde sobre a janela ativa em ≤ 5 s.

- [ ] **3.8 Pesquisa** — Gemini com busca do Google; só a pergunta reescrita; links no HUD. *(R10.1–R10.3)*
  - Lê: `contracts.py`, R10, §4.7, `magi/agent/tools/base.py`
  - Escreve: `magi/agent/tools/search.py`, testes
  - Depende de: 3.4
  - Orçamento: ~30k
  - Pronto: pergunta sobre algo recente vem com fonte.

## Fase 4 — Memória e personalidade

- [ ] **4.1 Memórias** — gravação por turno, busca de até 5 por similaridade, "esquece isso", histórico local. *(R11.2, R11.5, R11.6)*
  - Lê: `contracts.py`, §7 (tabelas de conversa), R11
  - Escreve: `magi/memory/memories_repo.py`, `magi/agent/tools/memory.py`, testes
  - Depende de: 3.4, 0.3
  - Orçamento: ~40k
  - Pronto: fato contado num dia é lembrado no outro; "esquece isso" remove.

- [ ] **4.2 Perfil e estilo** — perfil ≤ 300 tokens atualizado 1×/dia com gírias, formalidade e tamanho de resposta. *(R11.1, R11.4)*
  - Lê: `contracts.py`, §7 (`profile`, `vocab`), R11
  - Escreve: `magi/memory/profile.py`, testes
  - Depende de: 4.1
  - Orçamento: ~30k
  - Pronto: perfil muda após uma semana, sem passar do limite.

- [ ] **4.3 Humor no núcleo** — sinais locais, nota 0–4 suavizada, "pega leve" / "pode pegar pesado", nível no prompt e `mood` ao HUD. *(R13.3–R13.5)*
  - Lê: `contracts.py`, §4.4, R13
  - Escreve: `magi/memory/mood.py`, testes
  - Depende de: 4.1
  - Orçamento: ~35k
  - Pronto: testes da nota e dos comandos.

- [ ] **4.4 Termômetro no HUD** — desenhar o termômetro ao lado do rosto a partir de `mood`. *(R13.7)*
  - Lê: `hud/face.py` (interface), `hud/hud_bridge.py` (interface), do `hud/gamerhud.py` só `build_idle` e o trecho do rosto adicionado em 1.16
  - Escreve: `hud/face.py`, `hud/gamerhud.py` (alteração localizada)
  - Depende de: 1.16, 4.3
  - Orçamento: ~30k
  - Pronto: nível visível e atualizado.

- [ ] **4.5 Ajuda no jogo** — `help_log`, tópico canônico, degraus, "manda a solução", travado por pedidos repetidos e conquistas. *(R14.1–R14.5)*
  - Lê: `contracts.py`, §4.5, §7 (`help_log`), R14
  - Escreve: `magi/memory/help.py`, `magi/agent/tools/help.py`, testes
  - Depende de: 4.1
  - Orçamento: ~35k
  - Pronto: segunda ajuda no mesmo trecho começa na dica direta.

- [ ] **4.6 Frases de ouro, rodada 2** — ampliar com 2 semanas de turnos reais. *(RNF-07)*
  - Lê: `tests/data/utterances.yaml`, `magi/core/intents.yaml`
  - Escreve: `tests/data/utterances.yaml`, `magi/core/intents.yaml`
  - Depende de: 1.8 + uso real
  - Orçamento: ~20k
  - Pronto: acerto ≥ 95%.

## Fase 5 — Proatividade e Discord

- [x] **5.1 Detecção de call** — `source-output` do Discord a cada 2 s; desliga e religa o "Ei Magui". *(R2.1, R2.2)*
  - Lê: `contracts.py`, §3.2, `docs/spikes/S1.md`, R2
  - Escreve: `magi/satellite/discord.py`, testes
  - Depende de: 1.1
  - Orçamento: ~25k
  - Pronto: entrar e sair de call alterna a detecção em ≤ 5 s.

- [ ] **5.2 Mudo só para o Discord** — PTT em call muta e restaura; recuperação após queda. *(R2.3, R2.4)*
  - Lê: `contracts.py`, §3.2, R2, `magi/satellite/discord.py`
  - Escreve: `magi/satellite/discord.py`, `magi/satellite/ptt.py` (ligação), testes
  - Depende de: 5.1, 1.3
  - Orçamento: ~30k
  - Pronto: amigos não ouvem a fala para a Magui.

- [x] **5.3 Alertas** — temperatura de CPU/GPU, bateria do controle ≤ 15%, custo 80%/100%; só na tela em call. *(R15.1, R15.2)*
  - Lê: `contracts.py`, R15, do `hud/gamerhud.py` só as classes `Sensors` e a função `controllers` (lógica reaproveitável)
  - Escreve: `magi/core/proactive/alerts.py`, testes
  - Depende de: 1.12, 3.2, 5.1
  - Orçamento: ~35k
  - Pronto: alerta simulado por voz fora de call e só na tela em call.

- [ ] **5.4 Sugestão de música** — gênero pelas tags da Steam; casual no máximo 1×/sessão; imersivo e competitivo nunca. *(R15.3–R15.6)*
  - Lê: `contracts.py`, R15, interface de `magi/core/music/pick.py`
  - Escreve: `magi/core/proactive/music.py`, `magi/core/steam_tags.py`, testes
  - Depende de: 2.5
  - Orçamento: ~30k
  - Pronto: jogo de corrida sugere; RPG não.

## Fase 6 — Notícias

- [x] **6.1 Fontes, agendamento e RSS** — tabela de fontes com confiança 1–3, timer systemd a cada 2 h, coletor RSS, deduplicação por URL. *(R18.1, R18.4)*
  - Lê: `contracts.py`, §8 (passo 1), §7 (tabelas de notícias), R18
  - Escreve: `magi/news/sources.py`, `magi/news/collect/rss.py`, `magi/news/__main__.py`, `deploy/systemd/magi-news.{service,timer}`, testes
  - Depende de: 0.3
  - Orçamento: ~40k
  - Pronto: execução coleta itens novos em ≤ 1 min sem duplicar URLs.

- [x] **6.2 Coletor Steam News** — notícias dos jogos instalados.
  - Lê: `magi/news/sources.py` (interface), `magi/core/catalog.py` (interface)
  - Escreve: `magi/news/collect/steam.py`, testes
  - Depende de: 6.1, 1.7
  - Orçamento: ~25k
  - Pronto: notícias de um jogo instalado coletadas.

- [x] **6.3 Coletor AniList** — temporadas e sequências das obras da minha lista.
  - Lê: `magi/news/sources.py` (interface), R19
  - Escreve: `magi/news/collect/anilist.py`, testes
  - Depende de: 6.1
  - Orçamento: ~30k
  - Pronto: sequência anunciada aparece como item.

- [x] **6.4 Coletor Reddit** — r/anime e r/Games com OAuth, confiança 1.
  - Lê: `magi/news/sources.py` (interface)
  - Escreve: `magi/news/collect/reddit.py`, testes
  - Depende de: 6.1
  - Orçamento: ~25k
  - Pronto: posts entram marcados como fonte de confiança 1.

- [x] **6.5 Scraping genérico** — `robots.txt`, 1 req/s por domínio, extração por seletor configurado. *(R18.2)*
  - Lê: `magi/news/sources.py` (interface), R18
  - Escreve: `magi/news/collect/scrape.py`, testes
  - Depende de: 6.1
  - Orçamento: ~30k
  - Pronto: site sem feed coletado respeitando `robots.txt`.

- [x] **6.6 Agrupamento** — embeddings Gemini, cosseno ≥ 0,88 em 72 h. *(R18.3)*
  - Lê: `contracts.py`, §8 (passo 2), `magi/providers/registry.py` (interface)
  - Escreve: `magi/news/cluster.py`, testes
  - Depende de: 6.1, 3.1
  - Orçamento: ~30k
  - Pronto: a mesma notícia de 3 sites vira 1 item com 3 fontes.

- [x] **6.7 Classificação** — Gemini em lote, saída JSON (franquia, tipo, spoiler, tamanho, manchete segura), prompt fixo + até 6 exemplos do meu retorno; cota esgotada adia. *(R18.6, R19.1)*
  - Lê: `contracts.py`, §8 (passo 3 e 6), R18, R19
  - Escreve: `magi/news/classify.py`, `magi/news/prompts/classify.md`, testes
  - Depende de: 6.6
  - Orçamento: ~40k
  - Pronto: 20 itens reais classificados e revisados por mim.

- [x] **6.8 Progresso** — lista de anime (AniList ou MAL, a decidir) e horas/conquistas da Steam em `progress`.
  - Lê: `contracts.py`, §7 (`progress`), R19
  - Escreve: `magi/news/progress.py`, testes
  - Depende de: 6.3
  - Orçamento: ~35k
  - Pronto: episódio visto e horas jogadas atualizados.

- [x] **6.9 Anti-spoiler** — manchete reescrita ou escondida; "pode dar spoiler de X". *(R19.1–R19.3)*
  - Lê: `contracts.py`, R19, interfaces de 6.7 e 6.8
  - Escreve: `magi/news/spoiler.py`, testes
  - Depende de: 6.7, 6.8
  - Orçamento: ~30k
  - Pronto: notícia com spoiler de obra em andamento nunca aparece com o spoiler.

- [x] **6.10 Prioridade e entrega** — fórmula do §8, níveis, regra da bomba (2 fontes, uma de confiança 3), envio ao núcleo. *(R18.5, R19.4–R19.6)*
  - Lê: `contracts.py`, §8 (passos 4 e 5), R19
  - Escreve: `magi/news/priority.py`, `magi/core/proactive/news.py`, testes
  - Depende de: 6.9, 5.3
  - Orçamento: ~35k
  - Pronto: "bomba" simulada falada fora de call; "alta" vira card.

- [ ] **6.11 Retorno e aprendizado** — "não curti", ignorados 3×, "mais disso", obra largada. *(R19.7, R19.8)*
  - Lê: `contracts.py`, §7 (`franchise_prefs`, `news_feedback`), R19
  - Escreve: `magi/news/feedback.py`, testes
  - Depende de: 6.10
  - Orçamento: ~25k
  - Pronto: tema rejeitado cai de nível na execução seguinte.

- [ ] **6.12 Perguntas sobre novidades** — ferramenta `news_query`, "novidades?" com até 5 itens, fallback para pesquisa. *(R20.1–R20.3)*
  - Lê: `contracts.py`, R20, `magi/agent/tools/base.py`, interface de 6.9
  - Escreve: `magi/agent/tools/news.py`, testes
  - Depende de: 6.10, 3.8
  - Orçamento: ~30k
  - Pronto: "o que saiu de novo do Silksong?" responde com links.

## Encerramento do MVP

- [ ] **7.1 Medição final** — todos os RNF medidos e registrados.
  - Lê: tabela RNF de `requirements.md`, `tools/perf.py`
  - Escreve: `docs/perf/mvp.md`, `README.md`
  - Orçamento: ~25k
- [ ] **7.2 Duas semanas de uso real** — conferir as métricas de sucesso do PRD. **Precisa de mim.**
