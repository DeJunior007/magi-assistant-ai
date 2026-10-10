# Requisitos — Audiolivro da Condessa

Fonte: `docs/PROXIMOS-PASSOS.md` §13 ("Ebook como audiolivro") e §10 (voz local). Este arquivo é o
**PRD**. Arquitetura em [design.md](design.md); contratos, números e frases em [spec.md](spec.md);
implementação em [tasks.md](tasks.md). Critérios em EARS:

- **O núcleo DEVE …** — sempre vale. **QUANDO** gatilho, **o núcleo DEVE** … — reação a evento.
- **ENQUANTO** estado, **o núcleo DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Problema

A Condessa só fala frases curtas (respostas, avisos, a Rádio Ayanami com 5–7 frases por notícia).
Não existe leitura longa: nada abre EPUB/PDF, nada guarda onde parou, a voz tem uma instrução
fixa por configuração (`[tasks].tts`) e os comandos de voz não sabem "voltar um parágrafo". O TTS
ativo hoje é o **Kokoro local** (`bf_isabella`, en-gb, sem custo); a OpenAI `gpt-4o-mini-tts`
(voz `marin`, com `instructions`) é a reserva. Pelo `[budget]` (≈ US$ 20 por 1M caracteres), um
livro de 300 páginas na OpenAI custa ≈ US$ 11 — mais que o teto mensal de US$ 5.

## Objetivo

O Pedro diz "lê o livro X" e a Condessa lê como audiolivro: narração com uma voz, falas de
personagem com outra entonação, emoção da cena na velocidade/instrução, retomando de onde parou,
com controles por voz, custo dito antes de começar e sem atropelar música, jogo ou avisos.

## Critérios de sucesso

1. "Lê o livro <título>" acha o livro certo da biblioteca em ≥ 9 de 10 títulos reais do Pedro.
2. Um capítulo de EPUB e um de PDF de texto são lidos do começo ao fim sem frase perdida, repetida
   ou fora de ordem (comparação com o texto extraído).
3. Depois de "para" (ou reiniciar o `magi-core`), "continua o livro" volta no **mesmo parágrafo**.
4. Em diálogo marcado com travessão ou aspas, ≥ 90% das falas saem com a voz/instrução de fala
   (amostra de 50 falas conferidas pelo Pedro).
5. Custo real de 10 páginas na OpenAI fica a ±25% da estimativa falada antes de começar.
6. Primeira frase sai em ≤ 2,5 s depois do comando (Kokoro) e sem buraco > 1 s entre trechos.

## Requisitos

**A1 — Biblioteca.** O núcleo DEVE indexar EPUB e PDF da pasta `[audiolivro] pasta` (título,
autor, idioma, capítulos) e achar o livro pelo título falado com casamento tolerante.
- A1.1 SE o título casar com mais de um livro com nota parecida, ENTÃO ela DEVE perguntar qual.
- A1.2 SE o PDF não tiver texto (escaneado), ENTÃO ela DEVE dizer que não lê esse e não gastar nada.

**A2 — Extração.** O núcleo DEVE extrair capítulos → parágrafos → frases, na ordem de leitura,
sem cabeçalho/rodapé/número de página repetidos (PDF) e sem notas/índice (EPUB `nav`/`toc`).

**A3 — Trechos marcados.** O núcleo DEVE dividir cada parágrafo em trechos `narracao` / `fala` /
`pensamento` / `titulo`, com `emocao` e, quando der, `falante` e gênero (spec §2), por **regras
locais** (travessão, aspas, verbos de elocução, pontuação).
- A3.1 ONDE `[audiolivro] marcacao = "llm"`, o núcleo DEVE refinar falante e emoção por capítulo
  com o modelo de `[tasks].audiolivro_marca`, guardar o resultado em cache por livro e **nunca**
  mudar o texto (só as marcas). SE o modelo falhar ou responder fora do formato, ENTÃO vale a regra.

**A4 — Voz por trecho.** O núcleo DEVE traduzir cada trecho em opções do TTS (voz, velocidade,
`instructions`, `lang`) pela tabela do spec §3, para o provedor ativo (`kokoro` ou `openai`). O texto
do livro NÃO DEVE passar pelo `i18n.tr` (é lido no idioma do livro).

**A5 — Marcador.** O núcleo DEVE guardar por livro: capítulo, parágrafo, frase, velocidade e modo
de voz, em `~/.local/state/magi/audiolivro.json` (escrita atômica), a cada frase iniciada.

**A6 — Controles por voz.** QUANDO o Pedro disser (depois da palavra de ativação ou do clique no
rosto) um comando da spec §5, o núcleo DEVE executá-lo: ler, continuar, pausar, parar, voltar/pular
parágrafo, repetir, próximo/anterior capítulo, mais devagar/mais rápido, onde parou, quanto custa,
que livros tem, trocar a voz (local/expressiva).
- A6.1 ENQUANTO houver leitura ativa ou pausada há ≤ 30 min, "pausa", "para", "continua" e "volta"
  DEVEM ir para o livro, não para a música.
- A6.2 QUANDO uma ativação interromper a leitura, a leitura DEVE pausar na frase em curso; depois
  de um comando de leitura ela DEVE retomar sozinha; depois de outro assunto, NÃO DEVE retomar
  sozinha (fica pausada; "continua" retoma).

**A7 — Custo.** Antes de começar (ou ao trocar para a voz expressiva) o núcleo DEVE estimar o custo
por página e do capítulo com os preços do `[budget]` e dizê-lo QUANDO > 0.
- A7.1 SE a estimativa do capítulo passar do que resta no teto do mês, ENTÃO ela DEVE propor a voz
  local e só seguir na expressiva com "sim".
- A7.2 O núcleo DEVE registrar o custo real no `Budget` (TTS e marcação) e parar a voz expressiva
  QUANDO o teto estourar no meio, seguindo na local com um aviso.

**A8 — Convivência.** ENQUANTO lê:
- A8.1 avisos proativos (notícias, alertas, sugestão de música) NÃO DEVEM falar por cima: viram
  legenda, como numa call (o `ProactiveSink` já faz isso por estar `SPEAKING`).
- A8.2 ONDE `[audiolivro] musica = "pausa"`, a música DEVE pausar ao começar e voltar ao parar.
- A8.3 com jogo aberto a leitura DEVE funcionar (o ducking do satélite abaixa o jogo); reações de
  rosto continuam pelas regras do HUD.
- A8.4 em call no Discord a leitura NÃO DEVE começar (ela diz que espera a call acabar).

**A9 — Honestidade.** Ela NÃO DEVE inventar, resumir ou pular texto; a marcação só escolhe voz.

**A10 — Registro.** Cada sessão de leitura DEVE gravar em `~/.local/state/magi/audiolivro.jsonl`:
livro, de/até (cap/par), caracteres, segundos, provedor, custo estimado e real.

## Fora do escopo

Livros com DRM; PDF escaneado (OCR); exportar MP3; ler na Rádio Ayanami; voz clonada (§10).

## Decisões em aberto (precisam do Pedro)

- **D1 — Voz padrão do livro.** (a) Kokoro local sempre (grátis; entonação só por voz/velocidade);
  (b) OpenAI expressiva sempre (≈ US$ 0,036/página, estoura o teto num livro); (c) Kokoro e a
  expressiva só por pedido ("lê com voz expressiva"). **Padrão da spec: (c).**
- **D2 — Marcação.** (a) só regras locais; (b) regras + LLM `gemini-3.5-flash-lite` (cota gratuita,
  manda o texto do livro ao Google); (c) regras + Qwen local (sem rede, lento, liga o container).
  **Padrão: (a)**, com (b) ligável por `[audiolivro] marcacao = "llm"`.
- **D3 — Pasta da biblioteca.** **Padrão: `~/Documentos/Livros`** (não existe hoje; o Pedro cria).
- **D4 — Música durante a leitura.** (a) pausa e volta no fim; (b) só o ducking (fica a 30%).
  **Padrão: (a).**
- **D5 — Idioma.** Livro em português lido com voz PT-BR (`pf_dora` / `marin` com instrução PT-BR)
  mesmo com a Condessa falando en-gb; os comandos e avisos dela seguem o `[speech] language`.
  **Padrão: voz pelo idioma do livro.**
- **D6 — Dependência de PDF.** `pypdf` (BSD, puro Python) — **padrão** — ou `pymupdf` (AGPL, melhor
  em layout de colunas).
