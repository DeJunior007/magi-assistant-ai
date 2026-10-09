# Proposta da Aqua — Reações (Rodada 1)

> Noventa caras novas e alguém aqui quer cortar? Nem pensar. A Condessa é uma DIVA, ela tem que
> chorar, rir, cantar e comemorar na frente de todo mundo. Mas tá bom, tá bom, a Kurisu vai
> chorar se eu inventar sinal, então tudo que não existe eu amarrei num sinal de verdade ou num
> sinal novo com nome. Viram? Eu sei ser responsável. Às vezes.

## 1. Linhas vermelhas e concessões

**Linhas vermelhas**
1. **Emoção grande não é cortada.** Lágrima (29, 79), riso (11, 76), festa (26, 27, 30, 37, 53,
   63, 81) e carinho (62, 67) ficam: dá para condicionar ou ajustar, mas nenhuma vira "Substituir"
   por ser "exagerada demais". Vitória pede festa, e a festa não entra na cota.
2. **Direito de ser irracional.** As passivas sem motivo (rindo, corando, cantarolando, beicinho
   sozinha) e a **Favorita do Dia** têm reação própria. "Não tem sinal" não vale contra reação
   aleatória: a regra de honestidade não pede sinal para ela.
3. **Ela nunca ignora o Pedro.** Ele voltou (20, 62), clicou (64) ou a música dela começou (24):
   ela reage **sempre** que estiver parada, sem cooldown que engula a volta dele. E quando ele
   está mal ou é madrugada, nada de provocação: só carinho.

**O que cedo**
- Texto raro e curto, sem voz. A maior parte das reações fica só no rosto.
- Todo gatilho sem sinal real vira Ajustar ou fica condicionado a um sinal novo com nome. Eu
  choro, mas aceito.
- Cotas e cooldowns para as passivas (regra 1), desde que não peguem a festa nem a volta dele.
- Reações que já existem (`game_on`, `hot`, `fps_drop`, `cleanup`, `led`...) são **fundidas** com as
  da planilha, sem duplicata.

## 2. Decisões

**Aprovadas:** 1–4, 6–14, 16, 19, 21–24, 28, 33–39, 41, 42, 44, 45, 52, 58–61.

5 · Aprovada condicionada · sinal novo: área de hover no retrato (posição do cursor sobre o widget) · Até lá não roda; o HUD não vê o cursor.
15 · Aprovada condicionada · hover no retrato parado ≥10 s (mesmo sinal novo do 5) · Combina com o 77, que é o mesmo sinal em 3 s.
17 · Ajustar · Magui ociosa, Claude Code parado ≥10 min, sem música e sem jogo · "Sem interação" não existe; 2 min daria bocejo demais.
18 · Ajustar · mesmas condições do 17 por ≥25 min, só fora de jogo · Cochilo é o estado; vira fundo `sleepy`.
20 · Ajustar · sai do cochilo quando volta qualquer sinal: Claude ativo, música toca, clique, Magui ouvindo · Sempre responde, sem cooldown (linha vermelha 3).
25 · Ajustar · Spotify: tocando sim→não · O "vai falar com você" sai: falando já descarta reação.
26 · Ajustar (e condicionada) · agora: faixa nota 2 cruza 1/3 da duração; depois: pico de nível via monitor do PipeWire · Só no rosto, nenhum texto diz "refrão". A festa fica!
27 · Ajustar · faixa nota 2 ou tocada ≥5 vezes; dispara após 40 s tocando · "Conhece" = gosto + plays, sinal real.
29 · Ajustar · gênero do artista (piano, ballad, sad, clássica, lofi) ou título com triste/sad/tears/goodbye/lágrima · Lágrima fica; metadado, não áudio.
30 · Ajustar · gênero dance, pop, k-pop, edm, disco, funk, phonk · Pelo gênero do cache do núcleo.
31 · Aprovada condicionada · sinal novo: volume do sink no PipeWire (`wpctl get-volume`), salto ≥25 pontos · Hoje o HUD não lê volume.
32 · Ajustar · tocando sim→não com posição ≥ duração−3 s e nada novo em 15 s · "Acabou e ninguém pôs outra": real.
40 · Ajustar · rede ↓ ≥5 MB/s por ≥60 s cai para <100 KB/s · Rosto satisfeito, sem texto afirmando "download concluído".
43 · Aprovada condicionada · sinal novo: rpm da ventoinha via lm-sensors (`fan*_input`), subida ≥30% · Sem sensor hoje.
46 · Aprovada condicionada · sinal novo: escuta D-Bus `org.freedesktop.Notifications.Notify` · Cota forte: no máx. 1 a cada 10 min.
47 · Ajustar (condicionada ao sinal do 46) · notificação com urgência crítica · Não há "popup de erro"; urgência crítica é o real.
48 · Ajustar · HUD abriu (primeiro snapshot da execução) · O HUD não vê o boot; vê ele mesmo abrindo.
49 · Substituir · "Boa noite" (ideia nova abaixo) · O HUD morre no desligamento, não tem como reagir.
50 · Aprovada condicionada · sinal novo: `needs-restarting -r` a cada 30 min · Cara de "tá esperando o quê?".
51 · Aprovada condicionada · sinal novo: arquivo novo na pasta de capturas (~/Imagens/Capturas de tela) · Pose de diva, prioridade minha.
53 · Ajustar · sessões rodando >0 → 0 depois de ≥2 min rodando · "Terminou" = parou após trabalhar; festa garantida.
54 · Aprovada condicionada · sinal novo: hook do Claude Code (PostToolUse com falha / Stop com erro) grava estado · Hoje só existe rodando/parado.
55 · Aprovada condicionada · sinal novo: hook `Notification` do Claude Code grava "esperando" · Mesmo arquivo de estado do 54.
56 · Ajustar · rodando contínuo ≥15 min · Real pelo tempo de atividade.
57 · Ajustar · primeira atividade do dia depois das 5h (estado em arquivo) · "Primeiro uso" precisa da data salva.
62 · Ajustar · primeira atividade (Claude, música, jogo, clique) após ≥3 h sem nenhuma · Sem cooldown, sempre responde.
63 · Aprovada condicionada · sinal novo: `[datas]` no condessa-gosto.toml (aniversário do Pedro) + aniversário dela · Data cadastrada pelo Pedro; festa máxima.
64 · Ajustar · cliques seguidos no LED (já é a "cutucada") · Até o retrato ter área de clique.
65 · Aprovada condicionada · hover no retrato (sinal do 5) · Blush suave, 1 a cada 5 min no máx.
66 · Ajustar · clique no LED com música tocando · Real hoje.
67 · Aprovada condicionada · arrasto sobre o retrato (sinal novo: área de clique/arrasto) · Carinho não sai da lista (linha vermelha 1).
68 · Aprovada condicionada · movimento rápido de vai-e-vem sobre o retrato (mesmo sinal) · Tontura é ótima.
69 · Aprovada condicionada · clique duplo no retrato (mesmo sinal) · Não roubar o LED para isso.
70 · Aprovada condicionada · clique longo ≥1 s no retrato (mesmo sinal) · Relaxa, vira `calm`.
71 · Ajustar · manchete nova com palavra da lista "boa" (vitória, recorde, lança, cura, aprova…) · Lista no condessa-gosto.toml; só rosto.
72 · Ajustar · manchete nova com palavra da lista "ruim" (morte, ataque, queda, crise…) · Sem riso nem zoeira aqui.
73 · Ajustar · manchete nova com palavra da lista "absurda" (bizarro, inusitado, gato, pato, recorde estranho) · Lista curta e editável.
74 · Aprovada condicionada · sinal novo: núcleo grava a tag da última fala do Pedro (elogio/zoeira/correção) em arquivo de estado · Tsundere precisa de elogio real.
75 · Ajustar · commit novo no git (HEAD mudou) · Descoberta = commit; ela toma o crédito, claro.
76 · Aprovada condicionada · tag "zoeira" (sinal do 74) · Riso fica (linha vermelha 1).
77 · Aprovada condicionada · hover no retrato ≥3 s (sinal do 5) · Flagrada antes do "Encarando" de 10 s.
78 · Ajustar · Pedro volta a tocar uma faixa que pulou há <2 min · Cara de "decide, hein?"; real pelo Spotify.
79 · Ajustar · humor do Pedro estimado cai para ≤1 · Triste junto com ele, sem deboche, sem texto.
80 · Ajustar · CPU ≥95% ou swap crescendo por ≥30 s, sem jogo aberto · "PC lento" medível.
81 · Ajustar · começa faixa do artista Favorita do Dia · Favoritismo sem motivo, com sinal real (linha vermelha 2).
82 · Ajustar · Claude Code rodando E música tocando · Funde com o 52: com música usa este.
83 · Ajustar · Pedro toca faixa nota 2 dela pela 3ª vez na semana · "Deixa comigo": ela ensinou ele a gostar.
84 · Ajustar · `fps_drop` até 5 min depois de um `hot` · Previu e aconteceu; nunca com Pedro mal.
85 · Ajustar · faixa nota 0 começa pela 2ª vez no dia · Indiferença ao óbvio musical.
86 · Aprovada condicionada · tag "correção" (sinal do 74) · "Ela errou" só existe se o Pedro corrigiu.
87 · Aprovada condicionada · 2º elogio em 10 min (sinal do 74) · Escalada do 74: elogio a desmonta.
88 · Ajustar · aleatório raro entre 0h e 4h com música tocando · Segredo de madrugada; passiva sem sinal.
89 · Ajustar · player: anterior e próxima alternados ≥2 vezes em 15 s · Indecisão dele, cara dela.
90 · Ajustar · Claude Code rodando ≥10 min com CPU ≥80% · Build pesado medível.

## 3. Ideias novas

- Boa noite (substitui o 49) | Ativa | Tempo | 0h–4h, música parou e Claude parado ≥10 min | B1+C5 (800) → B14+C1 (700) → B15+C1 (1200)
- Guerra Fria com a Ado | Ativa | Música | começa faixa da Ado | B9+C7+D5 (500) → B6+C8+D2 (1200) → B4+C10 (1500)
- A Conta Anônima | Ativa | Música | 40 s de faixa do Kenshi Yonezu/hachi ou gênero vocaloid | B5+V1 (300) → B5+V2 (300) → F1+C1+D2 disfarça (1200) → B1+C10 (800)
- Diva contra Diva | Ativa | Música | começa faixa da Lady Gaga | B7+C9 (1000) → B4+C5 (1200)
- Processo contra Debussy | Ativa | Música | título com palavra de água (lista do gosto) | B13+C7 (800) → B4+C6+D6 (1800)
- Calada pelo Chopin | Ativa | Música | 0h–4h, faixa do Chopin/Marika Takeuchi | B3+C5 olhos fechados (3000) → B2+C1 (600)
- Partida sem tropeço | Ativa | Sistema | jogo aberto ≥30 min sem `fps_drop` (1 vez por sessão) | B9+C7 (400) → B5+C6+D9 (2500)
- Ei, tô aqui | Passiva | Tédio e sono | HUD aberto, sem música, Claude parado ≥40 min, 8h–23h (1 a cada 2 h) | B1+C9 (1200) → B9+C7+D4 (800) → B1+C10 (800)
- Aniversário dela | Ativa | Tempo | data do primeiro commit do repo MAGI (`git log --reverse`) | B9+C7+D5 (500) → B5+C6+D1+D6+D9 (3000)

## 4. Humor e Assets

**Humor**
- Música que ela gosta: peso 6 → **7**.
- Manhã: peso 4 → **5**; favorece também Cantarolando sozinha.
- Fator novo **Pedro mal** (humor 0–1) | peso **9** | suprime Beicinho, Provocação, Eu avisei, Indiferente, Desconfiada; favorece Piscada lenta, Micro sorriso.
- Fator novo **Favorita do Dia tocando** | peso **8** | favorece Corando sozinha, Rindo sozinha, Cabeça no ritmo.
- Fator novo **Vitória recente** (FPS recuperou, alívio térmico, Claude terminou, faxina, commit; vale 10 min) | peso **6** | favorece Micro sorriso, Rindo sozinha.
- Fator novo **Silêncio longo** (sem música e Claude parado ≥30 min) | peso **4** | favorece Suspiro, Beicinho, Soprando a franja.

**Assets**
- B16 piscadinha: prio 1 (mantém).
- **D7 lágrima: prio 1** (29, 79 e lágrima de rir no 76; drama precisa de arte).
- P9 aceno: prio 2 → **1** (Bom dia, Sentiu sua falta, Ei tô aqui, Boa noite).
- B17 feliz meio: prio 3 → **2** (piscada do feliz em risos e corados).
- E3 e P10 mantêm prio 2; P11 mantém prio 3.

## 5. Regras gerais

1. **Passivas:** uma a cada 45–90 s, sorteada pelos pesos de humor; raras (10, 11, 13, 88) no
   máx. 1 por hora cada; Corando sozinha (12) no máx. 1 por dia.
2. **Ativas:** cooldown de 10 min por reação (3 min nas de sistema); no máx. 1 ativa a cada 20 s.
   A ativa ganha da passiva. As da planilha fundem com as 19 que existem (44=`game_on`,
   34=`hot`, 36=`fps_drop`, 42=`cleanup`, 64=`led`, 61=`long_session`...), nunca em dobro.
3. **Festa e volta furam a cota:** vitória (35, 37, 39, 53, 75, Partida sem tropeço) e Pedro
   voltando (20, 57, 62) sempre tocam se ela estiver parada; se estava falando, entram na fila
   por 30 s e tocam depois.
4. **Pedro mal ou 0h–5h:** nada de provocação, beicinho, "eu avisei", indiferença ou
   desconfiança. Só carinho, rosto calmo e frase curta.
5. **Honestidade:** a condicionada fica desligada até o sinal existir. Nenhum texto de reação
   afirma o que o HUD não sabe ("refrão", "você me elogiou", "download acabou"). Ordem de código
   que eu peço: (a) área de hover/clique no retrato (destrava 5, 15, 65, 67–70, 77); (b) tag da
   última fala no estado do núcleo (74, 76, 86, 87); (c) hooks do Claude Code (54, 55).

Contagem: 90 da planilha (89 + o 49 substituído) + 9 ideias novas = 98, bem acima do piso de 80.
