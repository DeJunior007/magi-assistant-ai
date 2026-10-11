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
    idade: Literal["crianca", "jovem", "adulto", "idoso"] | None = None
    par: int = 0; frase: int = 0    # posição (capítulo vem da Leitura)

@dataclass(frozen=True)
class Marca:                        # uma linha do JSON do Qwen (A1.3); nunca traz texto
    par: int; i: int; tipo: Tipo; emocao: Emocao
    falante: str | None = None; genero: Literal["f", "m"] | None = None
    idade: Literal["crianca", "jovem", "adulto", "idoso"] | None = None

@dataclass(frozen=True)
class OpcoesVoz:                    # voice/speed/lang vão para GuardedTts.com_opcoes (sem None)
    voice: str | None = None; speed: float | None = None; lang: str | None = None
    pausa_ms: int = 0               # silêncio depois da parte (say_parts; não vai ao CallCtx)

@dataclass(frozen=True)
class Posicao:
    cap: int; par: int; frase: int; velocidade: float = 1.0

@dataclass(frozen=True)
class Estimativa:                   # tempo, não dinheiro (D1/D2: custo de API = 0)
    paginas_capitulo: float; minutos_capitulo: float; minutos_livro_restante: float
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
| Idade | substantivo colado à fala: "o menino/a menina" → criança, "o velho/a velha/o avô" → idoso | "the boy/girl", "the old man" |

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

## 3. Voz por trecho (`vozes.py`) — D1 + D5

`opcoes(trecho, elenco, velocidade, cfg) -> OpcoesVoz`. **Sempre Kokoro e sempre no idioma dela**
(`voz_dela`/`idioma_dela` do `config.py`: voz e `lang` do `[tasks].tts` quando é Kokoro; senão o
padrão Kokoro do `[speech] language`), qualquer que seja o idioma do livro. `lang` = idioma dela.
Velocidade final = `velocidade` do marcador × fator da emoção, limitada a 0,7–1,3.

- **Narração, título e pensamento sem falante:** a voz dela (pensamento com fator 0,95).
- **Personagem com nome (`falante`):** o `Elenco` do livro dá a voz; personagem novo pega a
  primeira voz livre do grupo (gênero × idade) do idioma dela, ≠ voz dela, e fica gravado em
  `~/.local/state/magi/audiolivro/elenco/<livro_id>.json` (nome normalizado sem acento/caixa →
  voz). Grupo esgotado → mistura nova `a:0.6,b:0.4` de duas vozes do grupo, ainda não usada.
- **Fala sem falante:** voz padrão do gênero (f/m) do idioma; sem gênero → `voz_dela:0.6,<f>:0.4`.

Grupos padrão (sobrepostos por `[audiolivro.vozes.<idioma>]`; a lista toda em `vozes.toml`):

| Idioma dela | f adulto | m adulto | jovem/criança | idoso |
| --- | --- | --- | --- | --- |
| en-gb | `bf_emma`, `bf_alice`, `bf_lily` | `bm_george`, `bm_lewis`, `bm_daniel` | `bf_lily`, `af_nicole:0.5,bf_lily:0.5` | `bm_fable`, `bf_alice:0.6,bm_fable:0.4` |
| pt-br | `pf_dora:0.5,af_bella:0.5`, `pf_dora:0.4,bf_emma:0.6` | `pm_alex`, `pm_santa` | `pf_dora:0.4,af_nicole:0.6` | `pm_santa:0.6,bm_fable:0.4` |

Emoção → velocidade e pausa depois do trecho (`pausa_ms`):

| Emoção / tipo | Fator | Pausa (ms) |
| --- | --- | --- |
| TENSA, RAIVA, GRITO | 1,08 | 150 |
| MEDO | 1,04 | 250 |
| TRISTE, SUSSURRO, CARINHO | 0,92 | 450 |
| demais | 1,00 | 250 (troca de voz) / 0 (mesma voz) |
| TITULO | 0,95 | 700 |

Trechos seguidos com as mesmas `OpcoesVoz` são **juntados** até 400 caracteres (menos chamadas).

## 4. Tempo (`custo.py`) — sem custo de API

Custo de API = **0** (D1/D2): o pacote não chama `MonthlyBudget` nem grava em `costs`. `custo.py`
só estima tempo: `estimar(livro, cap, posicao, cfg) -> Estimativa`, com
`minutos = caracteres / (chars_por_minuto × velocidade)`; `chars_por_pagina` = 1800 (EPUB); PDF usa
`caracteres / páginas` do próprio arquivo.

Frase falada (vai pelo `i18n.tr` como as outras): "Esse capítulo leva uns {min} minutos; o livro
todo, umas {horas} horas."

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
| `book.time` | "quanto falta desse livro", "quanto tempo leva {query}", "quanto falta do capítulo" | — |

`context: reading` = a frase só concorre quando `TurnContext.reading`; sem leitura, "pausa"/"para"
seguem para a música/sistema como hoje. Respostas curtas em `phrases.yaml` + `i18n/en-gb.yaml`.

## 6. Configuração (`[audiolivro]` em `~/.config/magi/config.toml`)

```toml
[audiolivro]
pasta = "~/Livros"                # D3: criada se não existir
marcacao = "qwen"                 # "qwen" (regras + Qwen local) | "regras" (D2)
musica = "pausa"                  # "pausa" | "duck" (D4)
chars_por_pagina = 1800
chars_por_minuto = 900            # Kokoro a 1,0×; calibrado na A3.1
parar_apos_capitulos = 0          # 0 = até o fim
retomar_apos_comando = true       # A6.2
pausa_expira_min = 30
qwen_container = "magi-qwen"      # vazio = não liga container (usa o que estiver de pé)
qwen_url = "http://127.0.0.1:11435"
qwen_start_timeout_s = 90
[audiolivro.vozes.en-gb]          # sobrepõe os grupos do §3: f, m, jovem, idoso = [vozes]
[tasks]
audiolivro_marca = { provider = "qwen", model = "qwen-learning", timeout_s = 60 }   # só local
```

Sem `[tasks].audiolivro_marca`, vale o padrão acima. Provedor que não seja local (`qwen`) na
marcação ou TTS que não seja `kokoro` no livro → ignorado com log (A7.2).

## 7. Critérios de aceite

- **CA-A1** EPUB de teste (fixture gerada no teste, 3 capítulos com `nav`, notas e itálico) e PDF de
  teste (gerado com `pymupdf`) extraem exatamente os parágrafos esperados, na ordem.
- **CA-A2** Para 30 parágrafos de fixture PT e EN, `marcas` devolve os tipos/emoções da tabela
  esperada; concatenação dos trechos == parágrafo (propriedade, 200 casos).
- **CA-A3** `vozes.opcoes` cobre todo par tipo × emoção × gênero × idade nos 2 idiomas da Condessa
  (pt-br, en-gb) sem `None` em `voice`; narração = voz dela; 5 personagens distintos → 5 vozes
  distintas e ≠ narração; mesmo falante → mesma voz depois de reabrir o elenco; só vozes Kokoro.
- **CA-A4** `custo.estimar` (tempo) bate com `caracteres / chars_por_minuto / velocidade` ± 1%;
  nenhum caminho do pacote chama provedor pago (`[tasks].tts` OpenAI → leitura segue no Kokoro).
- **CA-A5** Marcador: grava, sobrevive a reabrir, escrita atômica (arquivo truncado → começa do início
  do capítulo salvo no `.bak`), no máximo 1 escrita a cada 2 s em leitura contínua.
- **CA-A6** Roteador: "pausa" vai para `music.pause` sem leitura e para `book.pause` com; os 11
  intents casam suas frases-modelo; nenhum intent antigo muda de resultado (`tests/core/test_router*`).
- **CA-A7** `TurnMachine.narrate` com satélite e TTS falsos: interrupção por `wake` pausa na frase
  certa; comando de leitura retoma; outro assunto não retoma; nenhum aviso proativo fala no meio.
- **CA-A8** `say_parts` manda as `OpcoesVoz` de cada parte ao backend falso; `say`/`say_stream` iguais.
