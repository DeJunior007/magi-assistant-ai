# Tarefas — Reações da Condessa

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `R`, acordo do Conselho por `acordo §` (`persona/conselho/atas/2026-10-08-reacoes/acordo.md`).
2. **Orçamento planejado ≤ 60k tokens**; o resto da janela de 128k é margem. Perto de 100k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use `hud/wired/reacoes/contratos.py` e as assinaturas dos stubs; não
   leia o código de outras tarefas.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `hud/gamerhud.py`, `hud/wired/portrait.py`, `hud/wired/integration.py`, `hud/wired/data.py`.
6. **Testes curtos:** `uv run pytest -q -x tests/hud/<arquivo>` e `uv run ruff check <seus arquivos>`.
   Relógio e `rng` sempre injetados; nada de `sleep` real.
7. **Nada ao vivo nos testes:** sem `wpctl`, `dbus-monitor`, `dnf`, `git` do repositório real,
   `claude` ou Konsole de verdade (subprocesso é injetado/falso). Nunca `qdbus`/`gdbus` para
   KGlobalAccel/KWin.
8. **Uma tarefa = um commit** com o ID (`R1.2: detectores de música`), na branch `reacoes/<ID>`;
   merge no `main` pelo orquestrador.
9. **Reação condicionada não entra em `catalogo.ATIVAS`** sem o sinal dela pronto (R8).

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~2,5k,
`design.md` ~2,5k, `spec.md` ~4k, `acordo.md` ~6k, `reacoes.md` ~5k, `reactions.py` ~7k.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
R0.1 ─┬─ R0.2 ─┐
      ├─ R0.3  │
      └─ R0.4 ─┴─ R0.5 ─┬─ R1.1 ┬─ R1.2 ┬─ R1.3 ┬─ R1.4 ┬─ R1.5 ── (onda 1 pronta: 87 reações)
                        │       (paralelas entre si)
                        ├─ R2.A (dep R1.5)   ├─ R2.B ── R2.F
                        ├─ R2.C  ├─ R2.D  ├─ R2.E  ├─ R2.G      (paralelas entre si)
                        └─ R3.1 (arte, Pedro) ……… R3.2 (validação, no fim)
```

---

## Fase R0 — Motor

- [x] **R0.1 Contratos e esqueleto** — pacote `hud/wired/reacoes/` com `contratos.py` (spec §2:
  `EFEITO`, `Passo`, `Classe`, `Def`, `Disparo`), `__init__.py` com `DETECTORES` já listando todos
  os módulos do spec §5, e **stubs** de `det_tempo`, `det_musica`, `det_sistema`, `det_claude`,
  `det_entrada`, `det_conversa`, `det_volume`, `det_notif`, `det_extras`, `passivas`, `humor`,
  `atividade`, `governador`, `registro`, `catalogo` (assinaturas finais, corpo vazio). `Reaction`
  ganha `efeitos` e `corpo` (spec §2). *(R1, R5)*
  - Lê: design §2–§4, spec §1–§2, `hud/wired/reactions.py` linhas 1–95 (cabeçalho, `Reaction`, `REACTIONS`)
  - Escreve: `hud/wired/reacoes/*.py`, `hud/wired/reactions.py` (só a dataclass `Reaction`), `tests/hud/test_reacoes_contratos.py`
  - Depende de: —
  - Orçamento: ~35k
  - Pronto: testes dos contratos e todos de `tests/hud/test_wired_reactions.py` verdes; `ruff` limpo; cada stub tem docstring com a tarefa dona.
  - Paralelo: —

- [x] **R0.2 Governador e registro** — `governador.escolher(disparos, agora, ctx) -> Def|None` com
  todas as regras do spec §3 (cotas, cooldown, prioridade, fila, bloqueios, blush, lágrima, Ado,
  desligadas do Pedro) e `aplicar_bloqueios(def, ctx) -> tuple[Passo]` (C8/C11 → C9, tira `tear`
  fora de hora). `registro.gravar(...)` em `~/.local/state/magi/reacoes.jsonl` com giro de 5 MB
  (caminho injetável). *(R2, R3, R10, R11)*
  - Lê: `hud/wired/reacoes/contratos.py`, spec §3, requirements R2–R3, R10–R11
  - Escreve: `hud/wired/reacoes/governador.py`, `hud/wired/reacoes/registro.py`, `tests/hud/test_reacoes_governador.py`
  - Depende de: R0.1
  - Orçamento: ~50k
  - Pronto: CA-03 (24 h simuladas, relógio falso) e CA-07 verdes; um teste por linha da tabela do spec §3.
  - Paralelo: R0.3, R0.4

- [x] **R0.3 Retrato: efeitos, corpo e madrugada** — efeitos `zz`, `tear`, `vein`, `sparkle` no
  `_reaction_effect` (até 3 por passo, de `Reaction.efeitos`); extras `sway`, `tails`, `fone_on/off`,
  `braco:P*`, `iris:<olhar>` (asset ausente → ignora); `_reacting()` aceita `sleeping` de noite
  quando a reação vem marcada noturna (campo `noturna` na `Reaction`). *(R1.1, R6, design §6)*
  - Lê: design §6, spec §2, `hud/wired/portrait.py` por trecho: `grep -n "_reacting\|_resting\|_reaction_effect\|r.bob\|live:" ` e só esses intervalos; `docs/design/CONDESSA-RETRATO.md` §Montagem
  - Escreve: `hud/wired/portrait.py`, `hud/wired/reactions.py` (só o campo `noturna` em `Reaction`), `tests/hud/test_wired_portrait.py` (casos novos)
  - Depende de: R0.1
  - Orçamento: ~60k
  - Pronto: CA-06 verde; testes antigos do retrato sem mudar asserção; cada efeito novo desenha sem erro com e sem assets.
  - Paralelo: R0.2, R0.4

- [x] **R0.4 Catálogo** — as 110 `Def` em `catalogo.py`: 90 da planilha (49 e 68 marcadas
  `substituida=True`, fora de `ATIVAS`) e I1–I20, com passos/ms (de `reacoes.md` e acordo §2),
  classes (spec §3), `sinal` (spec §5), `cooldown_s`. As de variante (spec §1) entram como
  variante da chave atual, não `Def` nova. `ATIVAS` = sem sinal pendente. Script de checagem:
  conta 110 na lista e ≥ 80 em `ATIVAS`. *(R1, R5, R8)*
  - Lê: `hud/wired/reacoes/contratos.py`, spec §1, §3, §5, `persona/conselho/atas/2026-10-08-reacoes/reacoes.md`, acordo §1–§2
  - Escreve: `hud/wired/reacoes/catalogo.py`, `tests/hud/test_reacoes_catalogo.py`
  - Depende de: R0.1
  - Orçamento: ~60k
  - Pronto: CA-05 verde; teste confere 110 itens, 87 em `ATIVAS`, toda chave única, 1–4 passos, IDs de asset válidos (B1–B17, C1–C14, F1–F7, V1–V6, O1, D1–D9, E2–E3, P2–P13).
  - Paralelo: R0.2, R0.3

- [x] **R0.5 Ligação no Reactor** — `Reactor.observe` roda `DETECTORES` + passivas (a cada 10 s) →
  governador → toca a sequência; `active(now)` devolve o passo atual como `Reaction` de 1 rosto
  (com `efeitos`, `corpo`, `noturna`); `_music`/`_decide` passam a emitir `Disparo` em vez de
  `fire` direto; `ctx` montado uma vez por tick (design §4). Teste de desempenho CA-08. *(R1, R2, design §4)*
  - Lê: design §3–§4, spec §2–§3, `hud/wired/reacoes/{contratos,governador,catalogo,__init__}.py` (só assinaturas), `hud/wired/reactions.py` inteiro, `hud/wired/integration.py` linhas 300–330
  - Escreve: `hud/wired/reactions.py`, `tests/hud/test_wired_reactions.py` (casos novos), `tests/hud/test_reacoes_tick.py`
  - Depende de: R0.2, R0.3, R0.4
  - Orçamento: ~60k
  - Pronto: CA-01, CA-02, CA-08 verdes.
  - Paralelo: —

## Fase R1 — Detectores com sinais que já existem (onda 1: 87 reações)

Todas dependem de **R0.5** e rodam **em paralelo entre si** (cada uma só no próprio módulo).

- [x] **R1.1 Passivas e humor** — `humor.fatores(ctx)` (12 fatores, acordo §4) e
  `passivas.sortear(ctx, agora, rng)` para 1–4, 6–14, 16, 21–23 (spec §5); respirar/piscar
  contínuos não passam pelo sorteio. *(R4)*
  - Lê: `contratos.py`, spec §4–§5, acordo §1 (linhas 1–23) e §4
  - Escreve: `hud/wired/reacoes/humor.py`, `hud/wired/reacoes/passivas.py`, `tests/hud/test_reacoes_passivas.py`
  - Orçamento: ~50k
  - Pronto: CA-04 para estas linhas; 10 000 sorteios com fator "Pedro mal" nunca escolhem 8 ou 16; "Favorita do Dia" nunca favorece 12.

- [x] **R1.2 Música** — `det_musica.detectar` para 24–30, 32, 33, 78, 81, 83, 85, 89, I3, I7–I15
  (spec §5; listas `[listas]` do gosto; contagem de plays/pulos do `Reactor` via `ctx`). 33, I3,
  I13, I12 como variantes (spec §1).
  - Lê: `contratos.py`, spec §1, §5, acordo §1 (24–33, 78–89) e §2 (I3, I7–I15), `persona/condessa-gosto.toml` (`[listas]`, `[contexto]`), `hud/wired/reactions.py` linhas 136–272 (`Taste`, `Verdict`)
  - Escreve: `hud/wired/reacoes/det_musica.py`, `tests/hud/test_reacoes_musica.py`
  - Orçamento: ~60k
  - Pronto: CA-04 para estas linhas; Ado nunca recebe blush/love; 26 nunca dispara antes de 60 s.

- [x] **R1.3 Sistema** — `det_sistema.detectar` para 34–42 (sem 43), 44, 45, 48, 80, 84, I4, I5,
  I6, com histerese (hot 85 °C / alívio < 78 °C; rede: sem `net_ip` ≥ 10 s).
  - Lê: `contratos.py`, spec §1, §3, §5, acordo §1 (34–48, 80, 84) e §2 (I4–I6), `hud/wired/main_screen.py` linhas 100–160 (`Snapshot`)
  - Escreve: `hud/wired/reacoes/det_sistema.py`, `tests/hud/test_reacoes_sistema.py`
  - Orçamento: ~50k
  - Pronto: CA-04 para estas linhas; oscilação 84↔86 °C por 10 min gera no máximo 1 `hot`.

- [x] **R1.4 Tempo, tédio e atividade** — `atividade.py` (evento real, último uso, primeiro do dia;
  arquivo de estado injetável) e `det_tempo.detectar` para 17–20, 57–62, I1, I2, I16, I17, I19
  (data do 1º commit lida uma vez, com `git` injetado).
  - Lê: `contratos.py`, spec §3, §5 (parágrafo "Evento real"), acordo §1 (17–20, 57–63) e §2 (I1, I2, I16, I17, I19)
  - Escreve: `hud/wired/reacoes/atividade.py`, `hud/wired/reacoes/det_tempo.py`, `tests/hud/test_reacoes_tempo.py`
  - Orçamento: ~55k
  - Pronto: CA-04 para estas linhas; 18 nunca com jogo/Claude/música nota ≥ 1; 20/57/62 tocam mesmo com cota cheia (teste com governador real).

- [ ] **R1.5 Claude Code, entrada e conversa existente** — `GitStatus` ganha `head` (hash curto);
  `det_claude` para 52, 53, 56, 75, 82, 90; `det_entrada` para 5, 64, 66; `det_conversa` para
  71–73 (listas `noticia_*`), 79 (humor ≤ 1), I18 (Magui `falando` → parada).
  - Lê: `contratos.py`, spec §5, acordo §1 (5, 52–56, 64, 66, 71–79, 82, 90) e §2 (I18), `hud/wired/data.py` por trecho (`class ClaudeView`, `class GitStatus`)
  - Escreve: `hud/wired/data.py` (só `GitStatus`), `hud/wired/reacoes/det_claude.py`, `hud/wired/reacoes/det_entrada.py`, `hud/wired/reacoes/det_conversa.py`, `tests/hud/test_reacoes_claude.py`, `tests/hud/test_reacoes_entrada_conversa.py`
  - Orçamento: ~60k
  - Pronto: CA-04 para estas linhas; 72/73 nunca com palavra de morte/desastre seguida de riso.

> **Marco onda 1:** depois de R1.1–R1.5, rodar `tests/hud` inteiro e o teste de contagem: ≥ 87
> reações em `ATIVAS` disparando. Atualizar `docs/PROXIMOS-PASSOS.md` §7.

## Fase R2 — Sinais novos (cada um destrava reações condicionadas)

Dependem de **R0.5** (e do detector dono, quando indicado); **paralelas entre si**. Cada uma move
suas reações para `ATIVAS` editando **só** a linha `sinal=` delas em `catalogo.py` (conflito de
merge trivial, resolvido pelo orquestrador).

- [ ] **R2.A Retrato clicável e hover** — mouse tracking na área do rosto; gestos do spec §6 A;
  decisão D1 (padrão: PTT espera 250 ms); `Reactor.on_hover`; reações 15, 65, 67, 69, 70, 77 em
  `det_entrada`; 64 passa a valer também no retrato.
  - Lê: spec §6 A, requirements D1, `hud/gamerhud.py` por trecho (`mousePressEvent`…`wired_click`, ~1885–1935, e `clickable`), `hud/wired/main_screen.py` (`mascot_tick`), `det_entrada.py`
  - Escreve: `hud/gamerhud.py`, `hud/wired/integration.py` (só `on_hover`), `hud/wired/reactions.py` (só `on_hover`), `hud/wired/reacoes/det_entrada.py`, `catalogo.py` (linhas `sinal=`), `tests/hud/test_reacoes_retrato.py`
  - Depende de: R0.5, R1.5
  - Orçamento: ~60k
  - Pronto: teste com eventos Qt sintéticos (`QTest`) dispara cada gesto; clique simples ainda manda `push_to_talk`.

- [ ] **R2.B Tag do turno (núcleo → HUD)** — classificador local `turn_tag` no núcleo (reusa as
  regras de palavras do `mood.py`), `TurnTagMsg` em `contracts.py`, envio pelo canal do HUD, campo
  `turn_tag` no `Snapshot`; reações 74, 76, 86, 87 em `det_conversa`.
  - Lê: spec §6 B, `magi/memory/mood.py` (docstring e regras de palavras), `magi/common/contracts.py` (`_HudMsg`, `MoodMsg`), `hud/wired/integration.py` (trecho que trata `MoodMsg`: `grep -n mood`), `det_conversa.py`
  - Escreve: `magi/memory/turn_tag.py`, `magi/common/contracts.py`, o ponto do núcleo que manda `MoodMsg` (achar com `grep -rn "MoodMsg(" magi`), `hud/wired/integration.py`, `hud/wired/main_screen.py` (campo), `hud/wired/reacoes/det_conversa.py`, `catalogo.py` (linhas `sinal=`), `tests/memory/test_turn_tag.py`, `tests/hud/test_reacoes_tag.py`
  - Depende de: R0.5, R1.5
  - Orçamento: ~60k
  - Pronto: frases de teste (elogio, zoeira, correção, neutra) classificadas certo; tag com > 10 s ignorada.

- [ ] **R2.C Hooks do Claude Code** — `hud/tools/claude_hook.py`, leitura em `ClaudeStats`
  (`last_event`), reações 54, 55 em `det_claude`; trecho de `settings.json` documentado para o Pedro
  instalar (D2) em `docs/design/CONDESSA-REACOES.md`.
  - Lê: spec §6 C, `hud/wired/data.py` por trecho (`class ClaudeView`, `class ClaudeStats`), `det_claude.py`
  - Escreve: `hud/tools/claude_hook.py`, `hud/wired/data.py` (só `ClaudeView`/`ClaudeStats`), `hud/wired/reacoes/det_claude.py`, `catalogo.py`, `docs/design/CONDESSA-REACOES.md`, `tests/hud/test_claude_hook.py`
  - Depende de: R0.5, R1.5
  - Orçamento: ~40k
  - Pronto: hook falso grava linha; `ClaudeStats` lê só o novo; arquivo gira em 1 MB. **Não** editar `~/.claude/settings.json`.

- [ ] **R2.D Volume do PipeWire** — thread de 1 s com `wpctl` (subprocesso injetado), campo
  `volume`; `det_volume` para 31 e a variante de pico do 26.
  - Lê: spec §6 D, `hud/wired/data.py` (um leitor existente como modelo: `class GitStatus`), `contratos.py`
  - Escreve: `hud/wired/data.py` (classe nova `Volume`), `hud/wired/integration.py` (ligar a thread e o campo), `hud/wired/main_screen.py` (campo), `hud/wired/reacoes/det_volume.py`, `catalogo.py`, `tests/hud/test_reacoes_volume.py`
  - Depende de: R0.5
  - Orçamento: ~40k
  - Pronto: saída falsa do `wpctl` (`Volume: 0.45`, `[MUTED]`, erro) parseada; salto ≥ 20 pp em ≤ 2 s dispara 31.

- [ ] **R2.E Notificações (D-Bus, só escuta)** — leitor do `dbus-monitor` em thread (processo
  injetado), campo `notif`; `det_notif` para 46 (≤ 1/10 min) e 47 (urgência crítica).
  - Lê: spec §6 E, design §5 (proibição), `hud/wired/data.py` (modelo de leitor), `contratos.py`
  - Escreve: `hud/wired/data.py` (classe nova `Notificacoes`), `hud/wired/integration.py`, `hud/wired/main_screen.py` (campo), `hud/wired/reacoes/det_notif.py`, `catalogo.py`, `tests/hud/test_reacoes_notif.py`
  - Depende de: R0.5
  - Orçamento: ~45k
  - Pronto: texto gravado de `dbus-monitor` (fixture) parseado; processo morre com o HUD; nenhum `qdbus`/`gdbus` no código (teste com `grep`).

- [ ] **R2.F Voz baixa** — tag `sussurro` no `turn_tag` a partir do `ToneMetadata`; reação 88.
  - Lê: spec §6 F, `magi/memory/turn_tag.py`, `grep -n "ToneMetadata" -r magi` (só a dataclass)
  - Escreve: `magi/memory/turn_tag.py`, `hud/wired/reacoes/det_conversa.py`, `catalogo.py`, `tests/memory/test_turn_tag.py`
  - Depende de: R2.B
  - Orçamento: ~30k
  - Pronto: tom abaixo do limiar → `sussurro`; 88 dispara com a tag.

- [ ] **R2.G Sinais menores** — ventoinha (hwmon, raiz injetável), `needs-restarting` (6 h,
  subprocesso injetado), capturas (mtime), `[datas]` do gosto; `det_extras` para 43, 50, 51, 63.
  I20 fica para R3.1 (arte P13).
  - Lê: spec §6 Extras, `hud/wired/data.py` (modelo de leitor), `persona/condessa-gosto.toml` (`[datas]`), `contratos.py`
  - Escreve: `hud/wired/data.py` (classes novas `Ventoinha`, `Reinicio`, `Capturas`), `hud/wired/integration.py`, `hud/wired/main_screen.py` (campos), `hud/wired/reacoes/det_extras.py`, `catalogo.py`, `tests/hud/test_reacoes_extras.py`
  - Depende de: R0.5
  - Orçamento: ~55k
  - Pronto: hwmon falso em `tmp_path`; rc 0/1/erro do `dnf`; data do dia em `[datas]` dispara 63 uma vez.

> R2.D, R2.E e R2.G mexem em `data.py`, `integration.py` e `main_screen.py` só para **adicionar**
> classe/campo/linha nova; o orquestrador faz o merge em sequência (D → E → G) se houver conflito.

## Fase R3 — Arte e validação

- [ ] **R3.1 Arte nova** — **Pedro gera** (aba Assets novos da planilha da ata): prio 0 D1/D2/D6/D8;
  prio 1 E3, B16, D7; prio 2 P9, P10, B17, P12, P13; prio 3 P11. Agente: `condessa_build.py`
  aceita os IDs novos; efeitos em código passam a usar o PNG quando existir; I20 entra em `ATIVAS`
  quando P13 existir.
  - Lê: `hud/tools/condessa_build.py` por trecho (constantes do topo e `main`), `docs/design/CONDESSA-RETRATO.md`
  - Escreve: `hud/tools/condessa_build.py`, `hud/wired/portrait.py` (só a troca código → PNG dos efeitos), `catalogo.py`, `tests/hud/test_condessa_build.py`
  - Depende de: R0.3, R0.4 (e a arte)
  - Orçamento: ~50k
  - Pronto: build com pasta de teste contendo os IDs novos gera os arquivos; ausência de cada um não quebra.

- [ ] **R3.2 Validação de uma semana** — **precisa do Pedro.** Usar 7 dias; script
  `hud/tools/reacoes_relatorio.py` lê `reacoes.jsonl` e mostra por hora: ativas, passivas, furos
  de cota, top 10. Critérios de sucesso 3 e 4 do requirements. O que estiver poluindo volta ao
  Conselho (`/conselho`).
  - Lê: requirements (Critérios), spec §3, R10
  - Escreve: `hud/tools/reacoes_relatorio.py`, `tests/hud/test_reacoes_relatorio.py`, `docs/perf/reacoes.md`
  - Depende de: onda 1 completa (R1.1–R1.5)
  - Orçamento: ~30k
  - Pronto: relatório gerado com dados reais; CPU medida; nota do Pedro registrada.

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)

- R0.1: `Def` ganhou `variante` e `substituida` (citados em R0.4/spec §1, fora do bloco do spec §2). Stubs extras: `atividade.Atividade(caminho)` com `evento`/`parado_s`, `registro.gravar(d, disparo, agora, caminho)`, `catalogo.DEFS`/`ATIVAS`; R0.2/R1.4 podem ajustar.
- R0.2: `escolher` guarda o histórico num `governador.Estado` em `ctx["estado"]` (o chamador reusa o mesmo `ctx` entre ticks); demais chaves de `ctx` na docstring do módulo (`defs` aceita `chave` ou `(chave, variante)`, `hora`, `humor`, `jogo`, `claude`, `musica_nota`, `ado`, `desligadas`, `parada`). O disparo aprovado fica em `Estado.ultimo` para `registro.gravar`. Janelas de 1/h e 1/dia são móveis (3600 s / 86400 s); "I16 ≤ 1/noite" sai do 1/dia. Prioridade: classe de maior posto na Def (VOLTA/VITORIA/ZOEIRA etc. não têm posto próprio — use junto com PEDRO/SISTEMA no catálogo).
- R0.3: extras de corpo leem `extra/<ID>.png` no quadro das partes (`extra/E2.png` com recaída para `extra/fone.png`, `extra/E3.png`, `extra/P9.png`…); `condessa_build.py` ainda não gera E2/E3/P9–P13 (R3). `Reaction.efeitos` aceita nome ou ID D* (mapeado por `contratos.EFEITO`). `iris:<olhar>` só vale com a íris solta (O1). Na GPU (`renderer = "gl"`) os extras entram como camadas comuns, sem teste na GPU real.
- R0.4: `DEFS` usa a chave `chave` (sem variante) ou `(chave, variante)`, como o `_achar` do governador; `ATIVAS` guarda essas mesmas chaves; `TODAS` tem as 110 em ordem. Escolhas que ficam para revisão: 64 é o `led` base com a escalada inteira em 4 passos (as variantes `cutucada2`/`cutucada3` do spec §1 não viraram `Def` própria para manter as 110; o detector da R1.x pode recortar); a variante de pico do 26 (sinal D), a "árvore limpa" do 75 e a `happy` do 28 com Ado também não têm `Def` própria. I12 = `("musica_triste", "chopin")`. Classe do detector: entrada/conversa/claude → PEDRO, `posando_print` → PEDRO, 17–19/I16/I17 → PASSIVA+TEMPO; VOLTA (20, 57, 62) vem com PEDRO, VITORIA com SISTEMA/PEDRO. Passivas com `cooldown_s` 120 s (raras 1 h, diárias 1 dia, I17 2 h); só o 18 tem mood (`sleepy`). H3/H4 (franja, presilha) viraram nada/`sparkle`; F7 junto de B6/B7 ficou só F7. O1 = `iris:F1` (desvia) / `iris:B1` (volta).
- R0.5: **`ctx` dos detectores** (`(anterior, snap, ctx) -> list[Disparo]`; o mesmo `dict` (`Reactor.ctx`) reusado entre ticks, atualizado 1×/tick antes dos detectores; não guarde nada seu nele fora de chaves próprias): `defs` (dict `chave`/`(chave, variante)` → `Def`, só `ATIVAS`), `estado` (`governador.Estado`), `agora` (float, **`time.monotonic()`** do HUD — não é hora de parede), `relogio` (float, `clock()` de parede, epoch), `hora` (int 0–23), `madrugada` (bool, `[contexto] madrugada` do gosto), `humor` (int, **fixo 3** — falta o sinal do humor do Pedro; R1.1 decide de onde vem), `jogo` (bool), `claude` (bool, `snap.claude.running`), `musica_nota` (int −2..2; 0 sem faixa), `ado` (bool, artista reconhecido == "ado"), `faixa` (`(title, artist)` ou None), `faixa_desde` (float monotônico), `veredito` (`reactions.Verdict` ou None), `magui` (str, `snap.magui_state`), `parada` (bool: `magui == "sleeping"` e nenhuma reação no rosto; falso → governador só enche a fila), `atividade` (`atividade.Atividade`), `taste` (`reactions.Taste`; falas/gosto), `desligadas` (frozenset do `[reacoes] desligadas`). `passivas.sortear(ctx, agora, rng)` roda a cada 10 s (`PASSIVA_A_CADA`); `rng` = `Reactor.rng`. Detector que lança exceção é ignorado no tick. Injeção para testes: `Reactor(detectores=, sortear=, defs=, registro_file=, atividade=)`; `Reactor.tocar(d, disparo, now, passos)` toca uma sequência direto.
- R0.5: as 19 antigas seguem pelo `fire` (cooldown/prio/legenda próprios, CA-01); `_music`/`_decide` emitem `Disparo` em `Reactor._musica` e o `observe` os toca pelo `fire` no mesmo tick — **não** passam pelo governador (o cooldown de 600 s do catálogo para `music_love` etc. quebraria CA-01). As reações novas só começam com o rosto livre; uma antiga de `prio` ≥ a da sequência a substitui. `registro.gravar` recebe o relógio de parede. **Pendente fora do meu *Escreve*:** `tests/hud/conftest.py` não isola `registro.REGISTRO_FILE` nem `atividade.ESTADO_FILE` (lidos na hora, dá para `monkeypatch`); quando os detectores R1.x dispararem nos testes antigos, o log iria para o `~` real. `integration._react` não precisou mudar. CA-08: ~0,09 ms/tick com os stubs (teste trava em 2 ms).
- (orquestrador, pós-R0.5) `ctx["humor"]` agora vem de `snap.mood` (0..4 do núcleo; sem dado = 3). `conftest.py` isola `registro.REGISTRO_FILE` e `atividade.ESTADO_FILE`; `Atividade(caminho=None)` lê o `ESTADO_FILE` na hora.
- (orquestrador) As 19 reações antigas ainda tocam por `fire` direto, fora do governador: não contam no teto de 8/h. Revisar na validação (R3.2).
- R1.1: fatores sem fonte no `ctx` ficam como chaves opcionais que o `Reactor` pode preencher (fora do meu *Escreve*): `pc_problema` (bool, PC com problema), `favorita_dia` (chave do artista; hoje só existe `Reactor.favorite_of_day()`), `fps_estavel` (bool, padrão verdadeiro: "desempenho em jogo" = jogo aberto ≥ 5 min). Vitória recente vem de `Estado.ultimo` (com variante) e de `Estado.toques` só para `rede_voltou`/`ideia`/`cleanup` (os toques são por chave, sem variante); 35/37/53 que tocam pelo `fire` antigo não entram. Sessão longa = `atividade.parado_s(relogio)` < 30 min sem pausa por 3 h; Manhã = 1 h após toque do `bom_dia`. Sessão longa não favorece nenhuma passiva minha (sono 22h–05h é do det_tempo, 82/90 do det_claude): `humor.fatores` está pronto para eles. As passivas não saem no primeiro minuto do HUD (`AQUECIMENTO_S`, chave `_passivas_inicio` no `ctx`) — sem isso testes antigos de `test_wired_reactions` quebravam com uma passiva no t=0. Chance de passiva por sorteio de 10 s: 0,35 (metade em jogo); quem escolhe a favorecida de cada fator da tabela fui eu (acordo §4 só nomeia algumas). Vi uma vez `test_wired_portrait.py::test_partes_ouvindo_acorda_e_fica_atenta` falhar e não repetir (instável, fora do meu pacote).
- R1.2: os cliques do HUD (`on_click`: next/prev/playpause) e a contagem de plays/pulos do `Reactor` não estão no `ctx`; o `det_musica` infere tudo do `snap.track` e guarda o próprio estado em chaves `_musica_*` (lista na docstring). Pulo = troca de faixa com posição < duração − 3 s (sem posição: < 30 s de faixa); "botão" do 85 = play/pause alternado 3× em 10 s; 89 = direção da troca (voltou à faixa anterior da fila vista = prev). Plays do dia (28) e artistas já ouvidos (33) são da sessão do HUD (o `Reactor._plays`/`_seen` persistido daria o certo — pôr `plays`/`artista_novo` no `ctx`). Pendentes de catálogo: 29 tem D7 em toda hora (acordo: lágrima só 22h–04h e 1×/dia) — falta uma `Def` sem D7 ou variante; 28 com Ado (variante `happy`) não tem `Def`, então 28 não dispara para a Ado. Filtro "Ado nunca blush/love" no próprio detector (corta `music_love`, `surpresa_boa` e qualquer `Def` com D1 ou fundo `love` quando `ctx["ado"]`). I13 exige gênero `trilha` + `jogo` + `fps_estavel` contínuo por 2 min na mesma faixa. I12 = Chopin/Marika Takeuchi 0h–4h (substitui o 29 nesse caso).
- R1.3: 34/36/42/44/45 continuam só no `fire` antigo; o `det_sistema` espelha `hot` (85/78 °C) e `fps_drop` (< 60% da média, 2 leituras) com os limiares de `reactions.py` (copiados, não importados) para as variantes 35, 37, I4, 84 e I6 — se o `Reactor` expuser no `ctx` os toques antigos (`hot_em`, `fps_quedas`), o espelho some. Escolhas sem número no acordo: 35 só depois de ≥ 60 s quente (pico curto não vira alívio; também mantém `test_hud_quente_noticia_e_faxina` verde); 37 = FPS ≥ 90% da média por 2 leituras após uma queda; 41 = `disk_pct` ≥ 90% (sai < 85%); 80 com histerese de saída < 80%; I5 1× por episódio (sai com RAM < 85% e swap parado); 38 só depois de ter visto `net_ip` nesta execução; 84 = esquentou de novo ou `fps_drop` ≤ 10 min após o 34, 1× por 34. 48 não sai com jogo aberto no 1º snapshot (o palco é do `game_on`; sem isso 2 testes antigos quebravam). I4 (`vergonha`) passa pelo governador enquanto o `fps_drop` antigo toca no mesmo tick pelo `fire`: com prio do antigo ≥ a da sequência, a vergonha pode ser engolida — revisar em R3.2 (talvez o `Reactor` pular o `fire` antigo quando houver a variante).
- R1.4: o `Reactor` não chama `atividade.evento`; o `det_tempo` deduz os eventos reais do `snap` (faixa nova ou música voltando a tocar, Claude passou a rodar, Magui `listening`, jogo abriu) e registra com `ctx["relogio"]`. **Falta o clique no HUD** (`on_click`) como evento real — chamar `ctx["atividade"].evento(relogio, "clique")` no `Reactor`. `Atividade.evento` agora devolve `bool` (primeiro do dia ≥ 05h); `dia` no arquivo = data do último bom-dia. Escolhas sem número no acordo: "quieto" = Magui `sleeping` + Claude parado + sem música + sem jogo; sessão = ativo (evento < 30 min, Claude, música, jogo ou Magui fora de parada) sem buraco ≥ 30 min; 19 = sessão ≥ 2 h às 0h–4h; 58 = 12h–13h59; 60 = 3h–4h59 ativo; 61 só sem jogo (com jogo segue o `long_session` antigo do `fire`), 1×/sessão; I1 ignora buracos < 10 min do Claude; I2 = música parou há ≤ 30 min; I17 também não sai com jogo; só um retorno por evento (57 > 62 > 20). I19: `det_tempo.GIT` roda `git log` do repositório real **uma vez por processo** quando o detector roda pelo `Reactor` nos testes antigos — o `conftest.py` (fora do meu *Escreve*) deveria fazer `monkeypatch.setattr(det_tempo, "GIT", lambda: None)`; nos meus testes vai `ctx["git"]` falso.
