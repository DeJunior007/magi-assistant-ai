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
