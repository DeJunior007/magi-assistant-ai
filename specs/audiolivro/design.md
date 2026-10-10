# Design — Audiolivro da Condessa

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. Onde mora hoje

```
satélite ─wake/fala─▶ TurnMachine (magi/core/turn.py) ─▶ LocalRouter (intents.yaml) ─▶ Registry ─▶ handler
                                  │                                                         │
                                  └──── SPEAKING ◀── PhraseSpeaker.say/say_stream ◀── ActionResult.speech
PhraseSpeaker (magi/core/tts.py) ─▶ GuardedTts (providers/registry.py) ─▶ KokoroBackend | OpenAIBackend
ProactiveSink (core/proactive/sink.py): fala proativa só com o satélite SLEEPING e livre; em call → legenda
```
- Fala longa existente: a Rádio Ayanami (`magi/agent/tools/news.py`, `WhatsNewHandler`) — uma notícia
  por turno, narrada em 5–7 frases e "quer ouvir outra?". Não serve de leitor: não guarda posição
  fina nem aceita opções de voz por frase.
- `PhraseSpeaker.say_stream(texts, link, on_sentence=)` já fala um fluxo de frases num envio só e
  avisa **quando cada frase começa** (`_Playhead`): é a base do marcador (A5).
- O `CallCtx.options` (voz, `instructions`, `speed`, `lang`) é **um por tarefa**: hoje não dá para
  mudar a voz por trecho. `TurnMachine.wake` cancela o trabalho em curso e manda `StopPlayback`.
- Tarefas de modelo fora do `ProviderTask` (ex.: `learning_actions`) usam o padrão de
  `magi/learning/model.py` + `magi/learning/budget.py` (confere teto antes, grava custo depois).

## 2. Pacote novo `magi/audiolivro/`

| Módulo | Papel | Dono |
| --- | --- | --- |
| `contratos.py` | `Livro`, `Capitulo`, `Paragrafo`, `Trecho`, `Tipo`, `Emocao`, `Marca`, `OpcoesVoz`, `Estimativa` | A0.1 |
| `config.py` | lê `[audiolivro]` (spec §6) com padrões | A0.1 |
| `epub.py` | EPUB → capítulos/parágrafos (só `zipfile` + `xml.etree` + `html.parser`, sem dependência) | A1.1 |
| `pdf.py` | PDF de texto → capítulos/parágrafos (`pypdf`, D6); tira cabeçalho/rodapé repetidos | A1.1 |
| `frases.py` | parágrafo → frases (abreviações PT/EN, reticências, travessão) | A1.1 |
| `biblioteca.py` | índice da pasta (cache por mtime), busca tolerante pelo título falado | A1.4 |
| `marcas.py` | regras locais: parágrafo → `Trecho`s (spec §2) | A1.2 |
| `marcas_llm.py` | refino opcional por capítulo, cache em `~/.cache/magi/audiolivro/<id>/marcas-<cap>.json` | A1.3 |
| `vozes.py` | `Trecho` + idioma + provedor + velocidade → `OpcoesVoz` (spec §3) | A1.2 |
| `custo.py` | estimativa por página/capítulo/livro com os preços do `Budget` (spec §4) | A1.4 |
| `marcador.py` | posição por livro + registro de sessões (A5, A10) | A1.4 |
| `leitor.py` | `Leitura`: estado (lendo/pausada/parada), fila de trechos, prefetch, cache dos últimos parágrafos, retomada | A2.2 |
| `handler.py` | `BookHandler` dos intents `book.*` (spec §5) | A2.3 |

Ligações fora do pacote (cada uma de uma tarefa só):
- `magi/providers/registry.py`: `GuardedTts.com_opcoes(**over) -> GuardedTts` (cópia com o
  `CallCtx.options` mesclado; mesma chave/cota/orçamento). **A2.1**
- `magi/core/tts.py`: `PhraseSpeaker.say_parts(parts, link, on_sentence=)` — fluxo de
  `(texto, OpcoesVoz)`; cada parte vai ao provedor com as opções dela; frases do livro **não**
  entram no cache de frases (não são `cacheable`). **A2.1**
- `magi/core/turn.py`: `TurnMachine.narrate(leitura)` — como `announce`, mas longo: entra em
  `SPEAKING` sem janela de continuação, consome `leitura.partes()`, passa `on_sentence` para o
  marcador e, ao ser cancelado por `wake`, chama `leitura.interrompida()`. Expõe
  `TurnContext.reading` (leitura ativa/pausada ≤ 30 min). **A2.2**
- `magi/core/router.py` + `intents.yaml`: intents `book.*`; frases curtas ("pausa", "continua",
  "volta") marcadas `context: reading` só concorrem quando `ctx.reading` (A6.1). **A2.3**
- `magi/core/assemble.py` / `service.py`: monta `Biblioteca`, `Leitura` e registra o `BookHandler`. **A2.3**

## 3. Fluxo de uma leitura

1. "Condessa, lê o livro Duna" → `book.read{query=duna}` → `Biblioteca.achar` → `Livro`.
2. `Marcador.posicao(livro)` (ou início) e `custo.estimar(livro, cap, provedor)`; se custa > 0, a
   resposta fala o preço (A7); se passa do teto, oferta (`Offer`) de usar a local (A7.1).
3. `ActionResult` curto ("Duna, capítulo 3, de onde paramos.") e um **pedido de narração**
   (`ARG_NARRATE` no resultado); o `TurnMachine`, ao terminar essa fala, chama `narrate(leitura)`.
4. `Leitura.partes()` gera `(texto, OpcoesVoz)` frase a frase: extrai o capítulo (cache em memória),
   marca (regras ou cache do LLM), mapeia voz; pré-sintetiza 1 trecho à frente (já é o que o
   `say_stream` faz ao consumir o próximo item enquanto toca).
5. `on_sentence(texto, dur, i)` → `Marcador.avancar(cap, par, frase)` (grava no máximo 1×/2 s +
   no fim) e legenda no HUD (já existe).
6. Fim do capítulo → segue o próximo (sem pausa) até `[audiolivro] parar_apos_capitulos` ou o fim.

## 4. Interrupção e comandos

```
lendo ──wake/clique──▶ pausada(frase f) ──comando book.* ──▶ executa ──▶ lendo (retoma em f ou no alvo)
                               │──outro assunto──▶ pausada (não retoma; A6.2)
                               └──30 min sem "continua"──▶ parada (marcador fica)
```
- "Volta um parágrafo" = parágrafo atual − 1, frase 0. "Repete" = parágrafo atual, frase 0.
- O cache dos **últimos 3 parágrafos** de PCM (por provedor) torna voltar/repetir grátis na OpenAI.
- "Mais devagar/rápido" muda o fator (0,8–1,25, passo 0,1) gravado no marcador; no Kokoro vai
  em `speed`; na OpenAI em `speed` **e** na frase "ritmo mais lento" da instrução.

## 5. Convivência

| Situação | Comportamento |
| --- | --- |
| Música tocando ao começar | D4 (a): `music.pause` via o handler MPRIS existente; volta no `book.stop`/fim |
| Aviso proativo durante a leitura | o `ProactiveSink` já espera `SLEEPING`; com `max_wait_s` vira legenda (A8.1) |
| Jogo aberto | lê; ducking do satélite abaixa o jogo; o HUD mostra a Magui `speaking` |
| Call no Discord | não começa (A8.4); se a call começar no meio, pausa e avisa por legenda |
| Clique no rosto | = ativação: pausa a leitura e escuta (mesmo caminho do `wake`) |
| Teto estoura na expressiva | troca para a local no próximo parágrafo + legenda de aviso (A7.2) |

## 6. Riscos

| Risco | Mitigação |
| --- | --- |
| Custo da OpenAI fora de controle | padrão local (D1); estimativa antes; corte no teto (A7.2); cache dos 3 últimos parágrafos |
| Wake word não ouvida com a leitura alta | headset (eco baixo); clique no rosto como reserva; teste ao vivo em A3.1 |
| "Pausa" roubada da música | contexto `reading` no roteador (A6.1); teste de roteamento com e sem leitura |
| PDF com duas colunas/hifenização | junta hifenização no fim da linha; colunas ficam como limitação (D6) |
| Kokoro lento em parágrafo longo | `say_parts` manda frase a frase (o Kokoro já é `whole_sentence`) |
| Regressão da fala normal | `say`/`say_stream` não mudam; `com_opcoes` é cópia, não altera o `GuardedTts` original |
