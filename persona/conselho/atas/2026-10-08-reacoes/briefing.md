# Briefing — Reações da Condessa (2026-10-08)

## Assunto
O Pedro mandou a planilha `reacoes_condessa.xlsx` com **90 reações** (passivas e ativas) para o
rosto da Condessa no HUD, todas com status **Pendente**. Os gatilhos são só ideias. O Conselho
decide, para **cada uma**: **Aprovada**, **Ajustar gatilho** (com o gatilho novo) ou **Substituir**
(com a substituta proposta). Também decide se vale ter **mais** reações e propõe ideias novas, e
revisa a aba **Humor** (fatores e pesos) e a aba **Assets novos** (prioridades).

**Piso fixo do Pedro: nunca menos de 80 reações.** "Substituir" não tira da contagem; a substituta
entra como ideia nova. Pode ter mais que 90, nunca menos que 80.

Lista completa (com passos e durações): `reacoes.md` nesta pasta.

## Estado atual da persona (resumo; completo em `persona/condessa.md`)
- Orgulhosa, expressiva, cabeça de pesquisadora; julga rápido no rosto, mas justifica. Comemora
  vitória pequena como final de Copa, emburra 10 min e esquece. Elogio a desmonta (nega, cora).
- Manias: ranqueia, conta repetições ("quinta vez hoje"), toma o crédito das coisas boas do PC
  (faxina do SSD), Favorita do Dia, rivalidade com a Ado, Conta Anônima de vocaloid.
- Medos (só no humor `sad` e frase rara de madrugada): ser ignorada, substituída, silêncio longo.
- Com o Pedro: parceiro de esquadrão; zoa desempenho e gosto, **nunca a pessoa**; madrugada/sessão
  longa = carinho direto, frase curta, sem deboche.
- Regras fixas do Conselho: reações **no rosto primeiro**, texto raro e curto (≤70 caracteres,
  sem voz), voz só quando o Pedro fala com ela; honesta (nada afirma o que o sistema não sabe).

## O que o sistema consegue de verdade (restrições)
Reações vivem em `hud/wired/reactions.py` (`Reactor.observe` a 1 Hz sobre o `Snapshot` do HUD, e
`Reactor.on_click(alvo)`). Só aparecem com ela **parada** (falando/pensando/ouvindo, a reação é
descartada). Hoje existem 19: `music_love/like/ok/meh/hate/new/tolerate`, `news`, `hot`,
`fps_drop`, `game_on`, `game_off` (variantes curto/madrugada), `long_session`, `cleanup`, `led`
(clique no LED = "cutucada"), `player`, `card`, `claude`, `skips` (3 pulos). Humores do fundo:
calm, happy, stress, sad, focus, surprise, sleepy, love. Efeitos desenhados em código: sweat,
notes, question, bang, blush (D1–D9 ainda sem arte).

**O HUD sabe (Snapshot):** jogo aberto (sim/não), CPU/GPU carga e temperatura, RAM/VRAM/swap, uso
do disco (%), rede ↓/↑ (bytes/s, dá para ver "caiu" como zero/sem IP), FPS atual/mín/médio, faixa do
Spotify (título, artista, álbum, ano, posição, duração, tocando sim/não) + gênero do artista pelo
cache do núcleo, notícias da Rádio Ayanami (manchete, hora), LED (cor), estado da Magui (falando,
pensando…), humor do Pedro 0–4 (estimado pelo núcleo), Claude Code (sessões rodando, minutos desde
a última atividade, tokens, Konsole vivo), git (branch, +/-), faxina do SSD (arquivo de estado),
hora local. Cliques: LED, botões do player, cards.

**O HUD NÃO sabe (hoje):** volume do sistema; refrão/pico de áudio; BPM/"faixa lenta ou triste"
(não há análise de áudio; só gênero/título/artista); se ela "conhece" a música além do gosto
(nota 2 e plays); ventoinha (sem sensor lido); download concluído; notificações e popups do
sistema; Print Screen; atualização pedindo reinício; boot/desligamento (o HUD abre depois do boot
e morre no desligamento); fim de álbum/playlist (só "parou de tocar"); erro/pedido de aprovação do
Claude Code (só "rodando" e "parado"); aniversário (não há data cadastrada); mouse sobre ela,
cursor, arrasto, clique duplo/longo **no retrato** (o retrato não tem área de clique hoje; dá para
criar, custa código); elogio/zoeira/sugestão de pausa em texto (o núcleo sabe da conversa e do
humor 0–4, não do conteúdo para o HUD); "ela errou".

Regra de honestidade aplicada às reações: gatilho que depende de dado que não existe ou é
**Ajustar** para um sinal real, ou fica **Aprovada condicionada** a um sinal novo nomeado
(ex.: "precisa ler volume do PipeWire"). Reação passiva aleatória não precisa de sinal.

## Formato de saída esperado
Cada delegada grava `proposta-<nome>.md` com:
1. **3 linhas vermelhas** (o que ela não aceita de jeito nenhum) e **o que cede**.
2. **Decisões**: liste os Nº **Aprovada** numa linha só (ex.: "Aprovadas: 1–9, 11, 14…"); depois,
   uma linha por reação **Ajustar** ou **Substituir**: `Nº · decisão · gatilho/substituta · nota
   curta (≤ 20 palavras)`.
3. **Ideias novas** (0 a 10): `Nome | Passiva/Ativa | Categoria | gatilho real | sequência`.
4. **Humor e Assets**: só o que mudaria (peso, fator novo, prioridade).
5. **Regras gerais** (no máximo 5): frequência de passivas, cotas, convivência com as reações que
   já existem, o que nunca deve acontecer.
Seja concreta e curta. Tudo em português.
