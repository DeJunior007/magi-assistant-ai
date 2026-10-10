# Spec — Audiolivro da Condessa

Contratos, números, tabelas de voz e comandos. Implementa [requirements.md](requirements.md)
segundo o [design.md](design.md).

## 1. Contratos (`magi/audiolivro/contratos.py`)

```python
class Tipo(StrEnum): NARRACAO, FALA, PENSAMENTO, TITULO
class Emocao(StrEnum): NEUTRA, ALEGRE, TRISTE, TENSA, RAIVA, MEDO, SUSSURRO, GRITO, IRONIA, CARINHO

@dataclass(frozen=True)
class Paragrafo:
    n: int; frases: tuple[str, ...]

@dataclass(frozen=True)
class Capitulo:
    n: int; titulo: str; paragrafos: tuple[Paragrafo, ...]
    paginas: float                  # PDF: páginas reais; EPUB: caracteres / chars_por_pagina

@dataclass(frozen=True)
class Livro:
    id: str                         # sha1 do caminho + tamanho (curto, 12)
    caminho: Path; titulo: str; autor: str | None; idioma: str   # "pt-br", "en", ...
    formato: Literal["epub", "pdf"]; capitulos: int; caracteres: int

@dataclass(frozen=True)
class Trecho:
    texto: str                      # exatamente o texto do livro (A9)
    tipo: Tipo = Tipo.NARRACAO
    emocao: Emocao = Emocao.NEUTRA
    falante: str | None = None; genero: Literal["f", "m"] | None = None
    par: int = 0; frase: int = 0    # posição (capítulo vem da Leitura)

@dataclass(frozen=True)
class OpcoesVoz:                    # vai para GuardedTts.com_opcoes(**asdict sem None)
    voice: str | None = None; speed: float | None = None
    instructions: str | None = None; lang: str | None = None

@dataclass(frozen=True)
class Posicao:
    cap: int; par: int; frase: int; velocidade: float = 1.0; modo: Literal["local", "expressiva"] = "local"

@dataclass(frozen=True)
class Estimativa:
    usd_pagina: float; usd_capitulo: float; usd_livro_restante: float; provedor: str
```

`Livro.capitulo(n) -> Capitulo` é preguiçoso (extrai e guarda em LRU de 3 capítulos).

## 2. Marcação por regras (`marcas.py`)

Entrada: `Paragrafo` + idioma. Saída: `list[Trecho]` cuja concatenação dos `texto` (com os
espaços) é igual ao parágrafo (teste de propriedade, A9).

| Regra | PT-BR | EN |
| --- | --- | --- |
| Fala | parágrafo começa com `—`/`–`/`-` + espaço: alterna fala/narração a cada travessão interno (`— Vem — disse ela. — Agora.` = fala · narração · fala) | texto entre `“ ”` ou `" "` |
| Também fala | texto entre `“ ”`, `« »` | `' '` só se o parágrafo tiver verbo de elocução |
| Pensamento | itálico do EPUB (`<i>`, `<em>`) sem travessão | idem |
| Título | `<h1>`–`<h3>` do EPUB; linha curta isolada com "Capítulo"/"Chapter"/numeral romano no PDF | idem |
| Gênero | verbo + pronome na narração colada à fala: "disse ela/ele", "respondeu a moça/o velho" | "she said", "he said" |
| Falante | nome próprio colado ao verbo ("disse Paul") — guardado para a fala seguinte sem tag | idem |

Emoção (primeira que casar, na fala e na narração colada a ela):

| Emoção | Gatilho |
| --- | --- |
| GRITO | verbo `gritou/berrou/urrou/bradou` · `shouted/yelled/screamed`; ou fala só em maiúsculas |
| SUSSURRO | `sussurrou/murmurou/cochichou` · `whispered/murmured` |
| RAIVA | `rosnou/vociferou/explodiu/irritad*` · `snapped/growled/snarled` |
| MEDO | `tremeu/gaguejou/apavorad*` · `stammered/trembled` |
| TRISTE | `soluçou/chorou/lamentou` · `sobbed/wept` |
| ALEGRE | `riu/sorriu/gargalhou` · `laughed/grinned` |
| IRONIA | `ironizou/zombou/debochou` · `sneered/mocked` |
| TENSA | narração com ≥ 2 frases curtas (< 6 palavras) seguidas ou `!` na narração |
| CARINHO | `acariciou/sorriu para` + fala com vocativo carinhoso (tabela pequena) |
| NEUTRA | resto; `?` e `!` isolados não mudam a emoção (a voz já entoa) |

Listas de verbos ficam em `magi/audiolivro/verbos.toml` (PT e EN), não no código.

## 3. Voz por trecho (`vozes.py`)

`opcoes(trecho, idioma, modo, velocidade, cfg) -> OpcoesVoz`. Velocidade final = `velocidade` do
marcador × fator da emoção, limitada a 0,7–1,3.

**Local (Kokoro):** vozes do `[audiolivro.vozes.<idioma>]` (padrões abaixo); emoção só por fator.

| Idioma | Narração | Fala f | Fala m | Fala sem gênero |
| --- | --- | --- | --- | --- |
| pt-br | `pf_dora` | `pf_dora:0.6,af_bella:0.4` | `pm_alex` | `pf_dora:0.8,pm_alex:0.2` |
| en | `bf_isabella` | `bf_emma` | `bm_george` | `bf_isabella:0.7,bm_george:0.3` |

**Expressiva (OpenAI `gpt-4o-mini-tts`):** `voice` do `[audiolivro]` (padrão `marin`);
`instructions` = base do idioma + parte do tipo + parte da emoção (+ "ritmo mais lento/rápido" se
`velocidade` ≠ 1). Partes em `vozes.toml`, ex. PT-BR:
- base: "Leia em português do Brasil, como narradora de audiolivro, clara e natural."
- NARRACAO: "Narração em terceira pessoa, tom contido." · FALA f/m: "Interprete a fala de uma
  personagem feminina/masculina, sem caricatura." · PENSAMENTO: "Voz mais baixa e íntima." ·
  TITULO: "Anuncie o título, pausa breve depois."
- emoção: TENSA "tensão contida", RAIVA "irritação firme", GRITO "exclamado, sem gritar de
  verdade", SUSSURRO "quase sussurrando", TRISTE "embargada", ALEGRE "sorrindo", MEDO "hesitante",
  IRONIA "seca e irônica", CARINHO "afetuosa".

| Emoção | Fator de velocidade |
| --- | --- |
| TENSA, RAIVA, GRITO | 1,08 |
| TRISTE, SUSSURRO, CARINHO | 0,92 |
| MEDO | 1,04 |
| demais | 1,00 |

Trechos seguidos com as mesmas `OpcoesVoz` são **juntados** até 400 caracteres (menos chamadas).

## 4. Custo (`custo.py`)

Preços pelo `MonthlyBudget.price_usd(Usage(...))` (não copiar números):
- TTS: `Usage(provider, task=TTS, model, input_units=caracteres + caracteres_da_instrução)` —
  a instrução repetida por chamada entra na conta (≈ 150 caracteres por trecho juntado).
- Marcação LLM: `input_units = caracteres/4 + 350` tokens, `output_units = trechos × 25` tokens.
- `chars_por_pagina` = 1800 (EPUB); PDF usa `caracteres / páginas` do próprio arquivo.

Referência com o `config.toml` atual: OpenAI ≈ 1800 × 20/1M ≈ **US$ 0,036/página** (+ ~10% de
instrução); Kokoro **0**; marcação `gpt-5.4-mini` ≈ US$ 0,003/página; Gemini cota grátis **0**.

Frase falada (pt-br; vai pelo `i18n.tr` como as outras): "Esse capítulo sai por uns {usd} dólares
na voz expressiva, {usd_pag} por página." / "Na voz local é de graça."

## 5. Comandos (`intents.yaml`, `IntentId`)

| Intent | Frases-modelo | Contexto |
| --- | --- | --- |
| `book.read` | "lê o livro {query}", "lê {query}", "bota o audiolivro {query}", "abre o livro {query}" | — |
| `book.resume` | "continua o livro", "continua a leitura", "volta a ler"; **"continua", "pode continuar"** | as 2 últimas: `reading` |
| `book.pause` | "pausa a leitura"; **"pausa", "espera"** | `reading` |
| `book.stop` | "para de ler", "fecha o livro", "chega de livro"; **"para", "chega"** | `reading` |
| `book.back` | "volta um parágrafo", "volta {amount} parágrafos", "repete", "lê de novo" | `reading` |
| `book.forward` | "pula um parágrafo", "pula {amount} parágrafos" | `reading` |
| `book.chapter` | "próximo capítulo", "capítulo anterior", "vai pro capítulo {amount}" | `reading` |
| `book.speed` | "lê mais devagar", "mais devagar", "lê mais rápido", "velocidade normal" | `reading` |
| `book.where` | "onde a gente parou", "em que capítulo tá" | — |
| `book.list` | "que livros eu tenho", "lista os livros" | — |
| `book.cost` | "quanto custa ler {query}", "quanto custa esse livro" | — |
| `book.voice` | "lê com voz expressiva", "lê com a voz local" | — |

`context: reading` = a frase só concorre quando `TurnContext.reading`; sem leitura, "pausa"/"para"
seguem para a música/sistema como hoje. Respostas curtas em `phrases.yaml` + `i18n/en-gb.yaml`.

## 6. Configuração (`[audiolivro]` em `~/.config/magi/config.toml`)

```toml
[audiolivro]
pasta = "~/Documentos/Livros"
modo = "local"                    # "local" | "expressiva" (D1)
marcacao = "regras"               # "regras" | "llm" (D2)
musica = "pausa"                  # "pausa" | "duck" (D4)
voz_expressiva = "marin"
chars_por_pagina = 1800
parar_apos_capitulos = 0          # 0 = até o fim
retomar_apos_comando = true       # A6.2
pausa_expira_min = 30
[audiolivro.vozes.pt-br]          # sobrepõe a tabela do §3
[tasks]
audiolivro_marca = { provider = "gemini", model = "gemini-3.5-flash-lite", timeout_s = 20 }
```

## 7. Critérios de aceite

- **CA-A1** EPUB de teste (fixture gerada no teste, 3 capítulos com `nav`, notas e itálico) e PDF de
  teste (gerado com `pypdf`/texto) extraem exatamente os parágrafos esperados, na ordem.
- **CA-A2** Para 30 parágrafos de fixture PT e EN, `marcas` devolve os tipos/emoções da tabela
  esperada; concatenação dos trechos == parágrafo (propriedade, 200 casos).
- **CA-A3** `vozes.opcoes` cobre todo par tipo × emoção × idioma × modo sem `None` em `voice`.
- **CA-A4** `custo.estimar` com o `[budget]` de teste dá US$ 0,036 ± 10% por página OpenAI e 0 no Kokoro.
- **CA-A5** Marcador: grava, sobrevive a reabrir, escrita atômica (arquivo truncado → começa do início
  do capítulo salvo no `.bak`), no máximo 1 escrita a cada 2 s em leitura contínua.
- **CA-A6** Roteador: "pausa" vai para `music.pause` sem leitura e para `book.pause` com; os 12
  intents casam suas frases-modelo; nenhum intent antigo muda de resultado (`tests/core/test_router*`).
- **CA-A7** `TurnMachine.narrate` com satélite e TTS falsos: interrupção por `wake` pausa na frase
  certa; comando de leitura retoma; outro assunto não retoma; nenhum aviso proativo fala no meio.
- **CA-A8** `say_parts` manda as `OpcoesVoz` de cada parte ao backend falso; `say`/`say_stream` iguais.
