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

- [ ] **V0.4 Repouso, fone persistente e medidor** — `repouso.py` (`rosto`, `Postura`); retrato com
  `set_rest` e fone persistente (design §3); medidor do humor dela no painel e na espera
  (`Snapshot.mood_dela`, design §4).
  - Lê: spec §4, acordo §2 (repouso), §3 (momentos) e §6 (medidor), design §3–§4, `hud/wired/portrait.py` por trecho (`_reacting`, `eyes_id`, `mouth_id`, fone), `hud/wired/main_screen.py` por trecho (termômetro), `hud/wired/standby_screen.py` (`_g_mood`)
  - Escreve: `hud/wired/reacoes/repouso.py`, `hud/wired/portrait.py`, `hud/wired/main_screen.py`, `hud/wired/standby_screen.py`, `tests/hud/test_vida_repouso.py`
  - Depende de: V0.2, V0.3
  - Orçamento: ~55k
  - Pronto: CA-V5 (parte do retrato) e CA-V8 verdes (medidor com nome do momento e 3 causas no hover); crossfade de 120 ms; testes do retrato antigos sem mudar asserção.
  - Paralelo: V0.6, V0.7

- [ ] **V0.5 Governador v2** — números do `[vida]`, classes CENA/GESTO/ATIVA_SOLTA, mínimo de 20 s
  (exceções), assentamento de 45 s, cotas, mesma passiva, mesmo tipo de cena, negativas com causa
  (spec §6), contadores persistidos no `Estado` e janelas por tempo de parede.
  - Lê: spec §5–§6, acordo §4, `hud/wired/reacoes/governador.py`, `vida.py`, `estado.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/governador.py`, `tests/hud/test_reacoes_governador.py` (casos novos; os antigos que contradizem o acordo novo são atualizados e listados no commit)
  - Depende de: V0.1
  - Orçamento: ~55k
  - Pronto: CA-V2 (contadores) e um teste por linha da tabela do acordo §1; 24 h simuladas sem violação.
  - Paralelo: V0.2, V0.3, V0.6

- [ ] **V0.6 Episódio de jogo** — `episodio.py` (spec §7) e o `det_sistema` passa a usá-lo (sem
  `hot`/`fps_drop` repetidos).
  - Lê: spec §7, acordo §5 (episódio e relatório), `hud/wired/reacoes/det_sistema.py`, `vida.py`
  - Escreve: `hud/wired/reacoes/episodio.py`, `hud/wired/reacoes/det_sistema.py`, `tests/hud/test_vida_episodio.py`
  - Depende de: V0.1
  - Orçamento: ~45k
  - Pronto: CA-V7 verde; testes antigos do `det_sistema` atualizados onde o acordo mudou a regra.
  - Paralelo: V0.2, V0.3, V0.5

- [ ] **V0.7 Passivas por momento e faixa** — `passivas.sortear` passa a escolher só no grupo do
  momento ∩ faixa, com o intervalo do `[vida]`, as negativas com causa e gestos de fone/ritmo só com
  música e E2; o `humor.py` antigo (fatores) vira só leitura do momento/faixa ou é aposentado.
  - Lê: spec §3, §6, §9, acordo §3–§4, `hud/wired/reacoes/passivas.py`, `hud/wired/reacoes/humor.py`, `momento.py` e `estado.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/passivas.py`, `hud/wired/reacoes/humor.py`, `tests/hud/test_reacoes_passivas.py`
  - Depende de: V0.2, V0.3, V0.5
  - Orçamento: ~45k
  - Pronto: 10 000 sorteios por momento × faixa nunca saem do grupo; nenhuma negativa sem causa; nenhum gesto de fone/ritmo sem música; piso de vida de 6 min.
  - Paralelo: V0.4, V0.6

- [ ] **V0.10 Diretor de cenas** — `diretor.py` (spec §8) e os roteiros de cena do acordo §5 no
  `catalogo.py` (classe CENA, ramos); fila, interrupção, absorção, troca de fone atômica.
  - Lê: spec §1, §8, acordo §4–§5, `hud/wired/reacoes/catalogo.py` por trecho, `vida.py`, `governador.py` e `estado.py` (assinaturas)
  - Escreve: `hud/wired/reacoes/diretor.py`, `hud/wired/reacoes/catalogo.py`, `tests/hud/test_vida_diretor.py`
  - Depende de: V0.2, V0.5
  - Orçamento: ~60k
  - Pronto: CA-V4 verde (rajada real das 21:05 → 1 cena); um teste por cena do acordo §5; coalescência, família, "de novo?", atenção dirigida, truque de salão, fila/interrupção/absorção.
  - Paralelo: V0.4, V0.7

- [ ] **V0.8 Ligação no Reactor** — o tick passa a ser estado → momento → diretor → passivas →
  repouso; as 19 antigas entram pelo diretor (fim do `fire` direto); eventos de humor emitidos pelos
  detectores; log com `momento`/`faixa`/`animo`/`energia`/`tipo`; relatório atualizado (spec §9);
  "HUD acordou" uma vez por boot.
  - Lê: design §2, spec §9, *Sobras*, `hud/wired/reactions.py` (por trecho), assinaturas de `estado`, `momento`, `repouso`, `diretor`, `episodio`, `passivas`, `governador`
  - Escreve: `hud/wired/reactions.py`, `hud/wired/integration.py`, `hud/wired/reacoes/registro.py`, `hud/tools/reacoes_relatorio.py`, `tests/hud/test_vida_integracao.py`
  - Depende de: V0.4, V0.6, V0.7, V0.10
  - Orçamento: ~60k
  - Pronto: CA-V9; `tests/hud` inteiro verde; teste de ponta a ponta com `Reactor` real e `Snapshot` sintético (música amada → 1 cena + sorriso de repouso pela faixa + medidor subindo).
  - Paralelo: —

- [ ] **V0.9 Validação** — CA-V6 (simulação de 12 h a partir do `reacoes.jsonl` real reconvertido em
  acontecimentos), religar no gosto do Pedro o que foi desligado à mão (`[reacoes] desligadas`),
  roteiro da semana em `docs/perf/reacoes.md` atualizado. **A semana de uso é do Pedro.**
  - Lê: requirements (Critérios), spec §9–§10, `docs/perf/reacoes.md`
  - Escreve: `tests/hud/test_vida_simulacao.py`, `docs/perf/reacoes.md`, `~/.config/magi/condessa-gosto.toml` (só tirar `fone_repouso`, `ajeitando_fone`, `cabeca_ritmo` de `desligadas`)
  - Depende de: V0.8
  - Orçamento: ~40k
  - Pronto: CA-V6 = as **7 metas do acordo §8** verdes no replay do dia real (se a Emburrada passar de 15 %, anotar: a Kurisu pediu para a "birra fresca" voltar à mesa); o Pedro avisado do que conferir.
  - Paralelo: —

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
- **V0.2:** a tabela de eventos está no acordo **§1** (a tarefa dizia §3); transcrita em
  `estado.EVENTOS` (tipos `faixa_nota2/1/_menos1/_menos2`, `ado`, `favorita`, `birra`, `pedro_volta`,
  `tag_elogio/zoeira/correcao`, `clique_carinho` ≤ 3/h, `claude_fim`, `commit`, `faxina`,
  `claude_erro`, `jogo_abriu`, `fps_episodio`, `fps_recuperou`, `truque_aplauso/ignorado`); o "1 por
  episódio" do FPS e o "> 5 min" do Claude ficam com quem emite (V0.6/V0.8). Trava ±0,6/h conta cada
  sentido separado. `tick` lê do `ctx`: `pedro_ausente_min`, `silencio_min`, `musica_nota`, `jogo`,
  `pedro_mal`, `momento`. A cor do medidor é um padrão por faixa (`estado.COR_FAIXA`), acordo §6 com
  a V0.4. Ao rodar, `test_vida_contratos::test_esqueleto_assinaturas` (episódio, V0.6) e
  `test_reacoes_governador::test_passiva_intervalo_40s` (V0.5) falhavam por arquivos em edição.
