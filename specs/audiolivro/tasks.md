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
   satélite, sem tocar áudio, sem ler `~/Documentos/Livros` real nos testes (fixtures geradas em
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

```
A0.1 ─┬─ A1.1 (EPUB/PDF) ─┬─ A1.2 (marcas + vozes) ─┬─ A1.3 (LLM, opcional; fora do caminho crítico)
      │                   │                          │
      │                   └─ A1.4 (biblioteca, marcador, custo) ─┐
      └─ A2.1 (TTS por trecho) ───────────────────────────────────┴─ A2.2 (Leitura + narrate; dep A1.2, A1.4, A2.1) ── A2.3 (intents + handler) ── A3.1 (ao vivo, Pedro)
```

---

## Fase A0 — Contratos

- [ ] **A0.1 Contratos, config e esqueleto** — pacote `magi/audiolivro/` com `contratos.py`
  (spec §1), `config.py` (spec §6, padrões quando a seção falta), stubs com assinatura final e
  docstring da tarefa dona: `epub`, `pdf`, `frases`, `biblioteca`, `marcas`, `marcas_llm`,
  `vozes`, `custo`, `marcador`, `leitor`, `handler`; `verbos.toml` e `vozes.toml` vazios com o
  cabeçalho do formato; `tests/audiolivro/conftest.py` isolando estado/cache em `tmp_path`;
  `pypdf` no `pyproject.toml` (D6). *(A1–A10)*
  - Lê: design §2, spec §1 e §6, `magi/learning/model.py` linhas 1–40 (padrão de tarefa fora do `ProviderTask`)
  - Escreve: `magi/audiolivro/*`, `tests/audiolivro/conftest.py`, `tests/audiolivro/test_contratos.py`, `pyproject.toml` (só a dependência), `uv.lock`
  - Depende de: —
  - Orçamento: ~30k
  - Pronto: `import magi.audiolivro.<cada módulo>` funciona; config com e sem a seção; `ruff` limpo.
  - Paralelo: —

## Fase A1 — Texto, marcas, custo

- [ ] **A1.1 Leitores EPUB e PDF** — `epub.py` (OPF → spine → XHTML; pula `nav`/`toc`/notas
  `epub:type="footnote|endnote"`; `<h*>` vira parágrafo título; itálico marcado para A1.2 com
  um atributo no `Paragrafo` ou marca `\x1e` documentada), `pdf.py` (`pypdf`; junta hifenização;
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

- [ ] **A1.2 Marcação por regras e voz por trecho** — `marcas.py` (spec §2), `verbos.toml`
  (PT e EN), `vozes.py` + `vozes.toml` (spec §3, incluindo juntar trechos iguais até 400 caracteres). *(A3, A4)*
  - Lê: spec §1–§3, requirements A3–A4, `magi/audiolivro/contratos.py`, `magi/providers/kokoro_provider.py` linhas 1–40 (formato de voz misturada)
  - Escreve: `magi/audiolivro/marcas.py`, `verbos.toml`, `vozes.py`, `vozes.toml`, `tests/audiolivro/test_marcas.py`, `test_vozes.py`
  - Depende de: A1.1 (só o formato do itálico no `Paragrafo`)
  - Orçamento: ~45k
  - Pronto: CA-A2 e CA-A3 verdes.
  - Paralelo: A1.4, A2.1

- [ ] **A1.3 Marcação por LLM (opcional, D2)** — `marcas_llm.py`: por capítulo, manda os
  parágrafos **numerados** e os trechos das regras; o modelo devolve só JSON
  `[{par, i, tipo, emocao, falante, genero}]` (nunca texto); valida (índices existem, enums
  válidos) e mescla; cache por livro/capítulo; custo pelo padrão de `magi/learning/budget.py`;
  falha/JSON inválido → regras (A3.1). Prompt em `magi/audiolivro/prompts/marcas.md`. *(A3.1)*
  - Lê: spec §2 e §4, requirements A3.1, `magi/learning/model.py` (por trecho: `grep -n "def \|class "`), `magi/learning/budget.py` linhas 1–40
  - Escreve: `magi/audiolivro/marcas_llm.py`, `magi/audiolivro/prompts/marcas.md`, `tests/audiolivro/test_marcas_llm.py`
  - Depende de: A1.2
  - Orçamento: ~40k
  - Pronto: modelo falso com resposta boa, com índice inválido, com texto em vez de JSON e com timeout → resultado certo em cada caso; cache reaproveitado (0 chamadas na 2ª vez).
  - Paralelo: A1.4, A2.2

- [ ] **A1.4 Biblioteca, marcador e custo** — `biblioteca.py` (varre a pasta, cache do índice em
  `~/.cache/magi/audiolivro/indice.json` por mtime; `achar(fala) -> list[(Livro, nota)]` com
  normalização sem acento, sem artigos e casamento por tokens; ambíguo = 2 notas a < 0,1),
  `marcador.py` (spec §1 `Posicao`; atômico com `.bak`; ≤ 1 escrita/2 s; registro `audiolivro.jsonl`
  com giro de 5 MB), `custo.py` (spec §4, usando `MonthlyBudget.price_usd`). *(A1, A1.1, A5, A7, A10)*
  - Lê: spec §1, §4, §6, requirements A1, A5, A7, A10, `magi/core/budget.py` linhas 60–110 e `grep -n "def price_usd\|def status" -A12`
  - Escreve: `magi/audiolivro/biblioteca.py`, `marcador.py`, `custo.py`, `tests/audiolivro/test_biblioteca.py`, `test_marcador.py`, `test_custo.py`
  - Depende de: A1.1
  - Orçamento: ~45k
  - Pronto: CA-A4, CA-A5; 10 títulos de teste (com acento, artigo, subtítulo, número) achados.
  - Paralelo: A1.2, A1.3, A2.1

## Fase A2 — Voz e controle

- [ ] **A2.1 TTS com opções por trecho** — `GuardedTts.com_opcoes(**over)` (cópia com `CallCtx`
  mesclado: `voice`, `speed`, `instructions`, `lang`; mesma pool de chaves, mesmo orçamento,
  `whole_sentence` preservado) e `PhraseSpeaker.say_parts(parts, link, *, personal, on_sentence)`
  (fluxo de `(texto, OpcoesVoz)`; cada parte com o provedor das opções dela; `on_sentence` com
  índice contínuo; nada vai ao cache de frases). Custo de TTS segue gravado pelo `GuardedTts`. *(A4, A7.2)*
  - Lê: design §1–§2, spec §1 (`OpcoesVoz`), `magi/core/tts.py` linhas 224–335 e 408–490, `magi/providers/registry.py` linhas 225–280 e `grep -n "class _Guarded" -A40`
  - Escreve: `magi/providers/registry.py`, `magi/core/tts.py`, `tests/core/test_tts_partes.py`
  - Depende de: A0.1
  - Orçamento: ~40k
  - Pronto: CA-A8; `tests/core/test_tts*.py` e `tests/providers/` antigos verdes.
  - Paralelo: A1.1, A1.2, A1.4

- [ ] **A2.2 Leitura e narração no turno** — `leitor.py` (`Leitura`: `abrir(livro, posicao)`,
  `partes()` assíncrono frase a frase com marcas + vozes, `interrompida()`, `voltar(n)`,
  `pular(n)`, `capitulo(delta|n)`, `velocidade(delta)`, `estado`; cache PCM dos 3 últimos
  parágrafos; troca para local quando o `Budget` estoura no meio, A7.2) e
  `TurnMachine.narrate(leitura)` + `TurnContext.reading` (design §4; sem janela de continuação;
  pausa em call, A8.4). Retomada depois de comando de leitura pelo resultado com `ARG_NARRATE`. *(A5, A6.2, A7.2, A8)*
  - Lê: design §3–§5, spec §1, requirements A5–A8, `magi/core/turn.py` por trecho: `grep -n "def announce\|def wake\|def _go\|_followup\|in_call\|class TurnContext" ` e só esses intervalos (±40 linhas); `magi/common/contracts.py` `grep -n "class TurnContext" -A30` e `grep -n "ARG_QUIET\|ARG_ALSO_YES"`
  - Escreve: `magi/audiolivro/leitor.py`, `magi/core/turn.py`, `magi/common/contracts.py` (`TurnContext.reading`, `ARG_NARRATE`), `tests/audiolivro/test_leitor.py`, `tests/core/test_turn_narrate.py`
  - Depende de: A2.1, A1.2, A1.4
  - Orçamento: ~50k
  - Pronto: CA-A7; `tests/core/test_turn*.py` antigos verdes.
  - Paralelo: A1.3

- [ ] **A2.3 Intents, roteador e handler** — 12 intents `book.*` (spec §5) no `IntentId` e no
  `intents.yaml`; chave `context: reading` no formato do YAML e no `LocalRouter` (frase com
  contexto só concorre com `ctx.reading`); `handler.py` (`BookHandler`: custo e oferta da local
  (A7.1), ambiguidade (A1.1), não começa em call e avisa (A8.4), música pausada/retomada pelo handler MPRIS (D4), respostas em
  `phrases.yaml` + `i18n/en-gb.yaml`); registro no `assemble.py`. *(A1, A6, A7, A8.2, A8.4)*
  - Lê: spec §4–§6, requirements A1, A6–A8, `magi/core/intents.yaml` linhas 1–40 e o bloco `music.pause`, `magi/core/router.py` linhas 318–410 e 424–500, `magi/agent/tools/news.py` linhas 430–455 (handler modelo), `magi/core/assemble.py` `grep -n "Registry\|WhatsNewHandler"` ±15 linhas, `magi/core/i18n/en-gb.yaml` linhas 1–20
  - Escreve: `magi/core/intents.yaml`, `magi/core/router.py`, `magi/common/contracts.py` (só `IntentId`), `magi/audiolivro/handler.py`, `magi/core/assemble.py`, `magi/core/phrases.yaml`, `magi/core/i18n/en-gb.yaml`, `tests/audiolivro/test_handler.py`, `tests/core/test_router_livro.py`
  - Depende de: A2.2
  - Orçamento: ~50k
  - Pronto: CA-A6; handler com `Leitura`/`Budget`/MPRIS falsos cobre os 12 intents; `uv run pytest -q tests/core` verde.
  - Paralelo: —

## Fase A3 — Ao vivo

- [ ] **A3.1 Validação com o Pedro** — o Pedro põe 2 livros (1 EPUB PT, 1 PDF) na pasta e reinicia
  o `magi-core`; o agente só lê logs e o `audiolivro.jsonl`. Roteiro: "lê o livro X" (Kokoro, 1
  capítulo), "volta um parágrafo", "mais devagar", pergunta outra coisa no meio (não retoma),
  "continua", "para", reinicia o núcleo e "continua o livro"; 10 páginas na expressiva comparando
  custo estimado × `costs` do banco; 50 falas conferidas para o critério 4. Ajusta `verbos.toml`,
  fatores de velocidade e o `[audiolivro]` padrão. *(critérios 1–6)*
  - Lê: requirements (critérios), spec §2–§4, logs do `magi-core` por `grep -i audiolivro`
  - Escreve: `magi/audiolivro/verbos.toml`, `vozes.toml`, `docs/PROXIMOS-PASSOS.md` (§13, resultado)
  - Depende de: A2.3, Pedro (livros + uso)
  - Orçamento: ~30k
  - Pronto: os 6 critérios medidos e anotados; desvios viram itens em *Sobras*.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
