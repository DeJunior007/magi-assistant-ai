# Tarefas — Overlay da Condessa

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `R`/`D`.
2. **Orçamento planejado ≤ 50k tokens**; o resto da janela de 128k é margem. Perto de 100k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use as assinaturas de `hud/wired/overlay.py` (O0.1); não leia o código
   de outras tarefas além das assinaturas.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `hud/gamerhud.py`, `hud/wired/portrait.py`, `hud/wired/main_screen.py`, `hud/wired/integration.py`,
   `hud/wired/data.py`, `hud/wired/reactions.py`.
6. **Testes curtos:** `uv run pytest -q -x tests/hud/<arquivo>` e `uv run ruff check <seus arquivos>`.
   Relógio injetado; nada de `sleep` real; Qt com `QT_QPA_PLATFORM=offscreen`.
7. **Nada ao vivo nos testes:** sem abrir o HUD, sem `kwriteconfig6`/`kreadconfig6` de verdade
   (comando injetado ou `HOME` falso), sem o socket real do núcleo, sem MPRIS real. **Nunca**
   `qdbus`/`gdbus` nem D-Bus para KGlobalAccel/KWin (derruba a sessão KDE).
8. **Uma tarefa = um commit** com o ID (`O1.2: região de entrada`), na branch `overlay/<ID>`;
   merge no `main` pelo orquestrador.
9. **O clique no rosto só faz reação** (decisão de 2026-10-10): nada no overlay chama
   `push_to_talk` nem manda `cmd` ao núcleo.

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~2,5k,
`design.md` ~2k, `spec.md` ~3,5k, `hud_bridge.py` ~5k (ler só a classe), `install.sh` ~3k.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
O0.1 ─┬─ O1.1 ─┐
      ├─ O1.2 ─┴─ O1.3 ─┐
      └─ O2.1 ──────────┴─ O3.1 (ao vivo, Pedro) ── O3.2 (semana)
```

---

## Fase O0 — Contratos

- [ ] **O0.1 Contratos e esqueleto** — `hud/wired/overlay.py` com as constantes de caminho, `Config`
  (`ler`/`gravar` completos), `canto_para_posicao` completo, e **stubs** com assinatura final e
  docstring da tarefa dona: `Gestos`, `regiao_entrada`, `snapshot_leve`, `hud_aberto`,
  `jogo_aberto`, `DETECTORES_OVERLAY = ()`. *(R9, spec §1–§2)*
  - Lê: design §2, spec §1–§2, requirements R9 e D6
  - Escreve: `hud/wired/overlay.py`, `tests/hud/test_overlay_config.py`
  - Depende de: —
  - Orçamento: ~25k
  - Pronto: CA-O1 e CA-O4 verdes; `ruff` limpo; o módulo importa sem `QApplication` (só `QtCore`/`QtGui` tipos).
  - Paralelo: —

## Fase O1 — Peças

- [ ] **O1.1 Gestos, snapshot leve e reações** — `Gestos` (spec §1, constantes copiadas do
  `gamerhud`), `snapshot_leve`, `DETECTORES_OVERLAY`, `hud_aberto` (flock não bloqueante, solta na
  hora), `jogo_aberto` (carrega `hud/gamerhud-watch.py` por `spec_from_file_location`, sem `main`;
  erro → False). *(R3, R6, R7, spec §1, §3)*
  - Lê: spec §1, §3, §7 (CA-O2, CA-O5); `hud/gamerhud.py` por trecho (`grep -n "FACE_\|def face_" ` e só esses intervalos, ~1980–2030); `hud/wired/main_screen.py` linhas 104–150 (`Snapshot`); `hud/wired/reactions.py` só a assinatura do `Reactor.__init__` (`grep -n "def __init__" -A8` a partir da linha 284); `hud/wired/reacoes/__init__.py`; `hud/gamerhud-watch.py` linhas 38–90
  - Escreve: `hud/wired/overlay.py` (só as funções acima), `tests/hud/test_overlay_gestos.py`
  - Depende de: O0.1
  - Orçamento: ~45k
  - Pronto: CA-O2 e CA-O5 verdes; `hud_aberto` testado com trava real num `tmp_path` (ocupada/livre).
  - Paralelo: O1.2, O2.1

- [ ] **O1.2 Retrato sem fundo e região de entrada** — `PartsPortrait.fundo: bool = True` (com
  `False`, o `paint` pula a chamada de `_backdrop`; nada mais muda); `regiao_entrada` (spec §1).
  *(R1.1, R2)*
  - Lê: spec §1, §5; `hud/wired/portrait.py` por trecho: `grep -n "_backdrop\|def __init__\|class PartsPortrait"` e as linhas 627–670 e ~1000–1006; `tests/hud/test_wired_portrait.py` só os helpers do topo (como montam a arte de teste)
  - Escreve: `hud/wired/portrait.py` (só o atributo e o `if` do fundo), `hud/wired/overlay.py` (só `regiao_entrada`), `tests/hud/test_overlay_regiao.py`
  - Depende de: O0.1
  - Orçamento: ~40k
  - Pronto: CA-O3 verde; com `fundo=False` os pixels dos cantos do quadro pintado ficam com alfa 0 (arte de teste); `tests/hud/test_wired_portrait.py` inteiro verde sem mudar asserção.
  - Paralelo: O1.1, O2.1

- [ ] **O1.3 Janela e processo** — `hud/condessa_overlay.py`: `OverlayWindow` e `main()` (spec §3,
  §5; design §3): trava `LOCK_FILE`, `setDesktopFileName("condessa-overlay")`, `is_parts` (R1.2),
  `PartsPortrait` com `fundo`/`renderer` do `Config`, `HudBridge` (`stateChanged`, `mouth`, `mood`,
  `turnTag`, `connectedChanged`), `Reactor` com `DETECTORES_OVERLAY`, `NowPlaying` próprio, laço de
  1 Hz, redesenho pelo `portrait.tick`, máscara, mouse (Gestos / `startSystemMove` / menu),
  esconder em jogo / com HUD / 1 h, recaída `MAGI_OVERLAY_XCB=1` (D4 = b). *(R1–R7, R9)*
  - Lê: design §3–§5, spec §3, §5, §7 (CA-O6); assinaturas de `overlay.py`; `hud/hud_bridge.py` linhas 285–380 (classe e sinais); `hud/wired/integration.py` linhas 348–395 (`_react`, `set_state`, `set_mouth`); `hud/gamerhud.py` linhas 2795–2835 (`main`) e 1205–1220 (`mascot_tick`)
  - Escreve: `hud/condessa_overlay.py`, `tests/hud/test_overlay_janela.py`
  - Depende de: O1.1, O1.2
  - Orçamento: ~50k
  - Pronto: CA-O6 verde (offscreen, ponte com socket falso num `tmp_path`, `NowPlaying` com backend falso); estado `speaking` + `mouth` 0.8 muda o `mouth_id` do retrato; segunda instância sai com 0.
  - Paralelo: —

## Fase O2 — Instalação

- [ ] **O2.1 Comando, autostart e regra do KWin** — `hud/system/bin/condessa-overlay`,
  `hud/system/autostart/condessa-overlay.desktop`, `hud/system/applications/condessa-overlay.desktop`
  (spec §6) e um bloco novo no `install_hud` do `install.sh` (render dos três + regra
  `condessa-overlay-rule` do spec §4, escrita **antes** do `dbus-send … reconfigure` que já existe;
  `position` só se a regra for nova). Atualizar `hud/README.md` com 5 linhas (como ligar/desligar,
  mover com o botão do meio, onde fica o `overlay.toml`). *(R4, R8, R10)*
  - Lê: spec §4, §6, §7 (CA-O7, CA-O8); `hud/install.sh` linhas 1–40 e 40–112; `hud/system/bin/gamerhud`; `hud/system/autostart/gamerhud-watch.desktop`; assinatura de `canto_para_posicao`
  - Escreve: `hud/system/bin/condessa-overlay`, `hud/system/autostart/condessa-overlay.desktop`, `hud/system/applications/condessa-overlay.desktop`, `hud/install.sh`, `hud/README.md`, `tests/hud/test_overlay_install.py`
  - Depende de: O0.1
  - Orçamento: ~35k
  - Pronto: CA-O7 e CA-O8 verdes (`HOME` falso, `kwriteconfig6`/`kreadconfig6` trocados por funções de shell que escrevem num arquivo); `bash -n hud/install.sh` limpo.
  - Paralelo: O1.1, O1.2

## Fase O3 — Ao vivo

- [ ] **O3.1 Validação ao vivo** — **precisa do Pedro.** Rodar `hud/install.sh`, sair e entrar
  na sessão. Conferir: aparece em ≤ 10 s; clique fora da silhueta atravessa (5 pontos); arrasto do
  meio move e a posição volta após relogar; não aparece no Alt+Tab; some em jogo; CPU (critério 3,
  `docs/PROXIMOS-PASSOS.md` §7) com o HUD aberto e fechado. Se a máscara não atravessar no Wayland:
  testar `MAGI_OVERLAY_XCB=1` e anotar (D4).
  - Lê: requirements (Critérios), spec §4–§5
  - Escreve: `docs/perf/overlay.md`, `docs/PROXIMOS-PASSOS.md` (§13: a linha do overlay vira "feito" ou lista o que falhou)
  - Depende de: O1.3, O2.1
  - Orçamento: ~20k
  - Pronto: os 5 itens anotados com sim/não e números de CPU.
  - Paralelo: —

- [ ] **O3.2 Semana de uso** — **precisa do Pedro.** 7 dias com o overlay; `reacoes_relatorio.py`
  apontado para `reacoes-overlay.jsonl` (se o script não aceitar caminho, anotar em *Sobras*);
  nota do Pedro e decisão final de D2 (independente / esconde / espelho).
  - Lê: requirements (Critério 5, D2), `hud/tools/reacoes_relatorio.py` só o `argparse`
  - Escreve: `docs/perf/overlay.md`
  - Depende de: O3.1
  - Orçamento: ~15k
  - Pronto: relatório da semana e decisão D2 registrados.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
