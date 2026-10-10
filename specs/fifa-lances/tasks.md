# Tarefas — Lances do FIFA 22

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`. As tarefas F2.x dependem do SDD
`specs/condessa-vida/` (IDs `V0.n`).

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `F` (ex.: `F5.1`), vida por `vida spec §`.
2. **Orçamento planejado ≤ 50k tokens**; o resto da janela de 128k é margem. Perto de 90k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use `magi/lances/contratos.py` e as assinaturas dos stubs; não leia o
   código de outras tarefas além do que o *Lê* manda.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + intervalo): nunca leia inteiros `hud/gamerhud.py`,
   `hud/wired/data.py`, `hud/wired/main_screen.py`, `hud/wired/integration.py`,
   `hud/wired/reactions.py`, `hud/wired/reacoes/catalogo.py`, `magi/core/assemble.py`,
   `magi/common/events.py`, `magi/common/contracts.py`.
6. **Testes curtos:** `uv run pytest -q -x tests/lances/<arquivo>` (ou `tests/hud/<arquivo>`) e
   `uv run ruff check <seus arquivos>`. Relógio injetado; nada de `sleep` real.
7. **Nada ao vivo nos testes:** sem portal/D-Bus de verdade (barramento falso), sem
   `gst-launch-1.0`, `spectacle`, `pw-record` ou `pw-dump` reais (subprocesso injetado), sem abrir
   o jogo, sem reiniciar serviços, sem LLM. **Nunca `qdbus`/`gdbus` nem D-Bus para o
   KWin/KGlobalAccel** (derruba a sessão KDE) — só `org.freedesktop.portal.Desktop`.
8. **Uma tarefa = um commit** direto no `main`, mensagem começando com o ID (`F1.4: máquina da
   partida`) e terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem push.
   Marque `- [x]` no mesmo commit.
9. **Nada de imagem da tela em disco** fora da calibração (F2.3 do requirements).

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~2,8k,
`design.md` ~2,8k, `spec.md` ~4,5k, `game_context.py` ~4k, `data.py` 1389 linhas (só por trecho).

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
F0.1 ─┬─ F1.1 (portal + captura) ─┬─ F1.2 (calibração) ─┐
      ├─ F1.3 (OCR) ──────────────┤                      ├─ F1.6 (ao vivo: calibra e mede, Pedro) ─┬─ F3.1 (spike narrador) ┄┄ F3.2 (só com "vai")
      ├─ F1.4 (máquina) ──────────┴─ F1.5 (olhar + serviço no núcleo) ┘                            │
      └─ F2.1 (HUD: ponte + det_lances; dep V0.1) ── F2.2 (cenas e humor; dep V0.8, V0.10) ────────┴─ F2.3 (2 partidas, Pedro)
```

---

## Fase F0 — Contratos

- [ ] **F0.1 Contratos, config e esqueleto** — pacote `magi/lances/` com `contratos.py` (spec §1),
  `config.py` (spec §7; sobreposição pelo `lances-recorte.json`), stubs com assinatura final e
  docstring da tarefa dona (`portal`, `captura`, `calibrar`, `ocr`, `partida`, `servico`,
  `__main__`, `narrador`); `times.toml` com o cabeçalho e ~40 clubes/seleções comuns do FIFA 22
  (sigla → nome falado); `LanceMsg` (`{"t":"lance", ...}` = linha do protocolo da spec §2) em
  `magi/common/contracts.py` + codificador/decodificador em `magi/common/events.py` (modelo:
  `TurnTagMsg`); entrada `magi-lances` no `pyproject.toml`; `tests/lances/conftest.py` isolando
  `~/.local/state/magi` e `~/.cache/magi`. *(F1–F10)*
  - Lê: design §2 e §4, spec §1, §2 (protocolo) e §7, `magi/common/events.py` `grep -n "turn_tag\|TurnTagMsg"` ±10 linhas, `magi/common/contracts.py` `grep -n "class TurnTagMsg" -A12` e `grep -n "HudMessage ="`
  - Escreve: `magi/lances/*`, `magi/common/contracts.py` (só `LanceMsg` e `HudMessage`), `magi/common/events.py` (só o `lance`), `pyproject.toml` (só o script), `tests/lances/conftest.py`, `tests/lances/test_contratos.py`
  - Depende de: —
  - Orçamento: ~35k
  - Pronto: `Lance.json()` ↔ `decode_hud` ida e volta; imports de todos os stubs; `tests/core/test_assemble.py` verde; `ruff` limpo.
  - Paralelo: —

## Fase F1 — Ver o placar

- [ ] **F1.1 Portal e captura** — `portal.py` (sessão ScreenCast com `dbus-next`: `CreateSession`
  → `SelectSources(MONITOR, persist_mode=2, restore_token)` → `Start` → `OpenPipeWireRemote`;
  espera os sinais `Response` com timeout; regrava o token a cada `Start` em
  `~/.local/state/magi/lances-portal.json` 0600; recusa → `PermissaoNegada`), `captura.py`
  (pipeline da spec §2 com `pass_fds`, `Quadros` iterável, `PR_SET_PDEATHSIG`, para limpo) e o
  subcomando `magi-lances teste-captura [segundos]` (só imprime quadros/s e tamanho; não salva
  imagem) para o Pedro dar a permissão a 1ª vez. *(F2, F2.1–F2.3)*
  - Lê: design §3, spec §2, requirements F2, `hud/wired/data.py` linhas 1104–1126 (`_morrer_com_o_pai`, `_dbus_monitor`), documentação do portal só pelo que já está no design §3 (sem web)
  - Escreve: `magi/lances/portal.py`, `magi/lances/captura.py`, `magi/lances/__main__.py` (só `teste-captura`), `tests/lances/test_portal.py`, `tests/lances/test_captura.py`
  - Depende de: F0.1
  - Orçamento: ~45k
  - Pronto: CA-F1 e CA-F2 verdes com barramento e processo falsos.
  - Paralelo: F1.3, F1.4, F2.1

- [ ] **F1.2 Calibração** — `calibrar.py` e o subcomando `magi-lances calibrar`: confere que o
  FIFA está aberto (`/proc`, mesmo `processo` do `[fifa]`), roda `spectacle -b -n -f -o
  ~/.cache/magi/lances/calibracao.png` (timeout 10 s), aplica o recorte padrão da resolução
  (tabela no módulo: 1920×1080, 2560×1440, 3840×2160; outras = frações de 2560×1440), salva o
  recorte em `calibracao-recorte.png`, roda o `ocr.ler` nele e mostra o que leu; `--recorte
  x,y,w,h` grava `lances-recorte.json`. Sem argumento só mostra. *(F3)*
  - Lê: requirements F3, spec §3 e §7, `magi/lances/contratos.py`, `magi/lances/ocr.py` (só a assinatura)
  - Escreve: `magi/lances/calibrar.py`, `magi/lances/__main__.py` (só `calibrar`), `tests/lances/test_calibrar.py`
  - Depende de: F1.1 (o `__main__`), F1.3
  - Orçamento: ~30k
  - Pronto: com `spectacle` falso que grava uma PNG sintética, o recorte e o JSON saem certos; sem FIFA aberto → mensagem e código 2.
  - Paralelo: F1.5

- [ ] **F1.3 OCR do placar** — `ocr.py` (spec §3): pré-processo em numpy, motor plugável
  (`rapidocr` padrão, D2; `tesseract` se o binário existir; `modelos` como stub documentado),
  sub-regiões, pular OCR sem mudança, relógio a cada 5 s, interpretação por regex independente da
  ordem, confirmação em 2 quadros. Dependência `rapidocr-onnxruntime` no `pyproject.toml`. *(F4)*
  - Lê: spec §1 e §3, requirements F4, `magi/lances/contratos.py`
  - Escreve: `magi/lances/ocr.py`, `pyproject.toml` (só a dependência), `uv.lock`, `tests/lances/test_ocr.py`, `tests/lances/fixtures/` (gerador de placares sintéticos com PIL)
  - Depende de: F0.1
  - Orçamento: ~45k
  - Pronto: CA-F3 (parte sintética); 1 quadro OCR ≤ 60 ms no CPU do Pedro medido no teste (marcado `slow`, fora do `-x` padrão).
  - Paralelo: F1.1, F1.4, F2.1

- [ ] **F1.4 Máquina da partida** — `partida.py` (spec §4) pura, com relógio injetado; lado do
  Pedro (F6) inclusive troca no meio ("tô com o {time}" chega como `Maquina.meu_time(sigla)`). *(F5, F5.1, F5.2, F6)*
  - Lê: spec §1 e §4, requirements F5–F6, `magi/lances/contratos.py`
  - Escreve: `magi/lances/partida.py`, `tests/lances/test_partida.py`
  - Depende de: F0.1
  - Orçamento: ~40k
  - Pronto: CA-F4 (tabela de sequências + 2 h simuladas com ruído, `rng` semeado).
  - Paralelo: F1.1, F1.3, F2.1

- [ ] **F1.5 `olhar` e serviço no núcleo** — `__main__.py olhar` (portal → captura → ocr →
  máquina → JSONL no stdout; `resumo` no fim; sai com o pai) e `servico.py` (`Servico.on_game` assinado
  no `GameWatcher`: sobe/derruba o subprocesso só para o `processo` do `[fifa]`, reinicia ≤ 3×/partida;
  lê o JSONL; `LanceMsg` ao HUD; card (F9); falas pela spec §6 no `ProactiveSink` com cotas, em call/
  leitura → legenda, zoeira pelo humor do Pedro; `lances.jsonl` com giro de 5 MB; `permissao` → legenda).
  Intents `fifa.watch_off` ("para de assistir o jogo"), `fifa.watch_on` ("pode olhar a tela") e
  `fifa.my_team` ("tô com o {query}") no `intents.yaml`/`IntentId`, com handler no `servico.py`.
  Frases novas em `magi/core/i18n/en-gb.yaml`. Registro no `assemble.py` (ao lado do
  `MusicSuggester`, linha ~960). *(F1, F1.1, F2.1, F6, F8, F8.1, F8.2, F9, F10)*
  - Lê: design §2, spec §2, §6 e §7, requirements F1, F6, F8–F10, `magi/core/game_context.py` linhas 46–75 e 178–230, `magi/core/proactive/sink.py` linhas 1–30 e 120–155, `magi/core/assemble.py` linhas 940–970, `magi/core/proactive/music.py` `grep -n "def on_game" -A25` (modelo), `magi/core/intents.yaml` linhas 1–40
  - Escreve: `magi/lances/__main__.py` (só `olhar`), `magi/lances/servico.py`, `magi/lances/times.toml`, `magi/core/assemble.py`, `magi/core/intents.yaml`, `magi/common/contracts.py` (só `IntentId`), `magi/core/i18n/en-gb.yaml`, `tests/lances/test_servico.py`, `tests/lances/test_olhar.py`
  - Depende de: F1.1, F1.3, F1.4
  - Orçamento: ~50k
  - Pronto: CA-F5; `uv run pytest -q tests/core` verde.
  - Paralelo: F1.2, F2.1

- [ ] **F1.6 Ao vivo: permissão, calibração e medida (com o Pedro)** — o Pedro abre o FIFA e roda
  `magi-lances teste-captura 60` (dá a permissão "lembrar"), depois `magi-lances calibrar` com uma
  partida na tela; o agente lê a saída, ajusta o recorte/sub-regiões e grava os padrões reais na
  tabela do `calibrar.py`; o Pedro joga 10 min com o `magi-core` ligado e o agente compara FPS
  médio (MangoHud CSV em `~/.cache/gamerhud/fps` com e sem captura), CPU do `magi-lances` (`ps`
  a cada 5 s) e o `lances.jsonl`. Capturas da calibração viram fixtures reais do CA-F3 (o Pedro
  aprova o commit das imagens recortadas, só o placar). *(critérios 3 e 4; D1, D2)*
  - Lê: requirements (critérios), spec §2–§3 e §7, saída dos comandos e logs por `grep`
  - Escreve: `magi/lances/calibrar.py` (só a tabela), `tests/lances/fixtures/reais/`, `docs/PROXIMOS-PASSOS.md` (§13, medidas)
  - Depende de: F1.2, F1.5, Pedro (jogo aberto)
  - Orçamento: ~30k
  - Pronto: permissão persistente confirmada (2ª execução sem diálogo); CPU e FPS anotados; se FPS cair > 3%, `intervalo_s` ajustado e medido de novo.
  - Paralelo: F2.2

## Fase F2 — Rosto

- [ ] **F2.1 HUD: ponte e detector** — `hud/hud_bridge.py` (`_MIN_DECODERS["lance"]`, sinal
  `lance(dict)`), `gamerhud.on_bridge_lance` → `WiredUI.set_lance(d)` → `Snapshot.lance = (d,
  time.monotonic())`; `hud/wired/reacoes/det_lances.py` (spec §5, primeira metade: um `Disparo`
  por lance, idade ≤ 15 s, causa por grupo) registrado em `DETECTORES`. Sem `Def` no catálogo
  ainda (o lance não entra em `ATIVAS` sem o F2.2). *(F7)*
  - Lê: spec §5, design §5, `hud/hud_bridge.py` `grep -n "turn_tag\|turnTag"` ±10 linhas, `hud/gamerhud.py` `grep -n "turn_tag"` ±8, `hud/wired/main_screen.py` `grep -n "turn_tag"` ±3, `hud/wired/integration.py` `grep -n "turn_tag"` ±8, `hud/wired/reacoes/__init__.py`, `hud/wired/reacoes/contratos.py` (o `Disparo`, com o campo `causa` do V0.1)
  - Escreve: `hud/hud_bridge.py`, `hud/gamerhud.py`, `hud/wired/main_screen.py` (só `Snapshot.lance`), `hud/wired/integration.py`, `hud/wired/reacoes/det_lances.py`, `hud/wired/reacoes/__init__.py`, `tests/hud/test_reacoes_lances.py`
  - Depende de: F0.1, V0.1 (vida: `Disparo.causa`)
  - Orçamento: ~40k
  - Pronto: CA-F6 (parte da ponte e do detector); `uv run pytest -q tests/hud` verde.
  - Paralelo: F1.1, F1.3, F1.4, F1.5

- [ ] **F2.2 Cenas e humor do lance** — roteiros da spec §5 como cenas no catálogo/diretor da
  vida (tipos, ramos `virada`/`goleada`, prioridades, vitória furando a cota de cenas, fila atrás
  da cena de episódio), eventos de humor com os números em `[vida.lances]` do
  `persona/condessa-gosto.toml`, bloqueio de C11/C12 com humor do Pedro baixo. *(F7, F7.1, F7.2)*
  - Lê: spec §5, requirements F7, vida spec §1, §2 e §8, `hud/wired/reacoes/diretor.py` (`grep -n "ROTEIROS\|def receber\|def _ramo"` ±20), `hud/wired/reacoes/catalogo.py` `grep -n "CENA"` ±5, `persona/condessa-gosto.toml` `grep -n "\[vida"` ±10
  - Escreve: `hud/wired/reacoes/diretor.py` (só o mapa lance → cena e os ramos), `hud/wired/reacoes/catalogo.py` (só as cenas de lance), `persona/condessa-gosto.toml` (só `[vida.lances]`), `tests/hud/test_reacoes_lances.py`
  - Depende de: F2.1, V0.8, V0.10
  - Orçamento: ~45k
  - Pronto: CA-F6 completo (3 gols em 40 s = 1 cena `goleada`; lance durante cobrança de FPS fica na fila); testes da vida verdes.
  - Paralelo: F1.6

- [ ] **F2.3 Validação em 2 partidas (com o Pedro)** — o Pedro joga 2 partidas inteiras com HUD e
  núcleo ligados; o agente cruza `lances.jsonl`, `reacoes.jsonl` e o placar que o Pedro diz no fim.
  Ajusta limiares (`confianca_min`, tempos da máquina) e anota erros. *(critérios 1, 2, 5, 6)*
  - Lê: requirements (critérios), spec §4–§6, os dois `.jsonl` por `grep`/`jq`
  - Escreve: `magi/lances/partida.py` (só constantes), `persona/condessa-gosto.toml` (só `[vida.lances]`), `docs/PROXIMOS-PASSOS.md` (§13)
  - Depende de: F1.6, F2.2, Pedro
  - Orçamento: ~30k
  - Pronto: critérios 1, 2, 5 e 6 medidos e anotados; com o F1.6 (critérios 3 e 4), fecha o CA-F7.
  - Paralelo: F3.1

## Fase F3 — Narrador (condicional)

- [ ] **F3.1 Spike do áudio do narrador** — script descartável em `magi/lances/spike_narrador.py`:
  `pw-dump` → nó de saída do processo do jogo; `pw-record --target <serial>` 16 kHz mono por 5 min
  com o Pedro jogando (o áudio fica só em memória); STT local com gramática de palavras-chave
  (Vosk pequeno no idioma do D5) e, para comparar, `faster-whisper tiny`; mede CPU, atraso e
  acerto em "gol" contra o `lances.jsonl` do mesmo período. Relatório curto no fim deste arquivo
  (*Sobras*) com o go/no-go proposto. *(F11, D5, D6)*
  - Lê: design §6, requirements F11 e D5–D6, saída do `pw-dump` filtrada por `jq`
  - Escreve: `magi/lances/spike_narrador.py`, `specs/fifa-lances/tasks.md` (só *Sobras*)
  - Depende de: F1.6, Pedro (jogo aberto, D5)
  - Orçamento: ~40k
  - Pronto: números de CPU, atraso e acerto anotados; decisão do Pedro registrada.
  - Paralelo: F2.3

- [ ] **F3.2 Narrador (só com o "vai" do Pedro)** — `narrador.py` (captura do fluxo do jogo + STT
  local + palavras-chave → lances `CHANCE`/`ENTRADA_FORTE`/`CARTAO`/`PENALTI`/`DEFESA`/`TRAVE`
  no mesmo protocolo), ligado no `olhar`; cenas curtas novas pelo mesmo caminho do F2.2. Pacote
  exato definido pelo resultado do F3.1. *(F11)*
  - Lê: relatório do F3.1, spec §1–§2 e §5
  - Escreve: `magi/lances/narrador.py`, `magi/lances/__main__.py`, `tests/lances/test_narrador.py` (cenas: tarefa à parte, se precisar)
  - Depende de: F3.1 aprovado
  - Orçamento: ~50k
  - Pronto: definido no F3.1.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
