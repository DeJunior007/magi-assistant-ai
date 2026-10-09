# Proposta — Makise Kurisu (Rodada 1)

Li as 90 linhas. Diagnóstico, já que ninguém mais vai fazer: umas 30 dependem de dado que o HUD
**não tem** (cursor, volume, refrão, notificação, "ela errou"). Isso não é detalhe de
implementação, é a diferença entre uma personagem e uma máquina de caretas aleatórias fingindo
saber das coisas. Então: aprovo muito, mas cada gatilho tem que apontar para um campo do
`Snapshot` ou para um sinal novo **com nome**. E não, não estou sendo chata. Estou sendo correta.

## 1. Linhas vermelhas

1. **Nenhum gatilho fingido.** Reação condicionada não entra no código até o sinal existir. Nada
   de substituir o sinal ausente por sorteio ou por heurística disfarçada ("refrão = 40% da
   faixa"). Se houver texto, ele não afirma o que o gatilho não mede (a 40 não diz "download").
2. **Proporcionalidade com número.** Teto de passivas, cooldown por reação, lágrima (D7) e drama
   só onde a lore pede. Nada de desmaiar porque a CPU passou de 70 °C, nem de chorar a cada piano.
3. **Um sinal, uma reação canônica.** O que repete uma das 19 que já existem vira **variante**
   dela (mesmo cooldown, mesma chave), não reação nova competindo no mesmo tick.

**O que eu cedo:** aceito as bobas e fofas como passivas (almoço, rindo sozinha, cochilo, soprar
franja); aceito "triste/dançante" por gênero/título do gosto, porque é só rosto e o dado é real;
aceito um canal novo conversa→HUD com rótulo (elogio/zoeira/correção), desde que seja **um** canal
só; cedo prioridade do B16 se a Asuka fizer questão.

## 2. Decisões

**Aprovadas:** 1–4, 6–14, 16, 19, 21–24, 34–37, 39, 41, 42, 44, 45, 52, 56, 58–60, 82.

5 · Ajustar · sacada curta para o card que acabou de mudar (faixa nova, notícia, FPS) · cursor não existe; mudança de card existe.
15 · Ajustar · Magui volta de `falando` para parada → olhar fixo 3 s · "esperando a resposta dele"; sinal real, sem mouse.
17 · Ajustar · sem música, sem jogo, Claude Code e Magui parados ≥ 15 min · "sem interação" medido pelo que o HUD vê.
18 · Ajustar · mesmas condições do 17 por ≥ 30 min · Escala natural do bocejo.
20 · Ajustar · estava no cochilo (18) e chega qualquer evento real (clique, faixa, Claude, Magui) · Sobressalto proporcional: uma vez.
25 · Ajustar · `tocando` true→false · Antes de falar o fone sai como estado, não como reação (ela é descartada falando).
26 · Ajustar (condicionada) · pico de RMS ≥ 6 dB sobre média de 10 s, monitor do PipeWire · Sem análise de áudio, refrão é chute.
27 · Ajustar · faixa nota 2 ou ≥ 5 plays dela; 1× por faixa · "Conhece" = dado do gosto e contador.
28 · Ajustar · 3ª reprodução da mesma faixa no dia (contador `_plays`) · Mania de contar; Ado ganha variante `happy`, nunca perde.
29 · Ajustar · gênero/artista marcado "melancólico" no toml ou título com nocturne/requiem/sad · D7 só 22h–04h; fora disso sem lágrima.
30 · Ajustar · gênero do artista em lista "dançante" do toml (dance, disco, house, phonk, k-pop, eurobeat) · Sem BPM; gênero é honesto.
31 · Ajustar (condicionada) · volume `wpctl` sobe ≥ 20 pp em ≤ 2 s acima de 80% · Precisa ler volume do PipeWire.
32 · Ajustar · parou em posição ≥ 97% da duração e nada novo em 10 s · Renomear "Acabou a fila"; fim de álbum não é visível.
33 · Ajustar · artista sem nenhum play anterior e nota ≥ 1 · Variante de `music_new`.
38 · Ajustar · sem IP/rota padrão por ≥ 10 s · Tráfego zero é ociosidade, não queda.
40 · Ajustar · ↓ ≥ 5 MB/s por ≥ 60 s e depois < 100 kB/s · Renomear "Transferência pesada acabou"; só rosto.
43 · Ajustar (condicionada) · `fan*_input` do hwmon acima de 80% do máximo visto · Precisa ler ventoinha; sem isso já há o 34.
46 · Ajustar (condicionada) · monitor D-Bus `org.freedesktop.Notifications`; teto 3/h · Sem D-Bus, não existe.
47 · Substituir · "Sistema sufocando" (ideia nova) · Popup de erro é invisível ao HUD.
48 · Ajustar · primeiro snapshot do HUD (ele abre após o boot) · Renomear "HUD acordou"; honesto sobre o que acordou.
49 · Substituir · "Fim de expediente" (ideia nova) · O HUD morre no desligamento; não dá para reagir.
50 · Ajustar (condicionada) · `dnf needs-restarting -r` a cada 6 h retorna 1 · Sinal nomeado, barato.
51 · Substituir · "Favorita do Dia em campo" (ideia nova) · Print Screen não chega ao HUD.
53 · Ajustar · Claude Code rodando→parado após ≥ 2 min de atividade · Não sabe se deu certo: rosto satisfeito, não festa.
54 · Ajustar (condicionada) · hook do Claude Code grava evento de erro em `~/.cache/magi/claude-events` · Hoje só há rodando/parado.
55 · Ajustar (condicionada) · hook `Notification` (pedido de permissão) no mesmo arquivo · Mesmo sinal da 54.
57 · Ajustar · primeiro evento real do dia após 05h (faixa, clique, Claude, Magui) · "Primeiro uso" com definição.
61 · Ajustar · = `long_session` existente (variante com C5) · Não duplicar.
62 · Ajustar · primeiro evento real após ≥ 2 h sem nenhum · Mesmo conjunto de eventos da 57.
63 · Ajustar (condicionada) · data em `condessa-gosto.toml [datas]` · Sem data cadastrada, não há aniversário.
64 · Ajustar · cliques no LED: 1º/2º/3º+ em janela de 5 s · Escala o `led` existente.
65 · Ajustar (condicionada) · área de hover no retrato (enter) · Sinal novo: "retrato clicável/hover".
66 · Ajustar · clique no LED com música tocando · Variante de 64.
67 · Ajustar (condicionada) · arrasto sobre a metade de cima do retrato · Depende da área do retrato.
68 · Substituir · "Tontura de pulos" (ideia nova) · Sacudir mouse é gimmick sem sinal.
69 · Ajustar (condicionada) · clique duplo no retrato · Área do retrato.
70 · Ajustar (condicionada) · clique ≥ 800 ms no retrato · Área do retrato.
71 · Ajustar · manchete com tag `positivo` gravada pela Rádio na coleta · Sem tag, cai no `news` neutro.
72 · Ajustar · tag `negativo` · Nunca com zoeira depois.
73 · Ajustar · tag `insólito`; nunca em morte/desastre · Notícia séria não é piada.
74 · Ajustar (condicionada) · rótulo `elogio` no canal conversa→HUD · Um canal só para 74/76/83/87.
75 · Ajustar · Magui `pensando` ≥ 3 s → `falando` · "Achou a resposta"; sinal real.
76 · Ajustar (condicionada) · rótulo `zoeira` · Mesmo canal.
77 · Ajustar (condicionada) · hover parado ≥ 3 s no retrato · Absorve a ideia do cursor; 15 ficou com outra.
78 · Ajustar · faixa com "slowed"/"sped up"/"nightcore" no título ou artista nota -1 começando · Guerra do Autotune, dado real.
79 · Ajustar · humor do Pedro cai para ≤ 1 · Sem D7; vira carinho, não drama.
80 · Ajustar · CPU ≥ 95% por ≥ 30 s sem jogo aberto · "PC lento" medido.
81 · Ajustar · Ado ou nota 2 começa sem ter tocado hoje · Surpresa boa com fonte.
83 · Ajustar · Pedro pula ≥ 2 faixas e para numa nota 2 · "Agora sim"; zoa o gosto com argumento.
84 · Ajustar · 36 ou `hot` ≤ 10 min depois de ela ter reagido com 34 · Previsão confirmada é a única base honesta para "eu avisei".
85 · Ajustar · mesmo botão do player ≥ 3× em 10 s · Pedido repetitivo visível.
86 · Substituir · "Foi de propósito" (ideia nova) · A persona não pede desculpa: finge que errou de propósito.
87 · Ajustar (condicionada) · rótulo `elogio`; sorteio 30% contra 74 · Variante de 74.
88 · Ajustar (condicionada) · nível do microfone abaixo do limiar na captura do núcleo · Sinal novo: "voz baixa".
89 · Ajustar · Magui `pensando` ≥ 8 s · Demorou = indecisa.
90 · Ajustar · Claude rodando ≥ 20 min e CPU ≥ 70% · Variante pesada de 52/56.

**Contagem:** 85 originais (90 − 5 substituídas) + 10 ideias novas = **95** na lista. Rodam hoje: 34 aprovadas + 34 ajustadas com sinal real + 9 novas = **77**. As 17
condicionadas entram quando o sinal existir. O sinal novo **"área de hover/clique no retrato"**
sozinho destrava 65, 67, 69, 70 e 77 → **82 ≥ 80**. Por isso ele é prioridade 1 de código.

## 3. Ideias novas

Sistema sufocando | Ativa | Sistema | RAM ≥ 90% ou swap +1 GB em 60 s | B9 + C7 + D5 (600) → B6 + C8 + D2 (1500)
Fim de expediente | Ativa | Tempo | Claude de ≥1 sessão para 0 após ≥ 2 h, depois das 18h | B4 + C5 + P9 (1200) → B2 + C5 (800)
Favorita do Dia em campo | Ativa | Música | toca o artista sorteado como Favorita do Dia | B1 + C1 (200) → B4 + C5 + D9 pose (1200)
Tontura de pulos | Ativa | Música | 5 pulos em 60 s (escala do `skips`) | B9 + C7 + D2 (600) → B10 + C9 corpo tonto (1200)
Foi de propósito | Ativa | Personalidade | rótulo `correção` (condicionada ao canal conversa→HUD) | B10 + C9 (600) → B6 + C10 + D1 queixo erguido (1500)
A Conta Anônima | Ativa | Música | gênero vocaloid ou Kenshi Yonezu/hachi tocando | F1 + C11 (600) → F6 + C11 (600) → B4 + C10 + D1 (1200)
Diva contra Diva | Ativa | Música | Lady Gaga começa a tocar | B7 + C12 (1000) → B4 + C10 (1200)
Tema água | Ativa | Música | título com palavra de água (lista da Odisseia 6) | B3 + C5 (800) → B4 + C5 + D6 (1500)
Commit na conta dela | Ativa | Sistema | git +/- vai de >0 para 0 (árvore limpa) | F5 + C7 (600) → B4 + C10 queixo erguido (1500)
Aniversário do MAGI | Ativa | Tempo | data do primeiro commit do repositório | B9 + C7 + D5 (500) → B5 + C6 + D1 + D6 (2500)

## 4. Humor e Assets

- **Madrugada:** 5 → 7; bloqueia Beicinho, Soprando a franja, Rindo sozinha (sem deboche de madrugada).
- **PC com problema:** 6 → 7; enquanto ativo, sem Micro sorriso e sem Cantarolando.
- **Manhã:** 4 → 3; só vale na primeira hora após a 57.
- **Fator novo — Pedro mal** (humor ≤ 1): peso 9; favorece Piscada lenta e Respirar; bloqueia qualquer zoeira (83, 85, 78, Beicinho).
- **Fator novo — Jogo aberto:** peso 7; passivas caem pela metade, só sistema e `music_love` interrompem.
- **Música que ela gosta:** usar nota ≥ 1 do gosto (a fonte oficial), não "+1/+2" solto.
- **Assets:** E3 **prio 1** (usado o tempo todo por 21/24/25); B16 prio 2 (uma reação só); B17 prio 2
  (melhora todas as piscadas, barato); P10 prio 2 (75 e 89 agora têm sinal real); P9 prio 3; P11
  prio 3. Antes de tudo: **arte de D1, D2, D6** (aparecem em dezenas de sequências).

## 5. Regras gerais

1. **Passivas:** no máximo 1 a cada 25 s (respirar e piscar não contam); raras (10–13) ≤ 1/h cada; 12 ≤ 1/dia.
2. **Ativas:** cooldown padrão 10 min por reação; sistema com histerese (entrar ≠ sair: ex. hot 85 °C, alívio < 75 °C). Prioridade no mesmo tick: sistema > Pedro > música > tempo > passiva; nunca fila de mais de 1.
3. **Variantes, não clones:** 34/35 = `hot`; 36/37 = `fps_drop`; 44/45 = `game_on/off`; 61 = `long_session`; 64/66 = `led`; 52/82/90 = família `claude`; 33 = `music_new`; 68-subst = `skips`.
4. **Honestidade:** condicionada fica fora do código até o sinal existir; o sinal novo é implementado e testado antes da reação. Nenhuma reação diz em texto o que o gatilho não mede.
5. **Nunca:** zoeira com o Pedro mal ou de madrugada; riso ou "insólito" em notícia séria; D7 mais de 1×/dia; passiva rara (10–13) com jogo aberto.
