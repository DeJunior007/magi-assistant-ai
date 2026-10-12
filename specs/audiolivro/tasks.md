# Tarefas — Audiolivro da Condessa

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `A` (ex.: `A6.1`).
2. **Orçamento planejado ≤ 50k tokens**; o resto da janela de 128k é margem. Perto de 90k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use `magi/audiolivro/contratos.py` e as assinaturas dos stubs; não leia
   o código de outras tarefas além do que o *Lê* manda.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `magi/core/turn.py`, `magi/core/router.py`, `magi/core/intents.yaml`, `magi/core/tts.py`,
   `magi/providers/registry.py`, `magi/common/contracts.py`, `magi/core/assemble.py`,
   `magi/agent/tools/news.py`.
6. **Testes curtos:** `uv run pytest -q -x tests/audiolivro/<arquivo>` (e o teste antigo do arquivo
   que você mexeu) e `uv run ruff check <seus arquivos>`. Relógio injetado; nada de `sleep` real.
7. **Nada ao vivo:** sem chamar LLM nem TTS de verdade (backend falso), sem reiniciar `magi-core`/
   satélite, sem tocar áudio, sem ler `~/Livros` real nos testes (fixtures geradas em
   `tmp_path`); nada em `~/.local`/`~/.config` reais (caminhos injetáveis; o `conftest.py` isola).
   Nunca `qdbus`/`gdbus` para KGlobalAccel/KWin.
8. **Uma tarefa = um commit** direto no `main`, mensagem começando com o ID (`A1.2: marcação por
   regras`) e terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem push.
   Marque `- [x]` no mesmo commit.
9. **Texto do livro é sagrado (A9):** nenhum código muda, resume ou traduz o texto; só marca.

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~2,5k,
`design.md` ~2k, `spec.md` ~4k, `turn.py` ~12k (991 linhas: só por trecho), `tts.py` ~6k,
`router.py` ~7k, `intents.yaml` ~8k.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

Decisões do Pedro de 2026-10-10 aplicadas (`specs/DECISOES-2026-10-10.md`): Kokoro sempre, regras +
Qwen local, `~/Livros`, música pausa, sempre a voz dela, `pymupdf`. A A1.3 entrou no caminho.

```
A0.1 ─┬─ A1.1 (EPUB/PDF) ─┬─ A1.2 (marcas + elenco de vozes) ─┐
      │                   └─ A1.4 (biblioteca, marcador, tempo) ┤
      ├─ A1.3 (refino Qwen local) ──────────────────────────────┤
      └─ A2.1 (TTS Kokoro por trecho) ──────────────────────────┴─ A2.2 (Leitura + narrate) ── A2.3 (intents + handler) ── A3.1 (Pedro)
```

Ondas com *Escreve* disjunto: **1)** A1.1 ‖ A1.3 ‖ A2.1 · **2)** A1.2 ‖ A1.4 (‖ o que sobrou da
onda 1) · **3)** A2.2 · **4)** A2.3. A3.1 é do Pedro (não implementar).

---

## Fase A0 — Contratos

- [x] **A0.1 Contratos, config e esqueleto** — pacote `magi/audiolivro/` com `contratos.py`
  (spec §1), `config.py` (spec §6, padrões quando a seção falta), stubs com assinatura final e
  docstring da tarefa dona: `epub`, `pdf`, `frases`, `biblioteca`, `marcas`, `marcas_llm`,
  `vozes`, `custo`, `marcador`, `leitor`, `handler`; `verbos.toml` e `vozes.toml` vazios com o
  cabeçalho do formato; `tests/audiolivro/conftest.py` isolando estado/cache em `tmp_path`;
  `pymupdf` no `pyproject.toml` (D6). Config com os padrões das decisões: `pasta = ~/Livros`
  (criada ao usar, D3), `marcacao = "qwen"` (D2), `musica = "pausa"` (D4), `voz_dela`/`idioma_dela`
  do `[tasks].tts` Kokoro (D5), `audiolivro_marca` só local. *(A1–A10)*
  - Lê: design §2, spec §1 e §6, `magi/learning/model.py` linhas 1–40 (padrão de tarefa fora do `ProviderTask`)
  - Escreve: `magi/audiolivro/*`, `tests/audiolivro/conftest.py`, `tests/audiolivro/test_contratos.py`, `pyproject.toml` (só a dependência), `uv.lock`
  - Depende de: —
  - Orçamento: ~30k
  - Pronto: `import magi.audiolivro.<cada módulo>` funciona; config com e sem a seção; provedor pago na marcação recusado; `ruff` limpo.
  - Paralelo: —

## Fase A1 — Texto, marcas, custo

- [x] **A1.1 Leitores EPUB e PDF** — `epub.py` (OPF → spine → XHTML; pula `nav`/`toc`/notas
  `epub:type="footnote|endnote"`; `<h*>` vira parágrafo título; itálico marcado para A1.2 com
  um atributo no `Paragrafo` ou marca `\x1e` documentada), `pdf.py` (`pymupdf`/`fitz`, D6, texto por
  blocos na ordem de leitura; junta hifenização;
  tira linhas que repetem em ≥ 60% das páginas no topo/rodapé e números de página; capítulo por
  linha-título ou, sem achar, blocos de 10 páginas; "sem texto" se < 200 caracteres em 5 páginas),
  `frases.py` (abreviações Sr./Dra./etc./Mr./Dr.; reticências; não quebra dentro de aspas abertas).
  Metadados: título, autor, idioma (`dc:language`; PDF por contagem de palavras-função PT/EN). *(A1.2, A2)*
  - Lê: spec §1, requirements A1–A2, `magi/audiolivro/contratos.py`
  - Escreve: `magi/audiolivro/epub.py`, `pdf.py`, `frases.py`, `tests/audiolivro/test_epub.py`, `test_pdf.py`, `test_frases.py`
  - Depende de: A0.1
  - Orçamento: ~45k
  - Pronto: CA-A1 (fixtures geradas no teste); PDF escaneado → erro `SemTexto`; ≥ 25 casos de frases.
  - Paralelo: A2.1

- [x] **A1.2 Marcação por regras e elenco de vozes** — `marcas.py` (spec §2, inclusive idade),
  `verbos.toml` (PT e EN), `vozes.py` + `vozes.toml` (spec §3, D1/D5): narração na voz dela;
  `Elenco` por livro (falante normalizado → voz Kokoro do grupo gênero × idade no idioma dela,
  ≠ voz dela, persistido em `estado_dir/audiolivro/elenco/<id>.json`, atômico); fala sem falante →
  voz do gênero; velocidade e `pausa_ms` pela emoção; juntar trechos iguais até 400 caracteres.
  Nunca voz paga. *(A3, A4)*
  - Lê: spec §1–§3, requirements A3–A4, `magi/audiolivro/contratos.py` e `config.py`, `magi/providers/kokoro_provider.py` linhas 1–40 (formato de voz misturada)
  - Escreve: `magi/audiolivro/marcas.py`, `verbos.toml`, `vozes.py`, `vozes.toml`, `tests/audiolivro/test_marcas.py`, `test_vozes.py`
  - Depende de: A1.1 (só o formato do itálico no `Paragrafo`)
  - Orçamento: ~50k
  - Pronto: CA-A2 e CA-A3 verdes (elenco reaberto devolve as mesmas vozes; 5 personagens → 5 vozes distintas).
  - Paralelo: A1.4, A1.3, A2.1

- [x] **A1.3 Refino pelo Qwen local (D2; no caminho)** — `marcas_llm.py`: por capítulo, manda os
  parágrafos **numerados** e os trechos das regras ao Qwen local (`[tasks].audiolivro_marca`,
  provedor `qwen`; outro provedor → recusa e só regras); o modelo devolve só JSON de `Marca`
  `[{par, i, tipo, emocao, falante, genero, idade}]` (nunca texto); valida (índices existem, enums
  válidos) e mescla nos `Trecho`s das regras; roda em segundo plano à frente da leitura (capítulo
  atual + próximo), nunca bloqueia; liga o `magi-qwen` pelo `ContainerRuntime` de
  `magi/learning/runtime.py` quando preciso (injetado; `stop()` só se foi ele que ligou); cache por
  livro/capítulo em `cache_dir`. Qwen fora do ar, timeout ou JSON inválido → regras (A3.1). Sem
  custo, sem `Budget`, nunca LLM pago. Prompt em `magi/audiolivro/prompts/marcas.md`. *(A3.1, A7.2)*
  - Lê: spec §1, §2 e §6, requirements A3.1, `magi/audiolivro/contratos.py` e `config.py`, `magi/learning/model.py` (por trecho: `grep -n "def \|class "`), `magi/learning/runtime.py` linhas 1–30 e `grep -n "def "`
  - Escreve: `magi/audiolivro/marcas_llm.py`, `magi/audiolivro/prompts/marcas.md`, `tests/audiolivro/test_marcas_llm.py`
  - Depende de: A0.1 (usa só os contratos; testes com `Trecho`s feitos à mão)
  - Orçamento: ~45k
  - Pronto: modelo falso com resposta boa, com índice inválido, com texto em vez de JSON, com timeout e com container que não sobe → resultado certo em cada caso; cache reaproveitado (0 chamadas na 2ª vez); `[tasks].audiolivro_marca` com `openai` → 0 chamadas.
  - Paralelo: A1.1, A2.1 (e A1.2, A1.4)

- [x] **A1.4 Biblioteca, marcador e tempo** — `biblioteca.py` (varre `[audiolivro] pasta`,
  `~/Livros` por padrão, criando-a se não existir (D3); cache do índice em
  `cache_dir/indice.json` por mtime; `achar(fala) -> list[(Livro, nota)]` com
  normalização sem acento, sem artigos e casamento por tokens; ambíguo = 2 notas a < 0,1),
  `marcador.py` (spec §1 `Posicao`; atômico com `.bak`; ≤ 1 escrita/2 s; registro `audiolivro.jsonl`
  com giro de 5 MB), `custo.py` (spec §4: só tempo; custo de API = 0, sem `Budget`). *(A1, A1.1, A5, A7.1, A10)*
  - Lê: spec §1, §4, §6, requirements A1, A5, A7, A10, `magi/audiolivro/contratos.py` e `config.py`
  - Escreve: `magi/audiolivro/biblioteca.py`, `marcador.py`, `custo.py`, `tests/audiolivro/test_biblioteca.py`, `test_marcador.py`, `test_custo.py`
  - Depende de: A1.1
  - Orçamento: ~40k
  - Pronto: CA-A4, CA-A5; 10 títulos de teste (com acento, artigo, subtítulo, número) achados; pasta ausente criada (em `tmp_path`).
  - Paralelo: A1.2, A1.3, A2.1

## Fase A2 — Voz e controle

- [x] **A2.1 TTS Kokoro com opções por trecho** — `GuardedTts.com_opcoes(**over)` (cópia com
  `CallCtx` mesclado: `voice`, `speed`, `lang`; mesma pool, `whole_sentence` preservado) e
  `PhraseSpeaker.say_parts(parts, link, *, personal, on_sentence)` (fluxo de `(texto, OpcoesVoz)`;
  cada parte com as opções dela; `pausa_ms` vira silêncio PCM depois da parte; `on_sentence` com
  índice contínuo; nada vai ao cache de frases). Montagem de um `GuardedTts` **Kokoro** para o
  livro quando o `[tasks].tts` ativo não é Kokoro (D1: o livro nunca usa TTS pago). *(A4, A7)*
  - Lê: design §1–§2, spec §1 (`OpcoesVoz`), `magi/core/tts.py` linhas 224–335 e 408–490, `magi/providers/registry.py` linhas 225–280 e `grep -n "class _Guarded" -A40`
  - Escreve: `magi/providers/registry.py`, `magi/core/tts.py`, `tests/core/test_tts_partes.py`
  - Depende de: A0.1
  - Orçamento: ~40k
  - Pronto: CA-A8 (inclui `pausa_ms` → silêncio do tamanho certo); com `[tasks].tts` OpenAI o TTS do livro sai Kokoro; `tests/core/test_tts*.py` e `tests/providers/` antigos verdes.
  - Paralelo: A1.1, A1.3, A1.2, A1.4

- [x] **A2.2 Leitura e narração no turno** — `leitor.py` (`Leitura`: `abrir(livro, posicao)`,
  `partes()` assíncrono frase a frase com marcas (regras; marcas do Qwen quando o cache do
  capítulo já existe, sem esperar) + `Elenco`, `interrompida()`, `voltar(n)`, `pular(n)`,
  `capitulo(delta|n)`, `velocidade(delta)`, `estado`; dispara o refino A1.3 do capítulo atual e do
  próximo; cache PCM dos 3 últimos parágrafos) e `TurnMachine.narrate(leitura)` +
  `TurnContext.reading` (design §4; sem janela de continuação; pausa em call, A8.4). Retomada
  depois de comando de leitura pelo resultado com `ARG_NARRATE`. *(A3.1, A5, A6.2, A8)*
  - Lê: design §3–§5, spec §1, requirements A5–A8, `magi/audiolivro/contratos.py` + assinaturas de `marcas`, `marcas_llm`, `vozes`, `marcador`; `magi/core/turn.py` por trecho: `grep -n "def announce\|def wake\|def _go\|_followup\|in_call\|class TurnContext" ` e só esses intervalos (±40 linhas); `magi/common/contracts.py` `grep -n "class TurnContext" -A30` e `grep -n "ARG_QUIET\|ARG_ALSO_YES"`
  - Escreve: `magi/audiolivro/leitor.py`, `magi/core/turn.py`, `magi/common/contracts.py` (`TurnContext.reading`, `ARG_NARRATE`), `tests/audiolivro/test_leitor.py`, `tests/core/test_turn_narrate.py`
  - Depende de: A2.1, A1.2, A1.3, A1.4
  - Orçamento: ~50k
  - Pronto: CA-A7; Qwen falso lento → leitura começa nas regras e troca no capítulo com cache; `tests/core/test_turn*.py` antigos verdes.
  - Paralelo: —

- [x] **A2.3 Intents, roteador e handler** — 11 intents `book.*` (spec §5) no `IntentId` e no
  `intents.yaml`; chave `context: reading` no formato do YAML e no `LocalRouter` (frase com
  contexto só concorre com `ctx.reading`); `handler.py` (`BookHandler`: tempo restante em
  `book.time` (A7.1), ambiguidade (A1.1), não começa em call e avisa (A8.4), música pausada/retomada
  pelo handler MPRIS (D4), liga o `magi-qwen` no `book.read` e para no `book.stop`/fim se foi ele
  que ligou (D2), registro da `Biblioteca`/`Leitura`/TTS Kokoro do livro, respostas em
  `phrases.yaml` + `i18n/en-gb.yaml`); registro no `assemble.py`. *(A1, A6, A7, A8.2, A8.4)*
  - Lê: spec §4–§6, requirements A1, A6–A8, `magi/core/intents.yaml` linhas 1–40 e o bloco `music.pause`, `magi/core/router.py` linhas 318–410 e 424–500, `magi/agent/tools/news.py` linhas 430–455 (handler modelo), `magi/core/assemble.py` `grep -n "Registry\|WhatsNewHandler"` ±15 linhas, `magi/core/i18n/en-gb.yaml` linhas 1–20
  - Escreve: `magi/core/intents.yaml`, `magi/core/router.py`, `magi/common/contracts.py` (só `IntentId`), `magi/audiolivro/handler.py`, `magi/core/assemble.py`, `magi/core/phrases.yaml`, `magi/core/i18n/en-gb.yaml`, `tests/audiolivro/test_handler.py`, `tests/core/test_router_livro.py`
  - Depende de: A2.2
  - Orçamento: ~50k
  - Pronto: CA-A6; handler com `Leitura`/`ContainerRuntime`/MPRIS falsos cobre os 11 intents; `uv run pytest -q tests/core` verde.
  - Paralelo: —

## Fase A3 — Ao vivo

- [ ] **A3.1 Validação com o Pedro** *(é do Pedro — agente não implementa; decisão de 2026-10-10)* — o Pedro põe 2 livros (1 EPUB PT, 1 PDF) na pasta e reinicia
  o `magi-core`; o agente só lê logs e o `audiolivro.jsonl`. Roteiro: "lê o livro X" (Kokoro, 1
  capítulo), "volta um parágrafo", "mais devagar", pergunta outra coisa no meio (não retoma),
  "continua", "para", reinicia o núcleo e "continua o livro"; confere que `costs` não ganhou linha
  (critério 5); 50 falas conferidas para o critério 4 (voz por personagem estável). Ajusta
  `verbos.toml`, grupos de vozes, fatores de velocidade/pausa, `chars_por_minuto` e o `[audiolivro]` padrão. *(critérios 1–6)*
  - Lê: requirements (critérios), spec §2–§4, logs do `magi-core` por `grep -i audiolivro`
  - Escreve: `magi/audiolivro/verbos.toml`, `vozes.toml`, `docs/PROXIMOS-PASSOS.md` (§13, resultado)
  - Depende de: A2.3, Pedro (livros + uso)
  - Orçamento: ~30k
  - Pronto: os 6 critérios medidos e anotados; desvios viram itens em *Sobras*.
  - Paralelo: —

## Fase A4 — Limpeza

- [x] **A4.1 Limpeza do audiolivro (sobras de A2.2 e A2.3)** — registro A10: a `Narrada` chama
  `Marcador.registrar_sessao` no fim (`fim_livro`/`capitulos`), no `book.pause` (`pausa`), no
  `book.stop` (`parada`) e ao trocar de livro (`trocou`): livro (id), de/até, capítulos, caracteres,
  segundos/minutos, marcação (`Leitura.marcacao`), personagens novos, motivo — sem texto do livro.
  Música volta no fim do **áudio**: `say_parts(..., on_done)` (ou o `on_done` do iterável de partes;
  a `Narrada.partes()` devolve um `_Partes` com ele) agendado pelo `_Playhead` no fim do que foi
  enviado; interrompido, não chama. Frases soltas: "chega de livro" com `context: reading` ("chega"
  sem leitura não vira ASK); `book.read` com `query` de comando ("de novo", "mais rápido"...)
  responde `SAY_NO_BOOK`. Legenda de call traduzida em `i18n/en-gb.yaml` (a constante ficou em
  `turn.py`, sem edição).
  - Lê: as *Sobras* de A2.2/A2.3, `handler.py`, `leitor.py`, `magi/core/tts.py` (`say_parts`, `_Playhead`), `intents.yaml` (bloco `book.*`)
  - Escreve: `magi/audiolivro/handler.py`, `magi/audiolivro/leitor.py`, `magi/core/tts.py`, `magi/core/intents.yaml` (só `book.stop`), `magi/core/i18n/en-gb.yaml` (só livro), `tests/audiolivro/test_handler.py`, `tests/core/test_tts_partes.py`
  - Depende de: A2.3
  - Pronto: `uv run pytest -q tests/audiolivro tests/core` verde.

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
- (A1.2) Para a A2.2: `marcas.marcar` já tira as marcas `\x1e`/`\x1d` (`Trecho.texto` = `limpo` do
  parágrafo; concatenação == `limpo(paragrafo.texto)`) e corta trechos por frase; use
  `marcar_capitulo` (lembra gênero/idade do falante) e `vozes.partes(trechos, elenco, velocidade)`
  para o `say_parts`. `opcoes` ficou com a assinatura do stub (sem `cfg`; o `Elenco` leva o cfg).
- (A2.2) Para a A2.3: retomar/abrir a narração = `ActionResult(on_confirm=ActionRequest(...,
  args={ARG_NARRATE: leitura}), needs_confirmation=False)` (`True` = a leitura do contexto); sem
  `ARG_NARRATE` a leitura fica pausada. Montagem: `Leitura(cfg, Marcador(cfg), voz_dela=...,
  idioma_dela=..., tts=registry.tts_livro(), refino=marcas_llm.criar(...))` (o `tts` é embrulhado
  pelo cache de PCM). `TurnContext.reading` = `TurnMachine.reading` (lendo ou pausada ≤ 30 min).
  O fim da narração (fim do livro/`parar_apos_capitulos`) não avisa o handler: a volta da música
  (D4) e o `refino.parar()` no fim ficam para a A2.3 (ex.: embrulhar `Leitura.partes`). A legenda
  de call (`READING_CALL_CAPTION` em `turn.py`) não tem tradução en-gb (só legenda, sem fala).
  Os índices de parágrafo da `Posicao` são a posição na lista do capítulo (= `Paragrafo.n` no EPUB/PDF).
- (A2.3) Pronto: `BookHandler` + `montar` (Leitura com `registry.tts_livro()` e `RefinoQwen` sobre
  `ModeloQwen` — Ollama local `/v1/chat/completions` — e `ContainerRuntime` do `[audiolivro]`);
  `Narrada` embrulha a `Leitura` (fim de `partes()` → música volta + `refino.parar()`; `book.stop`
  marca `estado = "parada"`). Ficou: (1) a música volta quando o gerador acaba, que é um pouco
  antes do áudio das últimas frases (o `say_parts` pré-sintetiza); (2) o registro A10
  (`registrar_sessao`) não é chamado por ninguém ainda; (3) o "continua o livro" depois de reiniciar
  usa `estado_dir/audiolivro-ultimo` (id do último livro); (4) o Learning embrulha
  `LocalRouter.best(text)` com 1 argumento (`intent_action._gate`), então o `route` passa o
  `ctx.reading` por `self._reading`; (5) sem leitura, "chega" vira ASK de `book.stop` (85) e
  "lê de novo"/"lê mais rápido" viram `book.read` (responde "não achei esse livro").
- (A4.1) Itens (1), (2) e (5) das sobras da A2.3 e a legenda en-gb da A2.2 resolvidos. Ficou: o
  `TurnMachine._narrate_now` não passa `on_done` explícito (o `say_parts` pega o da `Narrada`
  pelo iterável); se a ativação cortar o áudio das últimas frases **depois** do gerador acabar, o
  turno já não acompanha (`_narrating` caiu) e a música volta mesmo assim no tempo previsto.
