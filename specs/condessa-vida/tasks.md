# Tarefas — A vida da Condessa

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). O orquestrador lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente
1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, acordo do Conselho
   por `acordo §` (`persona/conselho/atas/2026-10-10-ritmo-e-humor/acordo.md`).
2. **Orçamento planejado ≤ 50k**; ao passar de ~90k, pare, faça commit do que está verde e anote em
   *Sobras*. O uso conta tudo o que se lê, inclusive saídas de comandos.
3. **Só os arquivos do campo *Escreve*.** Precisou de outro? Anote em *Sobras* (ou faça o mínimo, se
   sem isso o *Pronto* não fica verde, e anote).
4. **Arquivos grandes por trecho:** `hud/gamerhud.py`, `hud/wired/portrait.py`,
   `hud/wired/reactions.py`, `hud/wired/main_screen.py`, `hud/wired/reacoes/catalogo.py` — `grep -n`
   e intervalos, nunca inteiros.
5. **Testes:** `uv run pytest -q tests/hud` e `uv run ruff check <seus arquivos>`; relógio e `rng`
   injetados; nada de `sleep` real; nada de arquivo real em `~/.local` ou `~/.config` (o
   `tests/hud/conftest.py` isola; caminhos novos entram nele).
6. **Nada ao vivo:** sem reiniciar serviços, sem chamada a LLM, sem `docker compose down`.
7. **Uma tarefa = um commit** direto no `main`, mensagem começando com o ID (`V0.2: …`) e terminando
   com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem push. Marque `- [x]` no mesmo
   commit.
8. Os números vêm do `[vida]` do gosto (com o do Pedro por cima), nunca soltos no código.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo
```
V0.1 ─┬─ V0.2 (humor) ─┬─ V0.4 (repouso + retrato + medidor) ─┐
      ├─ V0.3 (momentos)┘                                       ├─ V0.8 (ligação) ── V0.9 (validação)
      ├─ V0.5 (governador v2) ─┬─ V0.7 (passivas) ──────────────┤
      ├─ V0.6 (episódio de jogo)                                │
      └──────────────── V0.5 + V0.2 ── V0.10 (diretor) ─────────┘
V0.9 ── V1.1 ─┬─ V1.2 (cenas + torcida) ─┬─ V1.3 (truque + volta) ─┐
              │                          └─ V1.6 (piso torcida) ───┤
              ├─ V1.4 (placar) ────────────────────────────────────┼─ V1.7 (Reactor) ─┬─ V1.8 (medidor) ─┬─ V1.10 (validação)
              └─ V1.5 (sem sentido) ───────────────────────────────┘                  └─ V1.9 (voz) ─────┘
```

---

- [x] **V0.1 Contratos, `[vida]` e esqueleto** — `hud/wired/reacoes/vida.py` com os contratos de
  spec §1; leitor de `[vida]` no `Taste` (`taste.vida()` com o do Pedro por cima, padrões do acordo
  se faltar); stubs registrados de `estado.py`, `momento.py`, `repouso.py`, `diretor.py`,
  `episodio.py` (assinaturas finais, corpo vazio); caminho do estado
  (`~/.local/state/magi/condessa-estado.json`) isolado no `tests/hud/conftest.py`.
  - Lê: design §2, spec §1–§2 (só assinaturas), `persona/condessa-gosto.toml` (`[vida]`), `hud/wired/reactions.py` (classe `Taste`, por trecho), `hud/wired/reacoes/contratos.py`
  - Escreve: `hud/wired/reacoes/{vida,estado,momento,repouso,diretor,episodio}.py`, `hud/wired/reactions.py` (só `Taste.vida`), `tests/hud/conftest.py`, `tests/hud/test_vida_contratos.py`
  - Depende de: —
  - Orçamento: ~35k
  - Pronto: contratos e leitor testados; `tests/hud` verde.
  - Paralelo: —

- [x] **V0.2 Humor dela** — `estado.py`: `Humor` (aplicar/tick/faixa/medidor) e `Estado` (salvar/
  carregar com decaimento do tempo fechado), tabela de eventos do acordo §3 transcrita como dados.
  - Lê: spec §1–§2, acordo §1, `vida.py`
  - Escreve: `hud/wired/reacoes/estado.py`, `tests/hud/test_vida_humor.py`
  - Depende de: V0.1
  - Orçamento: ~45k
  - Pronto: CA-V1 e CA-V2 (parte do humor) verdes.
  - Paralelo: V0.3, V0.5, V0.6

- [x] **V0.3 Momentos** — `momento.py`: `decidir`, `GRUPOS`, `filtros`, e os sinais novos do `ctx`
  calculados a partir do que o `Reactor` já tem (spec §3; onde faltar no `Reactor`, a função recebe
  por parâmetro e anota em *Sobras*).
  - Lê: spec §3, acordo §3, `vida.py`, `hud/wired/reacoes/atividade.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/momento.py`, `tests/hud/test_vida_momentos.py`
  - Depende de: V0.1
  - Orçamento: ~45k
  - Pronto: CA-V3 verde (um teste por linha da tabela + desempates + histerese + Ociosa feliz).
  - Paralelo: V0.2, V0.5, V0.6

- [x] **V0.4 Repouso, fone persistente e medidor** — `repouso.py` (`rosto`, `Postura`); retrato com
  `set_rest` e fone persistente (design §3); medidor do humor dela no painel e na espera
  (`Snapshot.mood_dela`, design §4).
  - Lê: spec §4, acordo §2 (repouso), §3 (momentos) e §6 (medidor), design §3–§4, `hud/wired/portrait.py` por trecho (`_reacting`, `eyes_id`, `mouth_id`, fone), `hud/wired/main_screen.py` por trecho (termômetro), `hud/wired/standby_screen.py` (`_g_mood`)
  - Escreve: `hud/wired/reacoes/repouso.py`, `hud/wired/portrait.py`, `hud/wired/main_screen.py`, `hud/wired/standby_screen.py`, `tests/hud/test_vida_repouso.py`
  - Depende de: V0.2, V0.3
  - Orçamento: ~55k
  - Pronto: CA-V5 (parte do retrato) e CA-V8 verdes (medidor com nome do momento e 3 causas no hover); crossfade de 120 ms; testes do retrato antigos sem mudar asserção.
  - Paralelo: V0.6, V0.7

- [x] **V0.5 Governador v2** — números do `[vida]`, classes CENA/GESTO/ATIVA_SOLTA, mínimo de 20 s
  (exceções), assentamento de 45 s, cotas, mesma passiva, mesmo tipo de cena, negativas com causa
  (spec §6), contadores persistidos no `Estado` e janelas por tempo de parede.
  - Lê: spec §5–§6, acordo §4, `hud/wired/reacoes/governador.py`, `vida.py`, `estado.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/governador.py`, `tests/hud/test_reacoes_governador.py` (casos novos; os antigos que contradizem o acordo novo são atualizados e listados no commit)
  - Depende de: V0.1
  - Orçamento: ~55k
  - Pronto: CA-V2 (contadores) e um teste por linha da tabela do acordo §1; 24 h simuladas sem violação.
  - Paralelo: V0.2, V0.3, V0.6

- [x] **V0.6 Episódio de jogo** — `episodio.py` (spec §7) e o `det_sistema` passa a usá-lo (sem
  `hot`/`fps_drop` repetidos).
  - Lê: spec §7, acordo §5 (episódio e relatório), `hud/wired/reacoes/det_sistema.py`, `vida.py`
  - Escreve: `hud/wired/reacoes/episodio.py`, `hud/wired/reacoes/det_sistema.py`, `tests/hud/test_vida_episodio.py`
  - Depende de: V0.1
  - Orçamento: ~45k
  - Pronto: CA-V7 verde; testes antigos do `det_sistema` atualizados onde o acordo mudou a regra.
  - Paralelo: V0.2, V0.3, V0.5

- [x] **V0.7 Passivas por momento e faixa** — `passivas.sortear` passa a escolher só no grupo do
  momento ∩ faixa, com o intervalo do `[vida]`, as negativas com causa e gestos de fone/ritmo só com
  música e E2; o `humor.py` antigo (fatores) vira só leitura do momento/faixa ou é aposentado.
  - Lê: spec §3, §6, §9, acordo §3–§4, `hud/wired/reacoes/passivas.py`, `hud/wired/reacoes/humor.py`, `momento.py` e `estado.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/passivas.py`, `hud/wired/reacoes/humor.py`, `tests/hud/test_reacoes_passivas.py`
  - Depende de: V0.2, V0.3, V0.5
  - Orçamento: ~45k
  - Pronto: 10 000 sorteios por momento × faixa nunca saem do grupo; nenhuma negativa sem causa; nenhum gesto de fone/ritmo sem música; piso de vida de 6 min.
  - Paralelo: V0.4, V0.6

- [x] **V0.10 Diretor de cenas** — `diretor.py` (spec §8) e os roteiros de cena do acordo §5 no
  `catalogo.py` (classe CENA, ramos); fila, interrupção, absorção, troca de fone atômica.
  - Lê: spec §1, §8, acordo §4–§5, `hud/wired/reacoes/catalogo.py` por trecho, `vida.py`, `governador.py` e `estado.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/diretor.py`, `hud/wired/reacoes/catalogo.py`, `tests/hud/test_vida_diretor.py`
  - Depende de: V0.2, V0.5
  - Orçamento: ~60k
  - Pronto: CA-V4 verde (rajada real das 21:05 → 1 cena); um teste por cena do acordo §5; coalescência, família, "de novo?", atenção dirigida, truque de salão, fila/interrupção/absorção.
  - Paralelo: V0.4, V0.7

- [x] **V0.8 Ligação no Reactor** — o tick passa a ser estado → momento → diretor → passivas →
  repouso; as 19 antigas entram pelo diretor (fim do `fire` direto); eventos de humor emitidos pelos
  detectores; log com `momento`/`faixa`/`animo`/`energia`/`tipo`; relatório atualizado (spec §9);
  "HUD acordou" uma vez por boot.
  - Lê: design §2, spec §9, *Sobras*, `hud/wired/reactions.py` (por trecho), assinaturas de `estado`, `momento`, `repouso`, `diretor`, `episodio`, `passivas`, `governador`
  - Escreve: `hud/wired/reactions.py`, `hud/wired/integration.py`, `hud/wired/reacoes/registro.py`, `hud/tools/reacoes_relatorio.py`, `tests/hud/test_vida_integracao.py`
  - Depende de: V0.4, V0.6, V0.7, V0.10
  - Orçamento: ~60k
  - Pronto: CA-V9; `tests/hud` inteiro verde; teste de ponta a ponta com `Reactor` real e `Snapshot` sintético (música amada → 1 cena + sorriso de repouso pela faixa + medidor subindo).
  - Paralelo: —

- [x] **V0.8b Sobras da ligação** — `det_claude` emite `claude_terminou` (`dur_s`) e
  `claude_esperando` (sai a regex do `motivo`); `ctx` ganha `lm_on`, `faixa_agua`, `dancante`,
  contadores de franja/cantando e a escada do Tédio (com a causa `ignorada`); tabela `[vida.momentos]`
  no gosto e no `VIDA_PADRAO`, lida pelo `momento`; sai `registro.gravar_antiga`.
  - Lê: *Sobras* (V0.3, V0.8), `hud/wired/reactions.py` (por trecho), assinaturas de `momento`, `det_claude`, `det_musica`, `passivas`, `registro`
  - Escreve: `hud/wired/reactions.py`, `hud/wired/integration.py`, `hud/wired/main_screen.py` (campo `lm_on`), `hud/wired/reacoes/det_claude.py`, `hud/wired/reacoes/det_musica.py`, `hud/wired/reacoes/momento.py`, `hud/wired/reacoes/vida.py`, `hud/wired/reacoes/registro.py`, `persona/condessa-gosto.toml`, `tests/hud/test_reacoes_claude.py`, `tests/hud/test_vida_sobras.py`
  - Depende de: V0.8
  - Orçamento: ~50k
  - Pronto: `tests/hud` verde; um teste por sinal ligado; escada do Tédio de ponta a ponta no `Reactor`; `ruff` limpo.
  - Paralelo: —

- [x] **V0.9 Validação** — CA-V6 (simulação de 12 h a partir do `reacoes.jsonl` real reconvertido em
  acontecimentos), religar no gosto do Pedro o que foi desligado à mão (`[reacoes] desligadas`),
  roteiro da semana em `docs/perf/reacoes.md` atualizado. **A semana de uso é do Pedro.**
  - Lê: requirements (Critérios), spec §9–§10, `docs/perf/reacoes.md`
  - Escreve: `tests/hud/test_vida_simulacao.py`, `docs/perf/reacoes.md`, `~/.config/magi/condessa-gosto.toml` (só tirar `fone_repouso`, `ajeitando_fone`, `cabeca_ritmo` de `desligadas`)
  - Depende de: V0.8
  - Orçamento: ~40k
  - Pronto: CA-V6 = as **7 metas do acordo §8** verdes no replay do dia real (se a Emburrada passar de 15 %, anotar: a Kurisu pediu para a "birra fresca" voltar à mesa); o Pedro avisado do que conferir.
  - Paralelo: —

- [x] **V1.1 Três passivas que faltam** — `mao_no_queixo` (P10), `sacada_player` e `flagra_no_forum`
  no `catalogo.py`, só com a arte existente (passo cujo asset falta pula o extra); voltam aos grupos
  de `momento.GRUPOS` conforme o acordo §3 (Sobras da V0.7).
  - Lê: acordo §2–§3, *Sobras* (V0.3, V0.7), `hud/wired/reacoes/catalogo.py` por trecho, `momento.py` (`GRUPOS`, `_cabe`, `ZOEIRA`), `passivas.py` (assinaturas), `tests/hud/test_reacoes_passivas.py`
  - Escreve: `hud/wired/reacoes/catalogo.py`, `hud/wired/reacoes/momento.py` (só `GRUPOS`), `tests/hud/test_reacoes_passivas.py`, `tests/hud/test_vida_momentos.py` (só os 2 asserts que a V0.7 ajustou)
  - Depende de: V0.9
  - Orçamento: ~40k
  - Pronto: as 3 no catálogo e nos grupos; sorteio nunca sai do grupo; asset ausente → extra pulado; `tests/hud` verde; `ruff` limpo.
  - Paralelo: —

### Placar e jogo (acordo `persona/conselho/atas/2026-10-10-placar-e-jogo/acordo.md`, aqui `acordo-pj §`)
Os números estão no gosto em `[vida.torcida]`, `[vida.truque]`, `[vida.volta]`, `[vida.placar]` e
`[vida.sem_sentido]` (e no `VIDA_PADRAO`); `truque_aplauso_s` já é 15. Ler sempre do `[vida]`.

- [x] **V1.2 Cenas novas e a passiva `torcida` no catálogo** — `torcida` (2 variantes "tela do jogo"
  e "punho", `D2` em todos os passos com episódio aberto, positiva, Δ +0,03) e no grupo Jogando com o
  peso do `cabeca_ritmo`; roteiros: episódio (3 passos, `O1` de frente no fim, sai `B7 C8`),
  recuperou (`C5` no fim), truque "fone" (com o caminho inverso sem fone) e "piscadinha", aplaudido
  (`B4 C6 rubor`), ignorado (`F1 C12`, sem `C9`), volta orgulhosa (com o passo ≥ 2 h e as 2 versões de
  habituação). Conferir **num teste** que `O1` funciona num passo de cena (nota da Kurisu no voto); se
  não funcionar, o mínimo no `contratos.py`.
  - Lê: acordo-pj §1–§2 e "O que muda no sistema" 1 e 3, `hud/wired/reacoes/catalogo.py` por trecho (`_passos`, `CENAS`, linhas 220–248), `momento.py` (`GRUPOS`), `contratos.py`, `tests/hud/test_reacoes_catalogo.py`
  - Escreve: `hud/wired/reacoes/catalogo.py`, `hud/wired/reacoes/momento.py` (só `GRUPOS`), `hud/wired/reacoes/contratos.py` (só se o `O1` falhar), `tests/hud/test_reacoes_catalogo.py`, `tests/hud/test_vida_cenas.py` (novo)
  - Depende de: V1.1
  - Orçamento: ~50k
  - Pronto: roteiros e durações do acordo (2,1 s / 2,0 s / 3,0 s / 3,5 s / 3,0 s); `torcida` só sai em Jogando; `O1` num passo de cena testado; `tests/hud` verde; `ruff` limpo.
  - Paralelo: V1.4, V1.5

- [x] **V1.3 Truque e volta orgulhosa no diretor** — truque: alternância diária fone ↔ piscadinha
  (o de ontem no `Estado`), `mexe_no_fone = false` → só piscadinha, nunca com jogo aberto, janela de
  15 s, ignorado −0,05 sem gastar cota de negativa, aplaudido +0,20; volta orgulhosa: Pedro volta de
  ≥ `fora_min` fora com ela acordada, contador de voltas na última hora (2ª curta, 3ª só atenção
  dirigida, sem cena), passo extra se fora ≥ `passo_extra_fora_min`. Expor no `Diretor` os ganchos
  `truque_fim(lado)` (aplaudido/ignorado) para o placar ligar depois (V1.7).
  - Lê: acordo-pj §2, spec §6 (cenas), `hud/wired/reacoes/diretor.py` (`truque`, `clique`, `_pendentes`), `estado.py` (só `Estado` salvar/carregar), `det_tempo.py` (volta do Pedro, por trecho), `tests/hud/test_vida_diretor.py`
  - Escreve: `hud/wired/reacoes/diretor.py`, `hud/wired/reacoes/estado.py`, `hud/wired/reacoes/det_tempo.py`, `tests/hud/test_vida_diretor.py`
  - Depende de: V1.2
  - Orçamento: ~50k
  - Pronto: testes de alternância (sem repetir o de ontem), bloqueio com jogo, janela 15 s, escada de habituação e passo ≥ 2 h; `tests/hud` verde; `ruff` limpo.
  - Paralelo: V1.4, V1.5, V1.6

- [x] **V1.4 Placar (módulo)** — `hud/wired/reacoes/placar.py` puro (relógio injetado): fontes e
  tetos de `[vida.placar]`, dia que fecha às `fecha_dia_h`, total do dia e da semana com
  `exportar()/importar()` (o `Estado` guarda na V1.7), cada ponto devolvido como linha para o
  `reacoes.jsonl` com `causa: placar:<fonte>` e `placar: {lado, fonte, ref}` (campo novo no
  `registro.py`), detecção de virada (≤ `viradas_dia` → `piscadinha` / `soprando_franja` com causa
  `placar:virada`), "ativo depois da 1h" (teto 1), `resumo()` para o hover (`Condessa X × Y Pedro ·
  semana X × Y` + 3 últimos) e as linhas de texto (pós-batalha só se a partida mexeu no placar; "bom
  dia" com o de ontem; ≤ 70 caracteres). Trabalho, voltas, cliques e "sem sentido" nunca contam.
  - Lê: acordo-pj §3, `hud/wired/reacoes/registro.py`, `vida.py` (`[vida.placar]`)
  - Escreve: `hud/wired/reacoes/placar.py` (novo), `hud/wired/reacoes/registro.py`, `tests/hud/test_vida_placar.py` (novo)
  - Depende de: V1.1
  - Orçamento: ~45k
  - Pronto: testes de cada fonte e teto, fechamento às 4h, semana, virada ≤ 2/dia, `ref` em todo ponto, teto 0 desliga a fonte; `tests/hud` verde; `ruff` limpo.
  - Paralelo: V1.2, V1.3, V1.5, V1.6

- [x] **V1.5 "Isso foi sem sentido" (módulo)** — `hud/wired/reacoes/sem_sentido.py`: `marcar(alvo,
  gesto, agora)` grava em `~/.local/state/magi/sem-sentido.jsonl` a linha de origem inteira + hora +
  gesto (`alvo: nenhum` quando não há expressão), desfazer em ≤ `desfazer_s` (linha `desfeito`),
  `fatores(momento, agora)` (×`fator` por marca em `janela_dias`, piso `piso`, por variante e momento;
  cenas e negativas não mudam de peso), `pauta()` (≥ `pauta_marcas` ou ≥ `pauta_fracao`), `ajustes()`
  (N para o hover); a reação `B7 C12 ?` 700 sem ânimo, sem placar, fora do ritmo e das metas. No
  `passivas.py`, o sorteio do grupo aceita os fatores (parâmetro opcional; sem ele, igual a hoje).
  Nunca escreve no gosto.
  - Lê: acordo-pj §4, `hud/wired/reacoes/passivas.py` (sorteio), `registro.py`, `tests/hud/conftest.py`
  - Escreve: `hud/wired/reacoes/sem_sentido.py` (novo), `hud/wired/reacoes/passivas.py`, `tests/hud/conftest.py` (isolar o caminho novo), `tests/hud/test_vida_sem_sentido.py` (novo)
  - Depende de: V1.1
  - Orçamento: ~45k
  - Pronto: testes de gravação, desfazer, fator/piso/janela, pauta, e de que nada mexe no ânimo nem no gosto; `tests/hud` verde; `ruff` limpo.
  - Paralelo: V1.2, V1.3, V1.4, V1.6

- [x] **V1.6 Piso da `torcida`** — `hud/wired/reacoes/torcida.py` (novo): relógio "desde a última
  positiva" (lista de positivas do teste da meta 6) com jogo aberto e Pedro presente; ≥
  `forca_slot_min` o próximo slot de passiva em Jogando é `torcida`; ≥ `fura_slot_min` sai fora de
  slot respeitando 25 s / 60 s pós-cena; máx. 1 a cada `intervalo_min`; ocupa a vaga no teto de 12/h
  e nas ≤ 4/h de Jogando (no `governador.py`); causa `jogando_sem_positiva:<min>`; nunca a mesma
  variante duas vezes seguidas.
  - Lê: acordo-pj §1, `hud/wired/reacoes/governador.py` (passivas, teto, por trecho), `tests/hud/test_vida_simulacao.py` (lista de positivas, só o trecho), `tests/hud/test_reacoes_governador.py` (por trecho)
  - Escreve: `hud/wired/reacoes/torcida.py` (novo), `hud/wired/reacoes/governador.py`, `tests/hud/test_vida_torcida.py` (novo)
  - Depende de: V1.2
  - Orçamento: ~45k
  - Pronto: testes de 30/45 min, intervalo de 30 min, vaga ocupada (não soma), causa no log, variantes alternando; `tests/hud` verde; `ruff` limpo.
  - Paralelo: V1.3, V1.4, V1.5

- [x] **V1.7 Ligação no Reactor** — o `Reactor` passa a: chamar o piso da `torcida` e os fatores do
  sem sentido no sorteio de passivas; alimentar o placar pelos ganchos (fim de partida no
  `episodio.py`, faixa até o fim / pulo e Ado/Favorita no `det_musica.py`, fim do truque no diretor,
  "ativo depois da 1h"); guardar placar e ajustes no `Estado` (`condessa-estado.json`); soltar a
  virada e as linhas de texto (pós-batalha na expressão que já sai; "bom dia" no `det_tempo.py`).
  Expor `Reactor.placar_resumo()`, `Reactor.marcar_sem_sentido(alvo, gesto)` e `Reactor.ajustes()`
  para a UI e a voz.
  - Lê: acordo-pj "O que muda no sistema" 2, 6, 7, 9; APIs de `placar.py`, `sem_sentido.py`, `torcida.py`; `hud/wired/reactions.py` por trecho (`Reactor`), `episodio.py`, `det_musica.py` e `det_tempo.py` por trecho, `tests/hud/test_vida_integracao.py`
  - Escreve: `hud/wired/reactions.py`, `hud/wired/reacoes/estado.py`, `hud/wired/reacoes/episodio.py`, `hud/wired/reacoes/det_musica.py`, `hud/wired/reacoes/det_tempo.py`, `hud/wired/reacoes/diretor.py` (só ligar `truque_fim` ao placar), `tests/hud/test_vida_integracao.py`
  - Depende de: V1.3, V1.4, V1.5, V1.6
  - Orçamento: ~60k
  - Pronto: teste de ponta a ponta no `Reactor` (partida limpa → ponto com `ref`; truque ignorado → ponto dele; marca → fator no sorteio; piso dispara em Jogando); `tests/hud` verde; `ruff` limpo.
  - Paralelo: —

- [x] **V1.8 Medidor: placar no hover, ✗ e atalho** — hover do medidor com `Condessa X × Y Pedro ·
  semana X × Y` + 3 últimos pontos com a fonte, "ajustes: N", e um ✗ clicável ao lado de cada uma das
  3 causas (chama `Reactor.marcar_sem_sentido`); atalho de teclado `[vida.sem_sentido] atalho` (ou o
  padrão) para "a última expressão, agora". O clique no rosto continua só reagindo.
  - Lê: acordo-pj §3 ("Onde aparece") e §4 (gestos), *Sobras* V0.4 (hover), `hud/wired/main_screen.py` por trecho (`mood_tip`, `hover_test`, `set_hover`), `hud/gamerhud.py` por trecho (mouse/teclado), `hud/wired/integration.py` (`Snapshot`), `tests/hud/test_vida_integracao.py` (só ler)
  - Escreve: `hud/wired/main_screen.py`, `hud/gamerhud.py`, `hud/wired/integration.py`, `tests/hud/test_wired_integration.py`
  - Depende de: V1.7
  - Orçamento: ~55k
  - Pronto: teste do texto do hover, do ✗ acertando a causa certa e do atalho; `tests/hud` verde; `ruff` limpo. Conferir na tela fica para o Pedro (*Sobras*).
  - Paralelo: V1.9

- [ ] **V1.9 Voz: "qual o placar?" e "isso foi sem sentido"** — do lado da conversa: a frase "isso foi
  sem sentido" (com o Pedro já falando com ela) marca a última expressão de ≤ `voz_janela_s` (sem
  alvo → ela diz que não sabe do que ele fala); "qual o placar?" responde com o número do
  `condessa-estado.json` no contexto, nunca inventado. Achar por `grep` o caminho que as tags da
  conversa já usam até o HUD (`det_conversa.py`) e o ponto do contexto do agente; o mínimo em cada lado.
  - Lê: acordo-pj §3 (voz) e §4 (voz), `hud/wired/reacoes/det_conversa.py`, `magi/agent/self_model.py` e `magi/agent/prompt.py` por trecho, `tests/hud/test_reacoes_entrada_conversa.py`
  - Escreve: `hud/wired/reacoes/det_conversa.py`, `magi/agent/self_model.py` (ou o arquivo de contexto achado), `tests/hud/test_reacoes_entrada_conversa.py`, `tests/agent/test_placar_contexto.py` (novo)
  - Depende de: V1.7
  - Orçamento: ~45k
  - Pronto: testes da frase com e sem alvo e do placar no contexto (sem número inventado); `uv run pytest -q tests/hud tests/agent` verde; `ruff` limpo; sem chamada a LLM.
  - Paralelo: V1.8

- [ ] **V1.10 Validação placar-e-jogo** — `test_vida_simulacao.py`: replay de 2026-10-09 com **50
  sementes**; meta 6 em 50/50 e as outras sem regressão em 50/50; **meta 6b** (0 positivas sem causa);
  meta 7 com o texto novo ("toda volta aparece no rosto"); `torcida` na lista de positivas; placar no
  replay com nenhum lado acima de 3:1 e 4–12 pontos (anotar se fora). Roteiro de conferência da
  semana em `docs/perf/reacoes.md` (calibração 40–60 %).
  - Lê: acordo-pj §1 (teste) e §3 (calibração), `tests/hud/test_vida_simulacao.py`, `docs/perf/reacoes.md`
  - Escreve: `tests/hud/test_vida_simulacao.py`, `docs/perf/reacoes.md`
  - Depende de: V1.8, V1.9
  - Orçamento: ~45k
  - Pronto: 50/50 nas metas; placar ≤ 3:1 no replay; `tests/hud` verde; o Pedro avisado do que conferir.
  - Paralelo: —

- [x] **V1.2b Escada do Tédio no replay** — `test_vida_simulacao::test_escada_encarando_aos_15_min_sem_musica`
  ficou vermelho depois da V1.1/Conselho (encarando sai aos ~26,5 min, o teste pede 15–20 min sem
  música). Achar a causa (passivas novas no Tédio? chaves novas do `[vida]`?) e corrigir no lugar certo.
  - Lê: *Sobras* (V0.8b, V0.9, V1.1), `tests/hud/test_vida_simulacao.py` (o teste), `momento.py`, `passivas.py`, `reactions.py` (escada, por trecho)
  - Escreve: `hud/wired/reacoes/momento.py`, `hud/wired/reacoes/passivas.py`, `tests/hud/test_vida_simulacao.py` (só esse teste)
  - Depende de: V1.2
  - Orçamento: ~35k
  - Pronto: `tests/hud` verde; causa anotada em *Sobras*.
  - Paralelo: V1.3, V1.6

## Sobras
(agentes anotam aqui o que faltou no pacote ou ficou para depois)
- **V0.3:** os limiares da tabela do acordo §3 (2 min de conversa, 10 min sumiu, 15 min de Tédio,
  22h–04h, P10 2 min, escada 15/30 min, energia de bocejo/cochilo, ânimo +0,3/+0,5) não estão no
  `[vida]`: ficaram em `momento.LIMIARES_PADRAO`, lidos de `[vida.momentos]` quando existir — falta
  pôr a tabela `[vida.momentos]` no `persona/condessa-gosto.toml` e no `VIDA_PADRAO` (V0.8).
  A histerese guarda o candidato em `ctx["memo"]` (dicionário do chamador, mantido entre ticks) e o
  `[vida]` vem em `ctx["vida"]`, porque a assinatura `decidir(ctx, anterior, agora)` é fixa.
  `momento.sinais(...)` recebe por parâmetro o que o `Reactor` ainda não expõe (último turno do
  Pedro, última música, `claude_esperando/rodando`, `lm_on`, `alerta`, `faixa_agua`); `hora`,
  `humor_pedro`, `animo`, `energia`, `momento_ha_s`, contadores de franja/cantando e a escada do
  Tédio (`encarando_feito`, `ei_to_aqui_ha_s`, `ei_ignorado`) também ficam para a ligação (V0.8).
  Nomes de passivas novos em `GRUPOS` (`sacada_player`, `mao_no_queixo`, `flagra_no_forum`, `bocejo`,
  `cochilo`, ...) precisam bater com o catálogo na V0.7.
- **V0.4:** `repouso.rosto` + `repouso.fone_alvo(momento, ctx)` (CA-V5: sem música nunca E2; −1 só
  nos primeiros 8 s por `ctx["faixa_ha_s"]`; −2 nem põe). Quem chama `Postura`/troca de fone por passo
  de cena (P11) é a V0.8; `rosto` lê do `ctx`: `animo`, `energia`, `musica_nota`, `faixa_agua`,
  `episodio`, `momento_ha_s`. Repouso só vale parada de dia (`_resting`); sem `set_rest` o retrato é o
  de antes. Crossfade de 120 ms só na CPU (a GPU troca seco: `GLOp` não tem alfa). Fone no pescoço
  usa `extra/E3.png`. Efeitos de repouso: `braco:P10`, `sweat`, `olhando_pedro` (sem olhar solto).
  `COR_FAIXA` = cor do fundo (acordo §6): Radiante `#f2a7c3` (happy), as outras o acento `#b392f0`
  (calm). `Snapshot.mood_dela/mood_dela_cor/momento/causas` (causas = `(texto, Δ, há_s)`, montadas
  pela V0.8 a partir de `Humor.medidor()`). Hover: `Screen.hover_test/set_hover` + grupo `mood_tip`;
  falta o `gamerhud.py` chamar `hover_test`/`set_hover` no mouse move (V0.8).
- **V0.2:** a tabela de eventos está no acordo **§1** (a tarefa dizia §3); transcrita em
  `estado.EVENTOS` (tipos `faixa_nota2/1/_menos1/_menos2`, `ado`, `favorita`, `birra`, `pedro_volta`,
  `tag_elogio/zoeira/correcao`, `clique_carinho` ≤ 3/h, `claude_fim`, `commit`, `faxina`,
  `claude_erro`, `jogo_abriu`, `fps_episodio`, `fps_recuperou`, `truque_aplauso/ignorado`); o "1 por
  episódio" do FPS e o "> 5 min" do Claude ficam com quem emite (V0.6/V0.8). Trava ±0,6/h conta cada
  sentido separado. `tick` lê do `ctx`: `pedro_ausente_min`, `silencio_min`, `musica_nota`, `jogo`,
  `pedro_mal`, `momento`. A cor do medidor é um padrão por faixa (`estado.COR_FAIXA`), acordo §6 com
  a V0.4. Ao rodar, `test_vida_contratos::test_esqueleto_assinaturas` (episódio, V0.6) e
  `test_reacoes_governador::test_passiva_intervalo_40s` (V0.5) falhavam por arquivos em edição.
- **V0.5:** o `Governador` v2 (em `governador.py`) guarda os contadores em `hist` e os expõe por
  `exportar()`/`importar(dados, agora)` (dicionário JSON); a **V0.8** guarda isso no `Estado`. O
  `estado.py` era stub durante a V0.5 (a V0.2 estava nele), então ficou sem ligação.
- **V0.5:** o título da tarefa fala em "20 s" e "45 s"; valeram os números do `[vida]`/spec §5 (25 s e
  60 s). "Uma linha por tabela do acordo §1" foi lido como uma linha por regra do acordo §4 (o §1 é o
  humor, da V0.2).
- **V0.5:** as classes `CENA/GESTO/ATIVA_SOLTA/ATENCAO/CORPO` ficaram em `governador.Tipo` (o
  `contratos.Classe` não é da V0.5). Ficam para o diretor (V0.10): coalescência de 3 s, "de novo?"
  (mesma causa < 10 min), sorteio das passivas por `Governador.peso`, ligação de `ctx["causas"]` e
  `ctx["filtros"]`, e passar as 19 antigas pelo v2. Até lá, o `escolher` antigo só lê
  `passiva_min_s` (90 s) e `cenas_hora` do `ctx["vida"]`.
- **V0.5:** `test_vida_contratos::test_esqueleto_assinaturas` falhava porque a V0.2 estava no
  `estado.py`; não é da V0.5.
- **V0.6:** `hot`/`fps_drop` (34/36) e `game_off` (45) ainda saem pelo `Reactor._legado` em
  `reactions.py` (fora do *Escreve*): o `det_sistema` só decide e publica em `ctx["_sistema_cala"]`
  as chaves antigas a calar neste tick e em `ctx["_sistema_ep_estado"]` o estado (suor + `stress`);
  falta o `Reactor` consultar isso (V0.8/V0.11). Cobranças = cena do 1º episódio + `eu_avisei` +
  `fps_drop:vergonha`; recuperação = `hot:alivio`/`fps_drop:recuperou`; a "partida" fora de jogo é o
  tempo desde o último `game_off`. Relatório: com episódio sai `eu_avisei` (ou `desconfiada` se
  `ctx["pedro_mal"]`) e cala o `game_off`; sem episódio o `game_off` antigo é a vitória (o
  `P12 B4 C5 1500` do acordo ainda não está no catálogo). `game_off` aceita `pedro_mal=` (parâmetro
  novo). Atualizados `test_reacoes_sistema` (1 recuperação/partida) e a linha do episódio em
  `test_vida_contratos::test_esqueleto_assinaturas`.
- **V0.7:** em `momento.GRUPOS` (exceção autorizada), `presilha` → `brilho_presilha`; saíram por não
  ter equivalente no catálogo `mao_no_queixo` (P10; só a `indecisa` usa P10), `sacada_player` e
  `flagra_no_forum` (a `flagrada` é "flagrada olhando", outra coisa): falta criá-las no catálogo e
  voltar com elas aos grupos (a regra do P10 continua em `momento._cabe`). Ajustei 2 asserts do
  `test_vida_momentos` por isso. O `humor.py` virou só leitura (`momento`, `faixa`, `fone`, `filtros`,
  `sinais`); a faixa vem de `ctx["faixa_humor"]` ou `ctx["humor_estado"]` (porque `ctx["faixa"]` é a
  música) e o fone de `ctx["fone"]` (sem ele, E2 só com nota ≥ 0): a **V0.8** passa `momento`
  (com histerese), `faixa_humor`, `fone`, `energia`, `causas` e `ultima_expressao_em`. O piso de vida
  com grupo vazio ou cota cheia devolve `Disparo("atencao", "piso")`, que o diretor/Reactor ainda não
  resolvem (V0.8/V0.10). O que cada faixa tira (`passivas.FAIXA_BLOQUEIA`) e as causas de cada
  negativa (`passivas.NEGATIVAS`) são leitura minha do acordo §2 e spec §6. Não precisei de
  `[vida.momentos]` no gosto.
- **V0.10:** CA-V4 usa a rajada real (`reacoes.jsonl`, 21:05:08–21:06:23, 9 disparos, sem as
  passivas, que vêm do sorteio): dá **1 CENA** (`musica_comecou` ramo 2) e o resto vira atenção; o
  commit (`ideia`, outra causa) ainda pode sair como ativa solta depois dos 25 s (nesta rajada saiu).
  As roteiros ficam em `catalogo.CENAS` (fora de `DEFS`/`TODAS`, chave `(tipo, ramo)`), com
  `FAMILIA_CENA`, `NIVEL_CENA` e `SAIDA`; `_passos` ganhou `look:<painel>`. Não há `Classe.CENA` no
  `contratos` (não é meu): vale `governador.Tipo.CENA`. As sequências do episódio, do truque e da
  volta orgulhosa não têm notação no acordo (escolhi). A família cala também as ativas soltas
  (90 s música); o "de novo?" vem depois da absorção. `Diretor` ganhou `ctx` opcional em
  `receber`/`proxima`, `truque`, `clique`, `sortear_passiva` (peso do governador, negativas com
  `ctx["causas"]` + causas do diretor, `ctx["filtros"]`) e `tocando`. O beicinho do truque ignorado é
  continuação da cena (não passa pela cota). Para a V0.8: detectores emitem `musica_comecou`,
  `pulo` (`tocou_s`), `resposta_fim`, `claude_terminou` (`dur_s`), `episodio` (`primeiro`),
  `game_off` (`episodios`, `pedro_mal`), `pedro_voltou` (`cochilou`) e `causa` no `fmt`; as 19
  antigas já mapeiam em `diretor.ANTIGAS`. `test_vida_contratos::test_esqueleto_assinaturas` espera
  `NotImplementedError` em `Diretor.proxima` — falha agora; a linha deve sair (arquivo não é meu).
- **V0.8:** o tick é `_vida`: eventos de humor → `Humor.tick` → `momento.decidir` (memo no `ctx`) →
  `Diretor.receber/proxima` (1 cena por tick; o resto das `prontas` é descartado) → passivas (truque
  depois do aquecimento, `Disparo("atencao","piso")` = olhada dirigida para o card do momento) →
  `repouso.rosto` + fone (fora do lugar por 10 s sem cena = `recoloca_fone`/`musica_parou`, P11). O
  relógio da vida é o de parede no 1º tick andando com o `now` monotônico (`Reactor._rel`); o
  `Estado` grava a cada 60 s com `governador = {hist, boot}` (boot de `/proc/.../boot_id`). Sem
  `fire`/`say`: as 19 antigas viram `Disparo` (o rosto de antes só quando não há roteiro, via
  `_Diretor._cena`; com roteiro valem os passos da cena, com nome/humor/fala da antiga). Cliques em
  player/card = atenção; LED e "próxima" (`pulo`, `tocou_s`) vão pela fila ao próximo tick. Fora do
  *Escreve* (mínimo, para o verde): `gamerhud.face_move` chama `hover_test/set_hover` (repinta tudo
  com `update()`); testes antigos ajustados ao diretor (`test_wired_reactions`: helper sem ritmo e
  sem detectores, música em Jogando vira só olhada, `hot` olha o FPS; `test_reacoes_tick`,
  `test_reacoes_integracao` e `test_reacoes_governador`: 3 s de coalescência). Ficou para depois:
  `det_claude` emitir `claude_terminou` com `dur_s` (o Reactor extrai do `motivo` por regex) e o
  início do Claude (antiga `claude`) só vira atenção; `sobressalto`/`sentiu_falta` viram
  `pedro_voltou`; tags pelo `motivo` "turno: x"; clique carinhoso = duplo clique no retrato. Sinais
  ainda não ligados: `claude_esperando`, `lm_on`, `faixa_agua`, `dancante`, contadores de
  franja/cantando e a escada do Tédio (V0.3), e a tabela `[vida.momentos]` no gosto.
  `registro.gravar_antiga` ficou sem uso. CA-V9: tick médio ≈ 0,2 ms (1000 ticks, tudo ligado).
- **V0.8b:** `det_claude` emite `claude_terminou` (`fmt["dur_s"]`; a regex saiu do `_adaptar`) e põe
  `ctx["claude_esperando"]` a cada tick: vale do `notify` do hook até o próximo evento (`stop`/`fail`)
  ou `ESPERA_MAX_S` (30 min, leitura minha; o hook não avisa quando o Pedro responde, então a espera de
  permissão só fecha no `stop`). `lm_on` = `LearningModel.mode_on`, posto pela `integration` num
  campo novo `Snapshot.lm_on`. `dancante`/`faixa_agua` = `det_musica.dancante/faixa_agua` (gênero da
  lista `danca` em qualquer nota; título de água). Contadores e escada no `Reactor._contadores/_marcar`
  (só passivas que saíram contam; franja na espera zera com o momento, franja/cantando na faixa com a
  faixa). "Ignorada" = sem clique nela nem turno do Pedro em `escada_ei_resposta_s` (10 s, chave nova
  no `[vida.momentos]`, leitura minha); a causa `ignorada` (e `claude_esperando`) entra em
  `diretor.causas` enquanto vale; o beicinho limpa o ignorado. `momento.LIMIARES_PADRAO` agora é
  `VIDA_PADRAO["momentos"]`. Os limiares da escada contam `momento_ha_s` (tempo **no** Tédio, que só
  começa com 15 min sem música): encarando sai ~30 min sem música, não aos 15 — conferir na V0.9.
- **V0.9:** replay em `tests/hud/fixtures/dia-2026-10-09.json` (1,3 kB, só horários: música, faixa
  amada, jogo, quente→alívio, quedas de FPS, rodadas do Claude, hooks, commits, ausências e voltas;
  passivas antigas fora). O `Reactor` real roda com `det_tempo/musica/sistema/claude`, passo de 2 s,
  `rng` semente 1. Medido: 13,8 expr./h; 0 rajadas; maior buraco 5,6 min; 0 negativas sem causa;
  Contente 89 %, Radiante 8,5 %, Neutra 2,8 %, Emburrada 0; toda hora presente com positiva; 3/3
  voltas viram cena. Leituras minhas: "corpo" = troca de fone (`recoloca_fone`/`musica_parou`,
  `Tipo.CORPO`); a meta 3 não conta Jogando nem Conversa (spec §9: o piso não vale lá, e a média de
  Jogando é 8 min); negativas = acordo §4 + caretas com culpado (`impaciente`, `indiferente`,
  `desconfiada`, `eu_avisei`); o `encarando` da escada é degrau do Tédio, não careta; positivas são
  uma lista no teste (inclui `cabeca_ritmo` e o alívio do FPS/calor). **`[vida]` mudado** (gosto +
  `VIDA_PADRAO`): `piso_vida_min` 6 → 5,5 (o piso é "> N min" e o sorteio roda a cada 10 s, dava
  6,1 min); `pedro_sumido` −0,05/15 min → −0,10/10 min (com a meia-vida de 8 min abaixo da base, o
  −0,05/15 min estabiliza em +0,08 e ela nunca saía de Contente, então eram só 2 faixas no dia).
  **Bugs corrigidos** em `reactions.py` (fora do *Escreve*): (1) piso de vida recusado pelo
  governador não fazia nada e o `passivas.sortear` já contava o uso, o que dava buracos de 11–14
  min; agora vira atenção dirigida (spec §9); (2) a troca de fone (P11) passava por fora da cota e
  fazia rajada na volta (volta → fone → `game_on` em 26 s); agora espera `min_entre_expressoes_s`
  desde a última expressão. **Escada do Tédio** (acordo §3: Tédio = 15 min sem música, encarando aos
  15 min, ei aos 30): os degraus contam o tempo sem música (`min(sem_musica_ha_s, momento_ha_s +
  tedio_sem_musica_s)`), e o "ei" exige o encarando antes ("→" da escada). Ajustados
  `test_vida_momentos` (linhas da escada), `test_reacoes_governador::test_v2_piso_de_vida_6min` (lê
  o piso do cfg) e `test_vida_humor::test_pedro_sumido` (fixa os números antigos para testar o
  mecanismo). **Frágil:** a meta 6 depende do sorteio na hora das 14h (partida longa quase sem
  música; o grupo Jogando só tem positiva com música): falhou em 4 de 9 sementes. Fica para o
  Conselho decidir uma positiva em Jogando sem música (ex.: sorriso com FPS estável). Emburrada
  ficou em 0 %, então não precisei anotar a "birra fresca". Gosto do Pedro: `desligadas = []`.
- **V1.1:** as 3 entraram como `I21`–`I23` (sem sinal: ativas sem PNG novo). `mao_no_queixo` usa
  `braco:P10` (sem `extra/P10.png` o retrato já põe o braço da base — `test_wired_portrait`);
  `sacada_player` olha `look:player`; `flagra_no_forum` olha `look:history` (não há painel de
  fórum: o Conselho pode trocar o alvo) com D2 e é ZOEIRA. Fora do *Escreve*, o mínimo para ficar
  verde: `test_reacoes_catalogo` passou de 110 para 113 itens (`_N` até I23). `sacada_player` não é
  negativa em `passivas.NEGATIVAS` (sai em Aturando sem precisar de causa); se o Conselho quiser,
  entra lá com `faixa_nota_menos1`. As sequências foram escritas pelo agente, sem roteiro no
  acordo: revisar junto com as 3 cenas da V0.10.
- **Placar e jogo (Conselho 2026-10-10) — do Pedro, não de agente:** (1) calibração depois de 7 dias
  de log: o Pedro ganha 40–60 % dos dias, senão mexer nos **tetos** de `[vida.placar]`; (2) conferir
  na tela o hover/✗ (V1.8), o `O1` de frente nas cenas e os roteiros novos; (3) decidir o atalho de
  teclado e se o truque pode mexer no fone (`mexe_no_fone`); (4) **recomendadas pelas três** (não
  implementar sem ele): "pose de vitória" como 3º número do truque, "bebe água", linha do ânimo do
  dia no hover; (5) clique do meio no rosto para "a última, agora" (só a Asuka assinou) e "dia com
  ≥ 1 commit" +1 Pedro (só a Kurisu); (6) bis do truque: reavaliar com 1 semana de dados (Aqua).
- **V1.5:** `sem_sentido.SemSentido(vida, caminho, negativas)` (passar `passivas.NEGATIVAS`):
  `marcar(alvo, gesto, agora)` (alvo = linha do `reacoes.jsonl`; o mesmo alvo de novo em ≤
  `desfazer_s` desfaz), `desfazer(agora)`, `fatores(momento, agora)` (chave = `alvo["chave"]`, que é o
  que o sorteio pesa), `ajustes(agora)`, `pauta(agora, ocorrencias)` (a fração precisa das ocorrências
  da variante na janela — quem chama conta no `reacoes.jsonl`) e `exportar(agora)` para o `Estado`.
  Ajustável = `tipo` `gesto`/`passiva` fora das negativas; `cena` e negativas vão à pauta com 1 marca;
  `ativa`/`atencao`/`repouso` só pela regra de marcas/fração. A reação é a constante `REACAO`
  (`B7 C12 ?` 700, sem ânimo/placar/ritmo): falta o diretor tocá-la, o atalho (`atalho` vazio no
  `[vida.sem_sentido]`), o ✗ do hover, a voz e o `semente` na linha de origem (o `_log` ainda não grava)
  — V1.7/V1.8. Ao rodar, `test_reacoes_catalogo::test_113_itens_chaves_unicas` e
  `test_vida_diretor::test_pedro_voltou_corta_e_escolhe_ramo[orgulhosa]` falhavam pelo `catalogo.py`
  em edição (V1.2).
- **V1.4:** `placar.Placar(vida)`: `pontuar(fonte, ref, agora)` → `Ponto` (`linha` pronta via
  `registro.linha_placar`; grava com `registro.gravar_placar`) e `virada` (`{chave, causa:
  placar:virada, lado, ref}`; virada = líder estrito troca, o 1º líder do dia não conta); `ativo(agora,
  ref)` só entre `ativo_depois_h` e `fecha_dia_h`; `resumo()`, `linha_pos_batalha(ponto)`, `bom_dia()`,
  `exportar()/importar()` (guarda 14 dias). Nomes das fontes = chaves de `[vida.placar] tetos`; o
  `ref` é obrigatório (formato do id da linha de origem fica com a V1.7). Frase pós-batalha do ponto
  dela ("Suou nessa, hein? Ponto meu.") e as do "bom dia" sem empate/derrota dela são do agente, não
  do acordo — revisar. Ao fechar: `test_vida_diretor::test_pedro_voltou_corta_e_escolhe_ramo[False-
  orgulhosa-F1]` e `test_vida_simulacao::test_escada_encarando_aos_15_min_sem_musica` vermelhos pelos
  arquivos em edição da V1.2/V1.5 (não tocados aqui).
- **V1.2:** `torcida` = `I24` (tela do jogo; "íris para o lado do jogo" virou `look:fps`, o painel do
  jogo — o Conselho pode trocar) e `I25` (`("torcida", "punho")`); `catalogo.TORCIDA` lista as 2 e
  `catalogo.com_suor(d)` põe `D2` em todos os passos (quem sabe do episódio aberto chama: V1.6/V1.7).
  O Δ +0,03 e o `no_sorteio` do `[vida.torcida]` não são lidos aqui (governador/passivas, V1.6/V1.7);
  a lista de positivas do `test_vida_simulacao` ainda não tem `torcida` (V1.10). Notação do acordo
  no `_passos`: `O1` = `iris:B1` (testado no retrato num passo de cena: funciona, `contratos.py`
  intocado), `rubor` = `D1`, `!` = `D5`, `?` = `D4`. Truque: `("truque", None)` = piscadinha (o
  diretor de hoje pega esse), mais `fone`, `fone_inverso`, `piscadinha`, `aplaudido` (nível 3, como
  o ignorado) — a alternância e o `mexe_no_fone` são da V1.3. Volta: `orgulhosa` (4 passos),
  `orgulhosa_2` (2ª volta); a de ≥ 2 h tem 5 passos e ficou fora de `CENAS` (o
  `test_vida_diretor::test_roteiros_validos` limita a 4) como `catalogo.VOLTA_LONGA`, e a 3ª volta
  como `catalogo.VOLTA_ATENCAO` (`O1 B1 C10` 600 — duração do agente). Fora do *Escreve*:
  `test_vida_diretor::test_pedro_voltou_corta_e_escolhe_ramo` conferia o roteiro antigo da volta
  (ajustado para o novo). `test_vida_simulacao::test_escada_encarando_aos_15_min_sem_musica` falha
  também no HEAD limpo, sem a V1.2 (não mexi).
- **V1.6:** `torcida.Torcida(vida)`: `atualizar(agora, jogo=, presente=)` a cada tick (o relógio só
  anda com jogo aberto e Pedro presente; pausa fora disso, não zera), `positiva(agora)` em toda positiva
  da lista da meta 6, `no_slot(agora, momento, gov)` no slot de passiva em Jogando (≥ 30 min → `Escolha`
  com a variante, causa `jogando_sem_positiva:<min>`, Δ do `[vida.torcida]`; `None` = sorteia) e
  `fora_do_slot(...)` entre slots (≥ 45 min). As duas passam pelo `Governador` como `Tipo.GESTO`
  (ocupam a vaga do teto de 12/h); o fora de slot usa `Pedido(fora_de_slot=True)`, que só pula o
  `passiva_min` (25 s e 60 s pós-cena valem). A `torcida` do sorteio também chama `registrar(agora, var)`
  (intervalo de 30 min e alternância contam as duas origens). Não existe número "≤ 4/h de Jogando" no
  `[vida]` (só `passiva_media_min.jogando` = 8): o teto é o de 12/h. Falta (V1.7): o Reactor chamar,
  aplicar `catalogo.com_suor` com episódio aberto, `exportar/importar` no `Estado`. Ao fechar,
  vermelhos por arquivos em edição de outras tarefas (passivas.py da V1.2b, det_tempo/diretor da V1.3):
  `test_v11_sorteio_das_novas_fica_no_grupo[flagra_no_forum]`, `test_19_cabeca_pesada_sessao_longa_de_madrugada`,
  `test_passivas_aceitam_fatores`, `test_replay_do_dia_real_bate_as_7_metas`.
- **V1.2b:** causa: não era regressão de um commit, era sorte. O degrau da escada entrava no sorteio
  como mais uma passiva do Tédio (1 em ~5, hora marcada exponencial de 5 min); com a semente 7 o
  encarando caía nos 15–20 min por acaso (20 sementes no código antigo: só 6 na janela, até 41 min),
  e qualquer consumo novo do `rng`/candidato novo (`flagra_no_forum`, truque, torcida) o empurrava
  para 26,5 min. Correção em `passivas.py`: o degrau que cabe (`ESCADA`, via `permitidas`) sai no
  próximo tick e ganha o sorteio, só quando o chamador acompanha a escada (`encarando_feito` no
  `ctx`, o `Reactor`) e com `passiva_min_s` desde o último sorteio (recusa do governador não insiste).
  Agora: encarando a 15,5–17 min nas 20 sementes, `ei_to_aqui` a 31–32 min. Fora do *Escreve*, o
  mínimo: o replay (`POSITIVAS` de `test_vida_simulacao`) passou a contar `torcida` como positiva
  (acordo-pj §1, ela existe para a meta 6); a hora 14 do replay é só Jogando e passava pela sorte de
  um `cabeca_ritmo`. `ruff check` do repo acusa `hud/konsole_term.py:395` (E501), alheio a esta tarefa.
- **V1.3:** `Estado.truque = {numero, dia}` (salvo/carregado); `Diretor.numero_truque(agora)` = o 1º
  de `[vida.truque] numeros` ≠ o de ontem (dia = `atividade.dia_local`, meia-noite; não o
  `fecha_dia_h` do placar), sem `fone` com `mexe_no_fone = false`; com ela sem fone sai
  `fone_inverso` (grava `fone`). `truque` recusa com `ctx["jogo"]` verdadeiro (a V1.7 precisa pôr
  `jogo` no `ctx` do diretor). O clique na janela agora toca `("truque","aplaudido")` (continuação,
  fora da cota, como o ignorado). Ganchos: `Diretor.ganchos_truque` (lista de `f(lado, agora)`,
  `lado` = `aplaudido`/`ignorado`), chamados por `Diretor.truque_fim` — a V1.7 liga o placar
  (`ela_truque_aplaudido`/`ele_truque_ignorado`). Os Δ do truque e da volta seguem os de
  `estado.EVENTOS` (iguais ao `[vida.truque]`/`[vida.volta]`; o `Humor` não lê essas chaves), e o
  Δ da volta é aplicado pelo `Reactor` (`EVENTO_DE`), igual em todos os degraus: falta a V1.7
  aplicar +0,10 na 2ª e nada na 3ª (o `Cena.ramo` diz qual: `orgulhosa`/`orgulhosa_longa`/
  `orgulhosa_2`/`atencao`). Volta: `det_tempo` emite o 62 `sentiu_falta` também para ≥ `fora_min`
  (antes só ≥ 2 h), com `fmt["fora_s"]`; o `Reactor._adaptar` descarta o `fmt`, então o diretor
  lê o tempo do motivo (`depois de X h`) — a V1.7 deve repassar o `fora_s`. Contador de voltas em
  `Diretor.voltas` (só memória; o cochilo não conta); a 3ª vira `Cena("pedro_voltou","atencao")`
  com `catalogo.VOLTA_ATENCAO`, registrada no governador como `ATENCAO`.
- **V1.7:** API para a UI/voz: `Reactor.placar_resumo()` (`{texto, ultimos}` do `Placar.resumo`),
  `Reactor.ajustes()` (N), `Reactor.ultimas_expressoes(n=3)` (linhas de expressão `gesto`/`cena`/
  `ativa`/`atencao`, só memória, ≤ 10) e `Reactor.marcar_sem_sentido(alvo=None, gesto="atalho",
  now=None)` (alvo None = a última expressão, sem nenhuma `nenhum`; com `now` toca a `REACAO` direto
  no `Reactor`, fora do diretor/governador/ânimo e sem linha no `reacoes.jsonl`). `ref` do ponto =
  `<hora local ISO>#<origem>` (`game_off`, `faixa:<título>|<artista>`, `truque:<lado>`, `ativo`), não
  o id exato de uma linha gravada. A linha do placar ganha `tipo: placar` e `momento` no `Reactor`
  (o `registro.linha_placar` não tem `tipo` e o `test_vida_sobras` lê `tipo`). Fim de partida:
  `Episodio.partida_desde`/`fim_partida` + `episodio.fonte_placar`; música: `det_musica` põe
  `ctx["_musica_fim"]` (`nota`, `ate_fim`, `pulo`, `especial` = Ado/Favorita) e o `Reactor` consome.
  "Ativo depois da 1h" = `inatividade_s` < 60 s. Pós-batalha e "bom dia" (`det_tempo` leva
  `ctx["placar_bom_dia"]` no `fmt`) trocam a legenda da expressão que já sai (`_falar_placar`).
  Virada toca no próximo slot de passiva (recusada = só número); `soprando_franja` usa a causa
  `placar:virada` em `diretor.causas`. Volta: `fora_s` repassado no `_adaptar`; o Δ sai na cena pelo
  `Cena.ramo` (`pedro_volta`; `orgulhosa_2` → `pedro_volta_2` +0,10 novo em `estado.EVENTOS`; 3ª nada)
  — se a cena não toca (MAGI falando, suprimida), não há Δ. `torcida`: Δ por `estado.EVENTOS
  ["torcida"]` (+0,03, cópia do `[vida.torcida]`, como o truque) no piso e no sorteio; `com_suor`
  com `ctx["episodio"]`; positivas = `reactions.POSITIVAS` (cópia da lista do replay). `Estado`
  ganhou `placar`/`sem_sentido`/`torcida`. `jogo` já estava no `ctx` do diretor. `diretor.py` não
  mudou (o `Reactor` se inscreve em `ganchos_truque`). Falta: `semente` na linha de origem, a
  `pauta` com ocorrências contadas no `reacoes.jsonl`, a voz ("qual o placar?", V1.9) e conferir na
  tela.
- **V1.8:** hover do medidor (`main_screen.tip_linhas`, de cima para baixo): placar e os 3 últimos
  pontos, "ajustes: N", as 3 causas do ânimo (como antes) e as 3 últimas expressões (a mais nova em
  cima: `chave (causa|motivo) · há X`) com ✗ à direita (`tip_x_rects`). `Snapshot.placar/
  placar_ultimos/ajustes/expressoes` preenchidos em `WiredUI._hover_dados` a cada tick. Com o hover
  aberto a caixa dele também conta como hover (o ponteiro chega ao ✗); `WiredUI.hit` → alvo
  `sem_sentido:<i>` → `on_click` chama `marcar_sem_sentido(alvo, "hover", now)` (não vira clique
  para ela olhar). Atalho: só local, no `keyPressEvent` do HUD (sem KGlobalAccel/D-Bus; só funciona
  com a janela do HUD em foco, e ela fica abaixo das outras) — tecla = `[vida.sem_sentido] atalho`
  (QKeySequence, ex. `"Ctrl+Shift+X"`); **vazio = sem atalho** (o comentário do gosto diz "vazio = o
  padrão": não há padrão; **a tecla e se precisa ser global são do Pedro**). Fora do *Escreve*, o
  mínimo: `hud/wired/standby_screen.py` (o hover da espera usa o `_g_mood_tip` da base pelo
  `tip_anchor`). A caixa do hover cresceu de 3 para até 11 linhas (`TIP_MAX`, ~202 px acima do pé
  do medidor): conferir na tela (Pedro).
