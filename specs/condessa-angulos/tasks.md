# Tarefas — Ângulos do retrato da Condessa

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `R`/`D`.
2. **Orçamento planejado ≤ 50k tokens**; o resto da janela de 128k é margem. Perto de 100k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use as assinaturas de `hud/wired/angulos.py` (A0.1); não leia o código
   de outras tarefas além das assinaturas.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `hud/gamerhud.py`, `hud/wired/portrait.py`, `hud/wired/main_screen.py`, `hud/wired/integration.py`,
   `hud/tools/condessa_build.py`, `hud/wired/reactions.py`.
6. **Testes curtos:** `uv run pytest -q -x tests/hud/<arquivo>` e `uv run ruff check <seus arquivos>`.
   Relógio injetado; nada de `sleep` real; Qt com `QT_QPA_PLATFORM=offscreen`; arte **sintética**
   gerada no teste (nunca a pasta real `~/.local/share/magi/condessa` nem `~/Downloads/Condessa`).
7. **Nada ao vivo nos testes:** sem abrir o HUD, sem núcleo, sem IA de imagem. Nunca
   `qdbus`/`gdbus` para KGlobalAccel/KWin.
8. **Uma tarefa = um commit** com o ID (`A1.1: seletor e transição`), na branch `angulos/<ID>`;
   merge no `main` pelo orquestrador.
9. **Frente intocada:** sem `angulos/` na pasta do retrato, o desenho é byte a byte o de hoje
   (R1.2, CA-A4).

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~2,5k,
`design.md` ~2k, `spec.md` ~4k; `portrait.py` inteiro seria ~16k (não leia inteiro);
`condessa_build.py` ~7k.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
A0.1 ─┬─ A1.1 ─┬─ A1.2 (também espera a V0.4 da condessa-vida) ── A2.1 ─┐
      └─ A1.3 ─┼──────────────────────────────────────────────────────┤
A0.2 ──────────┴─ A3.1 (arte, Pedro) ─────────────────────────────────┴─ A3.2 (ao vivo) ── A4.1 (fase 3)
```

---

## Fase A0 — Contratos e arte pedida

- [ ] **A0.1 Contratos e esqueleto** — `hud/wired/angulos.py` com `FRENTE`, `YAW`, `PITCH`,
  `Angulo`, `Camada`, `carregar`, `pedido`, `lado_do_look` completos e **stubs** com assinatura
  final de `Transicao` e `Seletor` (docstring com a tarefa dona). *(R1, R1.1, R7, spec §1–§2)*
  - Lê: design §2–§3, spec §1–§3, requirements R1, R7, R9, D1
  - Escreve: `hud/wired/angulos.py`, `tests/hud/test_angulos_carregar.py`
  - Depende de: —
  - Orçamento: ~30k
  - Pronto: CA-A1 verde; o módulo não importa Qt (só `pathlib`, `tomllib`, `dataclasses`); `ruff` limpo.
  - Paralelo: A0.2

- [ ] **A0.2 Lista de arte no doc** — seção "Ângulos (G*) — o que gerar" em
  `docs/design/CONDESSA-RETRATO.md`: regras de enquadramento, prefixo P0, tabela do spec §6 com
  fase, ID, nome do arquivo e prompt; como rodar o build e conferir. Marcar a fase mínima (6
  imagens). *(R8, D2, D3)*
  - Lê: spec §5–§6, requirements D2–D3, `docs/design/CONDESSA-RETRATO.md` linhas 1–45 e 191–205
  - Escreve: `docs/design/CONDESSA-RETRATO.md`
  - Depende de: —
  - Orçamento: ~15k
  - Pronto: seção nova com as 16 linhas e a fase mínima destacada; nada mais do doc muda.
  - Paralelo: A0.1

## Fase A1 — Código

- [ ] **A1.1 Seletor e transição** — `Transicao` (`k`, `camadas`, `acabou`) e `Seletor.escolher`
  com todas as regras do spec §3 e as curvas do spec §4. *(R2, R3, R4, R5, R9)*
  - Lê: spec §1, §3, §4, §7 (CA-A2, CA-A3); assinaturas de `angulos.py`; `hud/wired/reactions.py` linhas 60–106 (`Reaction`, `LOOK_DIRS`)
  - Escreve: `hud/wired/angulos.py` (só `Transicao` e `Seletor`), `tests/hud/test_angulos_seletor.py`
  - Depende de: A0.1
  - Orçamento: ~40k
  - Pronto: CA-A2 e CA-A3 verdes; uma linha de teste por regra do spec §3.
  - Paralelo: A1.3

- [ ] **A1.2 Retrato com ângulos** — `PartsAssets.angulos` (lazy, `angulos.carregar`);
  `PartsPortrait`: `Seletor` no `tick`, `_paint_angulo` (busto + respiração + balanço + piscar dos
  remendos + efeitos), transição com dois `QPixmap` misturados pelas `Camada` (fundo uma vez, por
  baixo), `_fast` verdadeiro durante a transição; caminho de hoje intacto sem ângulos. Só CPU; na
  GPU (`renderer = "gl"`) o ângulo é desenhado em CPU por cima do resultado (anotar em *Sobras*).
  *(R1.2, R2, R4–R6, design §4)*
  - Lê: design §4, §6, spec §2, §4, §7 (CA-A4, CA-A6); assinaturas de `angulos.py`; `hud/wired/portrait.py` por trecho: `grep -n "class PartsAssets\|class PartsPortrait\|def tick\|def paint\|def _fast\|def _backdrop\|def _reaction_effect\|def eye_frame\|_resting"` e só esses intervalos (≈ 390–430, 627–700, 840–1010, 1060–1090); `tests/hud/test_wired_portrait.py` só os helpers do topo
  - Escreve: `hud/wired/portrait.py`, `tests/hud/test_angulos_retrato.py`
  - Depende de: A1.1 e a **V0.4** de `specs/condessa-vida/` no `main` (as duas mexem no `paint`)
  - Orçamento: ~50k
  - Pronto: CA-A4 e CA-A6 verdes; `tests/hud/test_wired_portrait.py` inteiro verde sem mudar asserção.
  - Paralelo: —

- [ ] **A1.3 Montagem dos ângulos** — `build_angulos(src, out, base)` no `condessa_build.py` e a
  chamada no `main` (spec §5); tabela `ANGULOS` com `yaw`/`pitch` padrão de G2–G16 para o
  `angulo.toml`. *(R8)*
  - Lê: spec §2, §5, §7 (CA-A5); `hud/tools/condessa_build.py` por trecho: linhas 1–100 (cabeçalho e constantes), `grep -n "^def "` e só `load`, `chroma`, `bottom_fade`, `diff_mask`, `only_blobs`, `best_shift`, `build_extras` e o `main`; `tests/hud/test_condessa_build.py` só os helpers do topo
  - Escreve: `hud/tools/condessa_build.py`, `tests/hud/test_condessa_build_angulos.py`
  - Depende de: A0.1
  - Orçamento: ~45k
  - Pronto: CA-A5 verde; `tests/hud/test_condessa_build.py` inteiro verde.
  - Paralelo: A1.1, A1.2

## Fase A2 — Ligação

- [ ] **A2.1 Gosto e reações pedindo ângulo** — `Taste` lê `[angulos]` (`ligado`, `desligados`, e
  os números do spec §3 se presentes) e o `integration` repassa ao retrato
  (`mascot.set_angulos_cfg(cfg)`, sem efeito no mascote vetorial); no catálogo, `corpo` com
  `angulo:G9` nos passos de "ideia"/pensando e `angulo:G10` no susto (só os campos `corpo=` dessas
  linhas; sem a arte, ignorado). *(R7, R9)*
  - Lê: spec §1, §3; requirements R7, R9; `hud/wired/reactions.py` por trecho (`class Taste`, `grep -n "def _load\|tomllib"`); `hud/wired/integration.py` linhas 186–200; `hud/wired/reacoes/catalogo.py` só `grep -n "ideia\|susto\|pensa"`
  - Escreve: `hud/wired/reactions.py` (só `Taste`), `hud/wired/integration.py` (só o repasse), `hud/wired/portrait.py` (só `set_angulos_cfg`), `hud/wired/reacoes/catalogo.py` (só `corpo=`), `tests/hud/test_angulos_gosto.py`
  - Depende de: A1.2
  - Orçamento: ~40k
  - Pronto: teste com gosto sintético desligando G2 → seletor nunca usa G2; reação "ideia" com G9 sintético vira G9; `tests/hud` inteiro verde.
  - Paralelo: —

## Fase A3 — Arte e validação

- [ ] **A3.1 Arte da fase mínima** — **precisa do Pedro.** Gerar G2, G2_B2, G2_B3, G3, G3_B2, G3_B3
  (spec §6), pôr em `~/Downloads/Condessa`, rodar o build e conferir na prancha
  (`hud/tools/portrait_check.py`) que os ombros casam com a A1.
  - Lê: `docs/design/CONDESSA-RETRATO.md` seção "Ângulos (G*)"
  - Escreve: — (arte fora do repositório); avisos do build anotados em *Sobras*
  - Depende de: A0.2, A1.3
  - Orçamento: — (trabalho do Pedro)
  - Pronto: `angulos/G2` e `angulos/G3` montados sem aviso de escala.
  - Paralelo: A1.2, A2.1

- [ ] **A3.2 Validação ao vivo** — **precisa do Pedro.** HUD aberto com G2/G3 por 2 dias; critérios
  1, 4 e 5; ajustar no `[angulos]` do gosto (duração, deslocamento, intervalo) o que ele pedir;
  decidir D4 e D6.
  - Lê: requirements (Critérios, D4, D6), spec §3–§4
  - Escreve: `docs/perf/angulos.md`, `docs/PROXIMOS-PASSOS.md` (§13: a linha dos ângulos)
  - Depende de: A2.1, A3.1
  - Orçamento: ~20k
  - Pronto: nota do Pedro ("virou" × "trocou de foto"), CPU medida, números finais registrados.
  - Paralelo: —

## Fase A4 — Depois da fase mínima

- [ ] **A4.1 Fala nos ângulos (fase 3)** — com `G2_C2`/`G2_C3` (e G3) montados e `fala = true` no
  `angulo.toml`: boca pela voz no ângulo (mesmos `MOUTH_LEVELS` da frente), e o seletor deixa de
  forçar `G1` na fala para esses ângulos. Arte da fase 2 (G6, G7, G9, G10, G11) entra sem código
  novo (o seletor já sabe usá-la).
  - Lê: spec §2–§3, §6; `hud/wired/portrait.py` `grep -n "def mouth_id\|MOUTH_LEVELS"` e o `_paint_angulo` da A1.2; assinaturas de `angulos.py`
  - Escreve: `hud/wired/portrait.py` (só `_paint_angulo` e a boca), `hud/wired/angulos.py` (só a regra da fala no `Seletor`), `tests/hud/test_angulos_fala.py`
  - Depende de: A3.2
  - Orçamento: ~40k
  - Pronto: fala em G2 sintético troca C1/C2/C3 pelo volume; sem `fala = true`, volta a `G1` como antes.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
