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
livro de 300 páginas na OpenAI custaria ≈ US$ 11 — mais que o teto mensal de US$ 5; por isso o
livro é **sempre no Kokoro** (D1) e a marcação usa o **Qwen local** (D2): leitura sem custo de API.

## Objetivo

O Pedro diz "lê o livro X" e a Condessa lê como audiolivro, **com a voz dela** (D5): narração na
voz dela, cada personagem com uma voz Kokoro própria (a mesma no livro todo), emoção da cena na
velocidade e nas pausas, retomando de onde parou, com controles por voz e sem atropelar música,
jogo ou avisos.

## Critérios de sucesso

1. "Lê o livro <título>" acha o livro certo da biblioteca em ≥ 9 de 10 títulos reais do Pedro.
2. Um capítulo de EPUB e um de PDF de texto são lidos do começo ao fim sem frase perdida, repetida
   ou fora de ordem (comparação com o texto extraído).
3. Depois de "para" (ou reiniciar o `magi-core`), "continua o livro" volta no **mesmo parágrafo**.
4. Em diálogo marcado com travessão ou aspas, ≥ 90% das falas saem com a voz de personagem, e o
   mesmo personagem tem a mesma voz no livro todo (amostra de 50 falas conferidas pelo Pedro).
5. Custo de API da leitura = **0** (Kokoro + Qwen local; nada novo em `costs`).
6. Primeira frase sai em ≤ 2,5 s depois do comando (Kokoro) e sem buraco > 1 s entre trechos.

## Requisitos

**A1 — Biblioteca.** O núcleo DEVE indexar EPUB e PDF da pasta `[audiolivro] pasta` (título,
autor, idioma, capítulos) e achar o livro pelo título falado com casamento tolerante.
- A1.1 SE o título casar com mais de um livro com nota parecida, ENTÃO ela DEVE perguntar qual.
- A1.2 SE o PDF não tiver texto (escaneado), ENTÃO ela DEVE dizer que não lê esse e não gastar nada.

**A2 — Extração.** O núcleo DEVE extrair capítulos → parágrafos → frases, na ordem de leitura,
sem cabeçalho/rodapé/número de página repetidos (PDF) e sem notas/índice (EPUB `nav`/`toc`).

**A3 — Trechos marcados.** O núcleo DEVE dividir cada parágrafo em trechos `narracao` / `fala` /
`pensamento` / `titulo`, com `emocao` e, quando der, `falante`, gênero e idade (spec §2), por
**regras locais** (travessão, aspas, verbos de elocução, pontuação) — sempre.
- A3.1 ONDE `[audiolivro] marcacao = "qwen"` (padrão, D2), o núcleo DEVE refinar falas, emoção e
  personagem por capítulo com o **Qwen local** de `[tasks].audiolivro_marca` (sem rede; liga o
  container `magi-qwen` quando preciso), em segundo plano à frente da leitura, guardar o resultado
  em cache por livro e **nunca** mudar o texto (só as marcas). SE o Qwen não estiver de pé, falhar
  ou responder fora do formato, ENTÃO vale a regra. Nunca LLM pago.

**A4 — Voz por trecho.** O núcleo DEVE traduzir cada trecho em opções do Kokoro (voz, velocidade,
`lang`, pausa depois) pelo spec §3: narração na voz dela; cada personagem com uma voz Kokoro
diferente no idioma dela (por gênero/idade/papel quando der para inferir), **a mesma voz para o
mesmo personagem no livro todo** (elenco persistido por livro); velocidade e pausa pela emoção.
O texto do livro NÃO DEVE passar pelo `i18n.tr` nem ser traduzido; é lido com a voz e o idioma
configurados da Condessa, qualquer que seja o idioma do livro (D5).

**A5 — Marcador.** O núcleo DEVE guardar por livro: capítulo, parágrafo, frase e velocidade, em `~/.local/state/magi/audiolivro.json` (escrita atômica), a cada frase iniciada.

**A6 — Controles por voz.** QUANDO o Pedro disser (depois da palavra de ativação ou do clique no
rosto) um comando da spec §5, o núcleo DEVE executá-lo: ler, continuar, pausar, parar, voltar/pular
parágrafo, repetir, próximo/anterior capítulo, mais devagar/mais rápido, onde parou, quanto tempo
falta, que livros tem.
- A6.1 ENQUANTO houver leitura ativa ou pausada há ≤ 30 min, "pausa", "para", "continua" e "volta"
  DEVEM ir para o livro, não para a música.
- A6.2 QUANDO uma ativação interromper a leitura, a leitura DEVE pausar na frase em curso; depois
  de um comando de leitura ela DEVE retomar sozinha; depois de outro assunto, NÃO DEVE retomar
  sozinha (fica pausada; "continua" retoma).

**A7 — Sem custo de API (D1, D2).** A leitura NÃO DEVE usar provedor pago: TTS sempre Kokoro
(mesmo que o `[tasks].tts` ativo seja outro) e marcação só regras + Qwen local. Nada vai ao
`Budget`.
- A7.1 O núcleo DEVE estimar o **tempo** de leitura (capítulo e resto do livro, spec §4) e dizê-lo
  quando pedido ("quanto falta desse livro").
- A7.2 SE a configuração apontar o TTS ou a marcação do livro para um provedor pago, ENTÃO o
  núcleo DEVE recusar esse provedor (Kokoro/regras) e logar o motivo.

**A8 — Convivência.** ENQUANTO lê:
- A8.1 avisos proativos (notícias, alertas, sugestão de música) NÃO DEVEM falar por cima: viram
  legenda, como numa call (o `ProactiveSink` já faz isso por estar `SPEAKING`).
- A8.2 ONDE `[audiolivro] musica = "pausa"`, a música DEVE pausar ao começar e voltar ao parar.
- A8.3 com jogo aberto a leitura DEVE funcionar (o ducking do satélite abaixa o jogo); reações de
  rosto continuam pelas regras do HUD.
- A8.4 em call no Discord a leitura NÃO DEVE começar (ela diz que espera a call acabar).

**A9 — Honestidade.** Ela NÃO DEVE inventar, resumir ou pular texto; a marcação só escolhe voz.

**A10 — Registro.** Cada sessão de leitura DEVE gravar em `~/.local/state/magi/audiolivro.jsonl`:
livro, de/até (cap/par), caracteres, segundos, marcação usada (regras/qwen) e personagens novos.

## Fora do escopo

Livros com DRM; PDF escaneado (OCR); exportar MP3; ler na Rádio Ayanami; voz clonada (§10).

## Decisões (Pedro, 2026-10-10 — `specs/DECISOES-2026-10-10.md`)

- **D1 — Voz.** **Kokoro sempre** (nada de voz OpenAI paga). Vozes caprichadas: narração com uma
  voz; personagens com vozes Kokoro diferentes (gênero/idade/papel quando der para inferir), a mesma
  voz para o mesmo personagem no livro todo (persistida por livro); velocidade/pausa pela emoção.
- **D2 — Marcação.** **Regras + Qwen local** (sem rede; liga o container `magi-qwen` quando preciso).
  As regras rodam sempre; o Qwen refina falas, emoção e personagem; Qwen fora do ar → só regras.
- **D3 — Pasta da biblioteca.** **`~/Livros`** (criada se não existir; `[audiolivro] pasta`).
- **D4 — Música durante a leitura.** Pausa e volta no fim. *(padrão confirmado)*
- **D5 — Idioma.** **Sempre a voz dela** (voz/idioma configurado da Condessa), qualquer que seja o
  idioma do livro; as vozes de personagem são variações Kokoro no idioma dela.
- **D6 — Dependência de PDF.** **`pymupdf`** (melhor em colunas; AGPL aceita para uso pessoal).
- A validação ao vivo (A3.1) fica com o Pedro.
