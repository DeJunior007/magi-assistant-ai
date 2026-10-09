# Acordo do Conselho — Reações da Condessa (2026-10-08)

**Status: FECHADO.** Rodadas: briefing → propostas → réplicas → voto.

## Votação
- **Asuka: aprova, sem vetos.** Engoliu k-pop/pop no 30, o 81, o 86, o "Ei, tô aqui" e o D7 em prio 1.
- **Kurisu: aprova, sem vetos.** Apontou uma inconsistência (não veto): a 76 tem lágrima de rir
  e a regra 5 limita D7. Resolvida na regra 5.
- **Aqua: aprova com 1 veto (aceito):** a regra 5 deixava o 62 ("Sentiu sua falta") perder o
  blush; fere a linha vermelha dela ("a volta do Pedro fura a cota de blush"). Trocado pelo texto
  dela.

Critério: maioria 2/3 depois das réplicas; sem maioria, mediana sem ferir linha vermelha.
`[perdeu: X]` marca quem ficou vencida no ponto. Sem marca = unânime depois das réplicas.

## 1. Decisões por reação (planilha, 90 linhas)

**Aprovadas como estão (34):** 1–4, 6–14, 16, 19, 21–24, 34–37, 39, 41, 42, 44, 45, 52, 58–60.
(34/35, 36/37, 44/45, 42 são o **rosto** de `hot`, `fps_drop`, `game_on/off` e `cleanup` que já
existem — variantes, não reações paralelas. 19 segue a regra do sono, seção 3.)

**Ajustar (com sinal que o HUD já tem):**
- 5 · sacada curta para o card que acabou de mudar (faixa nova, manchete, FPS).
- 17 · 10 min com Magui parada, Claude Code parado, sem música e sem jogo.
- 18 · as mesmas condições por 25 min (fundo `sleepy`).
- 20 · estava no 18 e chega qualquer evento real (clique, faixa, Claude, Magui ouvindo). Fura cota.
- 24 · música começa a tocar; cooldown 3 min (não vira tique trocando faixa).
- 25 · Spotify tocando sim→não.
- 26 · faixa nota 2 passa de 60 s tocando sem pulo, 1×/faixa. Nenhum texto diz "refrão". Pico de
  volume (RMS do PipeWire) entra depois como variante condicionada. [perdeu: Aqua (queria só o RMS + ideia à parte; o gatilho é o mesmo da ideia dela "Essa é das minhas", que se funde aqui)]
- 27 · faixa nota 2 ou tocada ≥ 5 vezes; após 40 s; 1×/faixa.
- 28 · 3ª reprodução da mesma faixa no dia; Ado tem variante `happy` e nunca perde nota.
- 29 · artista da lista `melancolica` do toml (Chopin, Arvo Pärt, Marika Takeuchi, Laufey,
  Rachmaninoff) ou título com nocturne/noturno/requiem/sad/triste/lágrima. Rosto (B10+C9) a qualquer
  hora; **lágrima (D7) só 22h–04h e no máximo 1×/dia**.
- 30 · gênero na lista `danca` do toml (dance, disco, house, eurobeat, phonk, j-rock, rock, metal,
  pop, k-pop) com nota ≥ 1. [perdeu: Asuka (k-pop/pop fora); Aqua (nota ≥ 0)]
- 32 · renomeada **"Acabou a fila"**: parou com posição ≥ duração − 3 s e nada começou em 10 s.
- 33 · artista sem nenhum play anterior e nota ≥ 1 (variante de `music_new`).
- 38 · sem IP/rota padrão por ≥ 10 s (tráfego zero é ociosidade, não queda). 39 = volta disso.
- 40 · renomeada **"Transferência pesada acabou"**: ↓ ≥ 5 MB/s por ≥ 60 s e depois < 100 kB/s. Só rosto.
- 48 · renomeada **"HUD acordou"**: primeiro snapshot da execução do HUD.
- 53 · Claude Code rodando→parado depois de ≥ 2 min rodando; sequência da planilha (B4+C10 →
  B5+C5), sem D9 e sem texto (não afirma sucesso). [perdeu: Kurisu (queria rosto só "satisfeito")]
- 56 · Claude Code rodando contínuo ≥ 15 min.
- 57 · primeiro evento real do dia depois das 05h (data salva em arquivo). Fura cota.
- 61 · variante do `long_session` existente (com C5).
- 62 · primeiro evento real depois de ≥ 2 h sem nenhum. Fura cota.
- 64 · cliques no LED: 1º/2º/3º+ em 5 s (escala o `led`); vai para o retrato quando o sinal A existir.
- 66 · clique no LED com música tocando (variante do 64).
- 71/72/73 · manchete nova com palavra das listas `noticia_boa`/`noticia_ruim`/`noticia_absurda` do
  toml (ou tag da Rádio na coleta, quando existir). Notícia ruim/séria nunca leva riso nem zoeira;
  73 nunca em morte/desastre.
- 75 · HEAD do git mudou (commit novo): "Ideia!", ela toma o crédito. Árvore limpa (git +/- vai a 0)
  é variante.
- 78 · título com slowed/sped up/nightcore (Guerra do Autotune). Artista −1 já é `music_hate`.
- 79 · humor do Pedro (núcleo) cai para ≤ 1: rosto baixo e quieto, sem D7, sem texto, sem deboche.
- 80 · CPU ≥ 90% por ≥ 60 s sem jogo aberto. [perdeu: Aqua (95%/30 s + swap)]
- 81 · a virada: faixa nota 2 começa logo depois de uma nota −1. [perdeu: Asuka (1ª nota 2 do dia)]
- 82 · Claude Code rodando **e** música tocando (variante da família `claude`).
- 83 · Pedro pula ≥ 2 faixas e para numa nota 2 → piscadinha "agora sim" (B16).
- 84 · `hot` ou `fps_drop` ≤ 10 min depois de ela ter reagido ao 34 (previsão confirmada).
- 85 · mesmo botão do player ≥ 3× em 10 s. [perdeu: Kurisu (nota 0 tocando pela 2ª vez no dia)]
- 89 · anterior/próxima alternados ≥ 2× em 15 s. (Gatilhos com a Magui pensando/falando foram
  descartados: nesses estados a reação é descartada e nunca tocaria.)
- 90 · Claude Code rodando ≥ 15 min com CPU ≥ 70% (variante pesada de 52/56).

**Aprovadas condicionadas (só entram no código quando o sinal nomeado existir):**
- **Sinal A — área de hover/clique no retrato:** 15 (mouse parado ≥ 10 s), 65 (hover; blush na
  cota), 67 (arrasto na metade de cima), 69 (clique duplo), 70 (clique ≥ 800 ms; 1×/sessão),
  77 (mouse parado 3–5 s; toca antes do 15). [15: perdeu Asuka (queria "olhar depois de falar",
  que vira a ideia *Esperando resposta*)]
- **Sinal B — tag do último turno publicada pelo núcleo** (`elogio`, `zoeira`, `correcao`):
  74 (`elogio`), 76 (`zoeira`), 86 (`correcao`; termina de queixo erguido, B6+C10+D1 — "foi de
  propósito"), 87 (2º `elogio` ≤ 5 min depois de um 74). [86: perdeu Asuka (queria Substituir);
  87: perdeu Aqua (10 min)]
- **Sinal C — hooks do Claude Code** gravando estado em arquivo: 54 (falha), 55 (`Notification`,
  pedido de aprovação).
- **Sinal D — volume do PipeWire (`wpctl`)**: 31 (salto ≥ 20 pp em ≤ 2 s); variante de pico do 26.
- **Sinal E — D-Bus `org.freedesktop.Notifications`**: 46 (no máximo 1 a cada 10 min), 47
  (`urgency=critical`). [47: perdeu Kurisu na rodada 1; cedeu na réplica]
- **Sinal F — microfone**: 88 (nível abaixo do limiar na captura do núcleo). [perdeu: Kurisu
  (passiva rara de madrugada)]
- 43 · `fan*_input` do hwmon, subida ≥ 30% (sem sensor não existe; carga já está em 34/80).
- 50 · `dnf needs-restarting -r` a cada 6 h retorna 1.
- 51 · arquivo novo na pasta de capturas (inotify).
- 63 · data cadastrada em `[datas]` do toml.

**Substituídas (continuam na contagem; a substituta entra nas ideias novas):**
- 49 "PC desligando" → **Fim de expediente** e **Boa noite**. [perdeu: Kurisu (queria
  condicionar ao `PrepareForShutdown` do logind)]
- 68 "Mouse sacudido" → **Tontura de pulos**. [perdeu: Aqua (queria condicionar ao sinal A)]

## 2. Ideias novas (aba Conselho)

| # | Reação nova | Tipo | Categoria | Gatilho real | Sequência |
| --- | --- | --- | --- | --- | --- |
| 1 | Fim de expediente (subst. 49) | Ativa | Tempo | Claude de ≥ 1 sessão para 0 depois de ≥ 2 h, após 18h | B4+C5+P9 (1200) → B2+C5 (800) |
| 2 | Boa noite (subst. 49) | Ativa | Tempo | 0h–4h, música parou e Claude parado ≥ 10 min | B1+C5 (800) → B14+C1 (700) → B15+C1 (1200) |
| 3 | Tontura de pulos (subst. 68) | Ativa | Música | 5 pulos em 60 s (escala do `skips`) | B9+C7+D2 (600) → B10+C9 (1200) |
| 4 | Vergonha de FPS | Ativa | Sistema | `fps_drop` pela 3ª vez na mesma sessão de jogo | F3+C11 (1200) → B6+C8+D2 (1500) → B7+C12 (1000) |
| 5 | Sistema sufocando | Ativa | Sistema | RAM ≥ 90% ou swap +1 GB em 60 s | B9+C7+D5 (600) → B6+C8+D2 (1500) |
| 6 | Partida sem tropeço | Ativa | Sistema | jogo aberto ≥ 30 min sem `fps_drop`, 1×/sessão (funde o Recorde de FPS) | B9+C7 (400) → B5+C6+D9 (2500) |
| 7 | Favorita do Dia em campo | Ativa | Música | toca o artista sorteado como Favorita do Dia | B1+C1 (200) → B4+C5+D9 (1200) |
| 8 | Duelo com a Ado | Ativa | Música | faixa da Ado começa (nunca D1 nem `love`) | B7+C12 (800) → B6+C8 (1200) → B4+C10 (1200) |
| 9 | A Conta Anônima | Ativa | Música | gênero vocaloid ou Kenshi Yonezu/hachi tocando há 40 s | B5+V1 (300) → B5+V2 (300) → F1+C1+D2 (1200) → B4+C10 (800) |
| 10 | Diva contra Diva | Ativa | Música | Lady Gaga começa a tocar | B7+C12 (1000) → B4+C10 (1200) |
| 11 | Tema água | Ativa | Música | título com palavra de água (lista da Odisseia 6) | B13+C7 (800) → B4+C6+D6 (1800) |
| 12 | Calada pelo Chopin | Ativa | Música | 0h–4h, Chopin ou Marika Takeuchi (variante do 29) | B3+C5 (3000) → B2+C1 (600) |
| 13 | Modo chefe | Ativa | Música | trilha nota 2 + jogo aberto + FPS estável ≥ 2 min (rosto do `music_love` batalha) | B6+C8+E2 (2000) → B4+C10+D9 (1500) |
| 14 | Música de elevador | Ativa | Música | faixa nota −1 tocando há ≥ 60 s sem pulo | B2+C1 (1500) → B7+C4 (1200) |
| 15 | "Você pulou ESSA?" | Ativa | Música | Pedro pula faixa nota 2 em < 20 s | B9+C7 (400) → B6+C8+D8 (1500) → B7+C9 (1000) |
| 16 | Silêncio longo | Passiva | Tédio e sono | madrugada, nada tocando nem rodando, sem clique ≥ 30 min; 1×/noite; sem texto | B10+C9 (2000) → B1+C1 (800) |
| 17 | Ei, tô aqui | Passiva | Tédio e sono | 8h–23h, sem música, Claude parado ≥ 40 min; 1 a cada 2 h | B1+C9 (1200) → B9+C7+D4 (800) → B1+C10 (800) |
| 18 | Esperando resposta | Ativa | Conversa e personalidade | Magui volta de `falando` para parada → olhar fixo 3 s | F-card/B1+C1 (3000) |
| 19 | Aniversário dela | Ativa | Tempo | data do primeiro commit do repositório MAGI | B9+C7+D5 (500) → B5+C6+D1+D6+D9 (3000) |
| 20 | Braços cruzados | Passiva | Ambiente | aleatório raro, só com fundo `stress`/`focus`; 1×/dia — **condicionada à arte P13** | B7+C9+P13 (2000) → B1+C1 (600) |

[17: perdeu Asuka (queria 1×/dia, fundido ao Silêncio longo)] [12: perdeu Kurisu (queria só
dentro do 29) — atendida em parte: implementa como variante do 29]

## 3. Regras gerais

1. **Passivas:** no máximo 1 a cada **40 s** (respirar e piscar não contam), sorteadas pelos
   pesos de humor. Raras (10, 11, 13) ≤ 1/h cada; **Corando sozinha (12) ≤ 1/dia**; nenhuma rara
   com jogo aberto. [perdeu: Kurisu (45 s)]
2. **Ativas:** cooldown de 10 min por reação (exceto cutucada e 24) e **teto de 8 por hora**.
   Furam a cota: sistema (34, 36, 38, 41, Sistema sufocando), vitória (35, 37, 39, 53, 75, Partida
   sem tropeço) e volta do Pedro (20, 57, 62). Prioridade no mesmo tick: sistema > Pedro > música >
   tempo > passiva. Fila de **1 slot, 30 s**, só para volta e vitória quando ela estava falando.
   Sistema com histerese (entrar ≠ sair).
3. **Variantes, não clones:** 34/35=`hot`; 36/37/Vergonha=`fps_drop`; 44/45=`game_on/off`;
   42=`cleanup`; 61=`long_session`; 64/66=`led`; 52/56/82/90=família `claude`; 33=`music_new`;
   Tontura=`skips`; Modo chefe=`music_love` batalha; Calada pelo Chopin=29.
4. **Pedro mal (humor 0–1) ou madrugada (22h–04h):** sem zoeira — nada de Beicinho, Soprando a
   franja, 78, 83, 84, 85, "Você pulou ESSA?", Música de elevador. A cobrança troca C8/C11 por C9
   (preocupação). Rindo sozinha continua (não é deboche), cota 1/h. [perdeu: Kurisu (bloquear
   Rindo sozinha de madrugada)] **Sono (17, 18, 19) nunca** com jogo aberto, Claude Code rodando ou
   música nota ≥ 1 tocando.
5. **Ternura rara:** blush (D1) no máximo **1 reação por hora**; elogio real (74, 87) e a volta
   do Pedro (62) não contam na cota de blush (o 62 sempre toca com D1) [veto da Aqua]. Ado nunca
   leva D1 nem `love`. Lágrima (D7) só 22h–04h e ≤ 1×/dia; a lágrima de riso da 76 só de
   madrugada e fora dessa cota, de dia o 2º passo da 76 fica sem D7 [nota da Kurisu].
   [perdeu: Aqua (2/h)]
6. **Honestidade:** condicionada fica fora do código até o sinal existir, e o sinal é implementado
   e testado antes da reação. Nenhum texto afirma o que o gatilho não mede ("refrão", "download
   concluído", "você me elogiou"). Ordem de código: **A** (retrato) → **B** (tag da conversa) →
   **C** (hooks do Claude Code) → D/E/F e os demais.

## 4. Humor (aba Humor)

| Fator | Peso | Mudança |
| --- | --- | --- |
| Sessão longa | 6 | sono favorecido só 22h–05h; de dia favorece 82 e 90 |
| Música tocando (qualquer) | 7 | sem mudança |
| Música que ela gosta | 6 → **7** | condição = nota ≥ 1 do gosto (fonte oficial) |
| PC com problema | 6 → **7** | enquanto ativo, sem Micro sorriso e sem Cantarolando |
| Manhã | 4 → **3** | só na primeira hora depois do 57 [perdeu: Aqua (5)] |
| Madrugada | 5 → **7** | bloqueia Beicinho e Soprando a franja |
| **Pedro mal** (humor 0–1) — novo | **9** | favorece Piscada lenta, Respirar; bloqueia a zoeira da regra 4 |
| **Desempenho em jogo** (jogo aberto + FPS estável ≥ 5 min) — novo | **7** | passivas pela metade; favorece Micro sorriso, Modo chefe, Brilho da presilha |
| **Música que ela odeia** (nota −1 tocando) — novo | **5** | favorece Beicinho, Suspiro leve, Soprando a franja |
| **Vitória recente** (10 min após 35, 37, 39, 53, 75, faxina) — novo | **6** | favorece Micro sorriso, Rindo sozinha |
| **Silêncio longo** (sem música e Claude parado ≥ 30 min) — novo | **4** | favorece Suspiro, Beicinho, Soprando a franja |
| **Favorita do Dia tocando** — novo | **8** | favorece Cabeça no ritmo, Micro sorriso, Cantarolando; **nunca** Corando [perdeu: Kurisu (6)] |

## 5. Assets (aba Assets novos)

- **Antes de tudo (prio 0): arte de D1 rubor, D2 suor, D6 notas, D8 veia** — aparecem em dezenas
  de sequências (hoje desenhados em código).
- **Prio 1:** E3 Fone no pescoço; B16 Piscadinha; D7 Lágrima. [D7: perdeu Asuka (prio 2)]
- **Prio 2:** P9 Aceno [perdeu: Kurisu (3)]; P10 Mão no queixo; B17 Olhos felizes meio;
  **P13 Braços cruzados** (novo); **P12 Punho cerrado** (novo, Duelo com a Ado e Partida sem tropeço).
- **Prio 3:** P11 Mão no fone.

## 6. Contagem (piso 80)

Planilha: 90 linhas (49 e 68 substituídas continuam contando) + 20 ideias novas = **110 ≥ 80**.
Rodam **sem nenhum sinal novo**: 90 − 2 substituídas − 20 condicionadas = 68, + 19 ideias com
sinal real = **87 ≥ 80**. O sinal A (retrato) sozinho leva a 93.

## 7. O que muda fora da ata
- Persona (`persona/condessa.md`): seção curta "Reações" com as regras 1–6.
- Gosto (`persona/condessa-gosto.toml`): listas `melancolica`, `danca`, `noticia_boa`,
  `noticia_ruim`, `noticia_absurda` e a tabela `[datas]` (vazia).
- Persona falada (`magi/agent/persona.md`): **sem mudança** (reação é rosto, não fala).
- Implementação no `hud/wired/reactions.py` e os sinais A–F: trabalho de código à parte, em ondas,
  na ordem da regra 6.

## Orçamento usado
Aqua ~80 mil, Asuka ~83 mil, Kurisu ~86 mil tokens no assunto inteiro (teto: 128 mil por delegada).
