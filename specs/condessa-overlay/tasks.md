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

**Decisões do Pedro (2026-10-10)** já aplicadas neste SDD pela O0.1 (requirements, *Decisões*):
D1/D4/D5 confirmadas; **D2** com HUD aberto o overlay se esconde; **D3** em jogo vai para o monitor
oposto (um monitor só → some e volta depois); **D6** canto superior direito, margem 24 px. A
decisão D2/D3 é a função pura `decidir_lugar` (feita na O0.1); as tarefas só a usam.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
O0.1 ─┬─ O1.1 ─┐
      ├─ O1.2 ─┴─ O1.3 ─┐
      └─ O2.1 ──────────┴─ O3.1 (ao vivo, Pedro) ── O3.2 (semana)
```

---

## Fase O0 — Contratos

- [x] **O0.1 Contratos e esqueleto** — aplica as decisões de 2026-10-10 no SDD; `hud/wired/overlay.py`
  com as constantes de caminho, `Config` (`ler`/`gravar` completos, padrões D2/D3/D6),
  `canto_para_posicao` e `Lugar`/`decidir_lugar` (D2/D3) completos, e **stubs** com assinatura final e
  docstring da tarefa dona: `Gestos`, `regiao_entrada`, `snapshot_leve`, `hud_aberto`,
  `jogo_aberto`, `DETECTORES_OVERLAY = ()`. *(R7, R7.1, R9, spec §1–§2)*
  - Lê: design §2, §4, spec §1–§3, requirements R7, R9 e Decisões; `specs/DECISOES-2026-10-10.md`
  - Escreve: SDD do overlay, `hud/wired/overlay.py`, `tests/hud/test_overlay_config.py`, `tests/hud/conftest.py` (isola os caminhos do overlay)
  - Depende de: —
  - Orçamento: ~25k
  - Pronto: CA-O1, CA-O4 e CA-O9 verdes; `ruff` limpo; o módulo importa sem `QApplication` (só `QtCore`/`QtGui` tipos).
  - Paralelo: —

## Fase O1 — Peças

- [x] **O1.1 Gestos, snapshot leve e reações** — `Gestos` (spec §1, constantes copiadas do
  `gamerhud`), `snapshot_leve`, `DETECTORES_OVERLAY`, `hud_aberto` (flock não bloqueante, solta na
  hora; é a entrada `hud` do `decidir_lugar`, D2), `jogo_aberto` (entrada `gaming`, D3) (carrega `hud/gamerhud-watch.py` por `spec_from_file_location`, sem `main`;
  erro → False). *(R3, R6, R7, spec §1, §3)*
  - Lê: spec §1, §3, §7 (CA-O2, CA-O5); `hud/gamerhud.py` por trecho (`grep -n "FACE_\|def face_" ` e só esses intervalos, ~1980–2030); `hud/wired/main_screen.py` linhas 104–150 (`Snapshot`); `hud/wired/reactions.py` só a assinatura do `Reactor.__init__` (`grep -n "def __init__" -A8` a partir da linha 284); `hud/wired/reacoes/__init__.py`; `hud/gamerhud-watch.py` linhas 38–90
  - Escreve: `hud/wired/overlay.py` (só os corpos dos stubs acima; não mexe em `Config`/`decidir_lugar`), `tests/hud/test_overlay_gestos.py`
  - Depende de: O0.1
  - Orçamento: ~45k
  - Pronto: CA-O2 e CA-O5 verdes; `hud_aberto` testado com trava real num `tmp_path` (ocupada/livre).
  - Paralelo: O1.2, O2.1

- [x] **O1.2 Retrato sem fundo e região de entrada** — `PartsPortrait.fundo: bool = True` (com
  `False`, o `paint` pula a chamada de `_backdrop`; nada mais muda); `regiao_entrada` (spec §1).
  *(R1.1, R2)*
  - Lê: spec §1, §5; `hud/wired/portrait.py` por trecho: `grep -n "_backdrop\|def __init__\|class PartsPortrait"` e as linhas 627–670 e ~1000–1006; `tests/hud/test_wired_portrait.py` só os helpers do topo (como montam a arte de teste)
  - Escreve: `hud/wired/portrait.py` (só o atributo e o `if` do fundo), `hud/wired/overlay.py` (só o corpo do stub `regiao_entrada`), `tests/hud/test_overlay_regiao.py`
  - Depende de: O0.1
  - Orçamento: ~40k
  - Pronto: CA-O3 verde; com `fundo=False` os pixels dos cantos do quadro pintado ficam com alfa 0 (arte de teste); `tests/hud/test_wired_portrait.py` inteiro verde sem mudar asserção.
  - Paralelo: O1.1, O2.1

- [x] **O1.3 Janela e processo** — `hud/condessa_overlay.py`: `OverlayWindow` e `main()` (spec §3,
  §5; design §3): trava `LOCK_FILE`, `setDesktopFileName("condessa-overlay")`, `is_parts` (R1.2),
  `PartsPortrait` com `fundo`/`renderer` do `Config`, `HudBridge` (`stateChanged`, `mouth`, `mood`,
  `turnTag`, `connectedChanged`), `Reactor` com `DETECTORES_OVERLAY`, `NowPlaying` próprio, laço de
  1 Hz, redesenho pelo `portrait.tick`, máscara, mouse (Gestos / `startSystemMove` / menu),
  a cada 5 s `decidir_lugar(cfg, telas, principal, jogo_aberto(), hud_aberto())` e **só aplica** o
  `Lugar` (D2: HUD aberto → esconde; D3: monitor oposto via `setScreen` + `move` em
  `canto_para_posicao`, um monitor só → esconde; guarda a posição antes de sair e volta a ela),
  esconder 1 h, recaída `MAGI_OVERLAY_XCB=1` (D4). *(R1–R7.1, R9)*
  - Lê: design §3–§5, spec §1 (`decidir_lugar`), §3, §5, §7 (CA-O6); assinaturas de `overlay.py`; `hud/hud_bridge.py` linhas 285–380 (classe e sinais); `hud/wired/integration.py` linhas 348–395 (`_react`, `set_state`, `set_mouth`); `hud/gamerhud.py` linhas 2795–2835 (`main`) e 1205–1220 (`mascot_tick`)
  - Escreve: `hud/condessa_overlay.py`, `tests/hud/test_overlay_janela.py`
  - Depende de: O1.1, O1.2
  - Orçamento: ~50k
  - Pronto: CA-O6 verde (offscreen, ponte com socket falso num `tmp_path`, `NowPlaying` com backend falso); estado `speaking` + `mouth` 0.8 muda o `mouth_id` do retrato; segunda instância sai com 0; com `hud_aberto`/`jogo_aberto` trocados por falsos: `Lugar(False)` esconde, `Lugar(True)` mostra de novo na posição guardada.
  - Paralelo: —

## Fase O2 — Instalação

- [x] **O2.1 Comando, autostart e regra do KWin** — `hud/system/bin/condessa-overlay`,
  `hud/system/autostart/condessa-overlay.desktop`, `hud/system/applications/condessa-overlay.desktop`
  (spec §6) e um bloco novo no `install_hud` do `install.sh` (render dos três + regra
  `condessa-overlay-rule` do spec §4, escrita **antes** do `dbus-send … reconfigure` que já existe;
  `position` só se a regra for nova). Atualizar `hud/README.md` com 5 linhas (como ligar/desligar,
  mover com o botão do meio, onde fica o `overlay.toml`). *(R4, R8, R10)*
  - Posição inicial da regra: `canto_para_posicao(Config(), geometria do monitor principal)` = canto superior direito, 24 px (D6).
  - Lê: spec §4, §6, §7 (CA-O7, CA-O8); `hud/install.sh` linhas 1–40 e 40–112; `hud/system/bin/gamerhud`; `hud/system/autostart/gamerhud-watch.desktop`; assinatura de `canto_para_posicao`
  - Escreve: `hud/system/bin/condessa-overlay`, `hud/system/autostart/condessa-overlay.desktop`, `hud/system/applications/condessa-overlay.desktop`, `hud/install.sh`, `hud/README.md`, `tests/hud/test_overlay_install.py`
  - Depende de: O0.1
  - Orçamento: ~35k
  - Pronto: CA-O7 e CA-O8 verdes (`HOME` falso, `kwriteconfig6`/`kreadconfig6` trocados por funções de shell que escrevem num arquivo); `bash -n hud/install.sh` limpo.
  - Paralelo: O1.1, O1.2

## Fase O3 — Ao vivo

- [ ] **O3.1 Validação ao vivo** — **precisa do Pedro.** Rodar `hud/install.sh`, sair e entrar
  na sessão. Conferir: aparece em ≤ 10 s; clique fora da silhueta atravessa (5 pontos); arrasto do
  meio move e a posição volta após relogar; não aparece no Alt+Tab; nasce no canto superior
  direito (D6); some com o HUD aberto e volta ao fechá-lo (D2); em jogo vai para o outro monitor
  e volta depois (D3 — se o Wayland não deixar trocar de monitor, anotar); CPU (critério 3,
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
  nota do Pedro e confirmação de D2 (esconde com o HUD) ou troca por espelho.
  - Lê: requirements (Critério 5, D2), `hud/tools/reacoes_relatorio.py` só o `argparse`
  - Escreve: `docs/perf/overlay.md`
  - Depende de: O3.1
  - Orçamento: ~15k
  - Pronto: relatório da semana e decisão D2 registrados.
  - Paralelo: —

## Fase O4 — Ajustes ao vivo

- [x] **O4.1 Card com moldura e arraste pelo botão esquerdo** — feedback do Pedro em 2026-10-12
  ("não gostei dela flutuando; ela tinha que ter um quadradinho pra ela" / "não consigo arrastar
  ela"). `Config.estilo = "card" | "solto"` (padrão `card`, validado no `ler`; no card
  `fundo_efetivo` = True). Card no mesmo quadro do `tamanho`: painel chanfrado + scanlines, borda e
  cantos marcados na cor do humor (`Reactor.medidor`, recaída `#b392f0`), retrato recortado de
  cantos arredondados, placa `CONDESSA` + estado curto; camadas em cache (refeitas só quando
  tamanho/humor/estado mudam). Máscara = retângulo; esquerdo arrastado → `startSystemMove` dentro
  do move (recusado → move manual); meio igual; posição em `POS_FILE` ao soltar (ou quando a janela
  para), restaurada no `main()` antes do canto D6. D5 revista. *(R1.1, R2, R4, R9)*
  - Lê: `hud/condessa_overlay.py`, `hud/wired/overlay.py` (Config, Gestos), `hud/wired/kit.py` (painel), `hud/wired/theme.py`, `hud/wired/reacoes/estado.py` (`COR_FAIXA`)
  - Escreve: `hud/condessa_overlay.py`, `hud/wired/overlay.py`, `tests/hud/test_overlay_janela.py`, `tests/hud/conftest.py`, SDD, `hud/README.md`
  - Depende de: O1.3
  - Orçamento: ~70k
  - Pronto: `uv run pytest -q tests/hud` verde; card com cantos na cor da borda e texto na placa; `solto` com as asserções antigas; máscara = retângulo; esquerdo chama `startSystemMove`; posição gravada e restaurada.
  - Paralelo: —

- [x] **O4.3 Atalhos para alternar HUD e overlay** — pedido do Pedro em 2026-10-12 ("Win+M já
  abre o HUD se estiver fechado; outro atalho fecha o HUD e abre o overlay; de novo, liga/desliga
  o overlay"). Lógica pura em `hud/alternar.py` (sem Qt): `decidir_meta_m(hud)` e
  `decidir_alternar(hud, overlay)`; HUD aberto = trava `hud.lock` presa ou processo vivo; ações
  pelos comandos do menu (`gamerhud` fecha por SIGTERM + `--restore`; `condessa-overlay` alterna).
  **Meta+M** (`magi-view.py`): HUD fechado → abre; aberto → alterna a ociosidade (como antes).
  **Meta+O** (`condessa-alternar`): HUD aberto → fecha o HUD e liga o overlay (se o processo já
  roda, escondido pela D2, não liga outro); HUD fechado → liga/desliga o overlay. Atalho por
  `X-KDE-Shortcuts=Meta+O` em `condessa-alternar.desktop` (sem D-Bus novo); Meta+O livre no
  Plasma 6 e no `kglobalshortcutsrc` do Pedro. *(D2)*
  - Lê: `hud/magi-view.py`, `hud/system/bin/*`, `hud/install.sh` (bloco do HUD), `hud/wired/overlay.py` (`hud_aberto`, só leitura)
  - Escreve: `hud/alternar.py`, `hud/magi-view.py`, `hud/system/bin/condessa-alternar`, `hud/system/applications/condessa-alternar.desktop`, `hud/install.sh`, `hud/README.md`, `tests/hud/test_alternar.py`, SDD
  - Depende de: O4.1
  - Orçamento: ~40k
  - Pronto: `uv run pytest -q tests/hud` verde; decisões nos 4 casos + Meta+M nos 2; nenhum `dbus-send` novo no `install.sh`.
  - Paralelo: O4.2 (arquivos separados)

- [x] **O4.2 Overlay em XWayland com encaixe em 8 pontos por tela** — feedback do Pedro em
  2026-10-12 ("seria bom setorizar os cantos da tela pra ela grudar nos pontos certos, não ficar em
  qualquer lugar pra ter que acertar certinho" / "o overlay demorou para fechar quando abri o
  HUD"). D4 revista: padrão `xcb` (`QT_QPA_PLATFORM="xcb;wayland"` antes do `QApplication`);
  `MAGI_OVERLAY_WAYLAND=1` ou `plataforma = "wayland"` volta ao nativo (O4.1, sem encaixe). Puras:
  `ANCORAS` (4 cantos + meio das bordas), `ponto_ancora`, `encaixar` (área útil, qualquer monitor,
  `ancoras` limita), `gravar_ancora`/`ler_ancora` (converte o `{x, y, tela}` antigo). Janela: arraste
  do próprio app no xcb, ao soltar anima ~180 ms até a âncora e grava; restaura no `main()` (tela
  ausente → principal, padrão D6 `sup_dir`); D3 na mesma âncora do monitor oposto; menu
  "Grudar em ▸". HUD: `checar_hud` no laço de 1 Hz + `QFileSystemWatcher` na trava (esconde/volta
  em ≤ 1 s; `jogo_aberto` segue nos 5 s). *(R2, R4, D3, D4, D6)*
  - Lê: `hud/condessa_overlay.py`, `hud/wired/overlay.py`, `hud/install.sh`
  - Escreve: `hud/condessa_overlay.py`, `hud/wired/overlay.py`, `tests/hud/test_overlay_janela.py`, SDD, `hud/README.md`
  - Depende de: O4.1
  - Orçamento: ~70k
  - Pronto: `uv run pytest -q tests/hud` verde; `encaixar` com 1 e 2 telas e painel; soltar → âncora exata; memória converte o formato antigo; D3 espelhado; "Grudar em" move; HUD visto a 1 Hz.
  - Paralelo: —

- [x] **O4.4 Toque do overlay igual ao do HUD** — sobra da O1.1: o `Gestos` usava `LONG_S = 0,6`
  e `DRAG_PX = 18` com comentário "copiados" errado (o HUD usa `FACE_LONG_S = 0,8` e `FACE_DRAG =
  40` px na base 1920 sobre um rosto de 272 px). Agora `LONG_S = 0,8` e `DBL_MS = 250` iguais ao
  HUD; o arraste, que no card move a janela (O4.1/O4.2), é em px reais pelo lado do card:
  `limiar_arraste(lado) = max(12, round(0,075 × lado))` (metade da proporção do HUD, 40/272 ≈ 0,147,
  para não ficar duro num card pequeno; piso de 12 px contra tremida do clique) → 120 px: 12 ·
  220 px: 16 · 480 px: 36. `Gestos(..., lado=220)` e `redimensionar(lado)`; `DRAG_PX = 16` fica
  como o valor no lado padrão. *(spec §1, CA-O2)*
  - Lê: `hud/wired/overlay.py` (`Gestos`), `hud/gamerhud.py` (`FACE_*`, por grep), `tests/hud/test_overlay_gestos.py`
  - Escreve: `hud/wired/overlay.py` (só `Gestos`), `tests/hud/test_overlay_gestos.py`, SDD
  - Depende de: O4.1, O4.2
  - Orçamento: ~25k
  - Pronto: `uv run pytest -q tests/hud` verde; 0,7 s é simples (não longo); limiar 12/16/36 nos lados 120/220/480.
  - Paralelo: —

- [x] **O4.5 Limiar de arraste da janela pelo tamanho do card** — sobra da O4.4: a janela criava
  `Gestos` sem `lado` (valia 16 px mesmo com outro `tamanho`). Agora `Gestos(..., lado=cfg.tamanho)`
  e `mudar_tamanho` (menu Tamanho ±) chama `gestos.redimensionar(cfg.tamanho)`. As chaves
  `[overlay] toque_longo_s`/`arraste_px` ficaram de fora (ver *Sobras*). *(spec §1, CA-O2)*
  - Lê: `hud/condessa_overlay.py`, `hud/wired/overlay.py` (`Gestos`), `tests/hud/test_overlay_janela.py`
  - Escreve: `hud/condessa_overlay.py`, `tests/hud/test_overlay_janela.py`, SDD
  - Depende de: O4.4
  - Orçamento: ~15k
  - Pronto: `uv run pytest -q tests/hud` verde; Tamanho ± leva o limiar a 36 px (480) e 12 px (120).
  - Paralelo: —

- [x] **O4.6 Padrão de processo casa `/usr/bin/python3`** — bug ao vivo: o autostart sobe o overlay
  como `/usr/bin/python3 …/condessa_overlay.py` e o padrão `^python3 .*/condessa_overlay\.py$` não
  casava; `condessa-overlay` e Meta+O não viam nem fechavam essa instância. Padrão novo (ERE do
  pgrep) `^([^ ]*/)?python3(\.[0-9]+)? [^ ]*/<script>\.py$` no overlay e no HUD (`alternar.py`,
  `bin/condessa-overlay`, `bin/gamerhud` pela paridade testada); não casa o próprio `pgrep`/`bash -c`.
  - Lê: `hud/alternar.py`, `hud/system/bin/*`, `hud/system/autostart/condessa-overlay.desktop`
  - Escreve: `hud/alternar.py`, `hud/system/bin/condessa-overlay`, `hud/system/bin/gamerhud`,
    `tests/hud/test_alternar.py`, SDD
  - Depende de: O4.3
  - Orçamento: ~15k
  - Pronto: `uv run pytest -q tests/hud/test_alternar.py` verde com as linhas de comando reais.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)

- **O0.1:** `decidir_lugar` (D2/D3) ficou pronto na O0.1 (era pura e pequena); O1.1 só faz as
  entradas `hud_aberto`/`jogo_aberto` e O1.3 só aplica. O1.1 e O1.2 tocam o mesmo
  `hud/wired/overlay.py`, mas cada uma só o corpo do seu stub (trechos separados; merge sem
  conflito esperado). Risco aberto para O1.3/O3.1: no Wayland o app pode não conseguir trocar de
  monitor (`setScreen`/`move`); se não der, esconder em jogo (como com um monitor só) e anotar.
  `tela_jogo` não é descoberta (exigiria D-Bus do KWin): padrão = monitor principal.
- **O2.1:** `install.sh --overlay-rule` só escreve a regra (usado nos testes). A posição inicial
  sai de `canto_para_posicao(Config(), primaryScreen())` por `python3` + `QGuiApplication`
  (`MAGI_OVERLAY_TELA="x,y,w,h"` pula o Qt; falha → 1920×1080). Nenhuma chamada D-Bus nova: o bloco
  do overlay só escreve o `kwinrulesrc` antes do `dbus-send … reconfigure` que já existia; a regra
  vale com certeza no próximo login (O3.1: relogar depois do install). O `dbus-send` ao KWin e o
  `doRegister`/`setShortcut` do KGlobalAccel antigos do `install_hud` continuam lá (fora do pacote;
  avaliar se tiram, dado o risco de derrubar a sessão). O teste de `hud/condessa_overlay.py` no
  CA-O7 só roda quando o arquivo existir (O1.3).
- **O1.1:** `Gestos` usa os valores do spec (`LONG_S = 0,6`, `DRAG_PX = 18` px da janela), não os
  do `gamerhud` (`FACE_LONG_S = 0,8`, `FACE_DRAG = 40` px base 1920): o comentário "copiados" do
  stub não bate; ajustar se o Pedro quiser o mesmo toque do HUD. Longo vale no `release` (como no
  HUD). `press` depois da espera sem `tick` solta o simples antes (não vira duplo). `hud_aberto`
  não cria a trava (sem arquivo = `False`). `jogo_aberto` usa o helper `_carregar_watch` (cache do
  módulo; os testes trocam ele) e o import dos 4 detectores fica no fim do `overlay.py` (E402).
- **O1.3:** `OverlayWindow` recebe tudo injetado (portrait, ponte, `Reactor`, `NowPlaying`, relógio,
  `jogo`/`hud`); `main()` só monta (sem teste de ponta a ponta: o `NowPlaying` real abriria o
  MPRIS). Ordem do `main`: `ligado` → trava → `is_parts` → `setDesktopFileName` → janela. "Alto"
  do `Gestos` = `y < 0,32 × altura` (`ROSTO_Y`, aproximado; o retrato não expõe o centro do rosto).
  Posição guardada só ao sair do `normal` (`_volta`); ao voltar, `setScreen` + `move` nela (no
  Wayland o `move` pode não valer: O3.1 mede). O offscreen tem um monitor só: o `jogo_oposto` com
  2 monitores reais só foi testado via `aplicar(Lugar(..., "jogo_oposto"))`. Fechar emite
  `fechada` (→ `app.quit`); SIGTERM/SIGINT fecham a janela (timer de 500 ms para o Python ver o
  sinal). "Esconder 1 h" ganha do laço de 5 s até o `QTimer` vencer.
- **O4.1:** por que o botão do meio não moveu não deu para reproduzir aqui (offscreen, sem KWin):
  o `startSystemMove` já era chamado dentro do press; suspeitas: a máscara recortada (o clique
  caía fora da silhueta) ou o compositor recusar (`startSystemMove` devolve `False`, antes
  ignorado). Agora: no card a máscara é o retângulo todo, o retorno é checado e, recusado, a
  janela anda na mão com o mouse (vale em X11/XWayland; no Wayland nativo o `move` do app não
  vale). No Wayland nativo o app não sabe a própria posição: o `overlay-pos.json` só é gravado fora
  dele (o KWin lembra pela regra depois do relogin). O arrasto do card não vira reação `arrasto`
  (no `solto` continua virando).
- **O4.3:** o `X-KDE-Shortcuts` de um `.desktop` em `~/.local/share/applications` costuma ser lido
  pelo kglobalaccel só no próximo login (depois do `kbuildsycoca6`); se não pegar, o caminho manual
  está no `hud/README.md`. `trava_ocupada` repete o `wired.overlay.hud_aberto` (sem importar o Qt:
  roda a cada tecla). Corrida rara: o HUD morrer entre o teste e o `gamerhud` (que alterna) o
  reabriria; aceito.
- **O4.2:** a fábrica dos testes ganhou `xcb=` (padrão `False` = o Wayland nativo do O4.1, para as
  asserções antigas valerem sem mudança); o `OverlayWindow` também tem `xcb=False` por padrão e
  quem liga é o `main()` pelo `platformName()`. A tela salva é o `QScreen.name()` (não o serial).
  A regra do KWin (posição "Lembrar") continua e pode, no xcb, pôr a janela onde lembrava no
  primeiro `show`: a âncora é reafirmada logo depois (`_t_reafirma`). `x`/`y` do toml ficam
  obsoletos (lidos e ignorados). Soltar a trava do HUD não gera evento de arquivo (só abrir, que
  trunca): a volta vale pelo laço de 1 Hz. Risco do XWayland: com escala fracionária no KDE o
  retrato pode ficar borrado (o Plasma escala o XWayland) — conferir ao vivo.
- **O4.4:** a janela (`hud/condessa_overlay.py`, fora do Escreve) ainda cria `Gestos` sem `lado`,
  então vale o padrão de 220 px (16 px) mesmo com outro `tamanho`. Falta, numa tarefa da janela:
  `Gestos(reactor.on_click, self._hover, lado=cfg.tamanho)` e `self.gestos.redimensionar(...)` no
  `mudar_tamanho`. Chaves em `[overlay]` (`toque_longo_s`, `arraste_px`) não foram criadas: só
  valeriam com essa ligação; fica para a mesma tarefa, se o Pedro quiser ajustar na mão.
- **O4.5:** `toque_longo_s`/`arraste_px` em `[overlay]` não criadas: o `Gestos` não aceita
  `LONG_S` por instância nem limiar fixo; exigiriam mudar o `Gestos` (fora do Escreve). Só vale se o
  Pedro quiser ajustar na mão.
