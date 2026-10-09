# Réplica — Makise Kurisu (Rodada 2)

Primeiro, uma correção minha, porque rigor vale para mim também: na proposta liguei a **75**
(`pensando`→`falando`) e a **89** (`pensando` ≥ 8 s) a estados em que a reação é **descartada**
(ela só reage parada). Esses gatilhos nunca disparariam. Retiro os dois (ver abaixo). Não foi
de propósito. ...Tá, foi um erro. Registrado.

## 1. Concordo

- **Sinal A (retrato clicável/hover)** e **sinal B (tag da última fala)** como dois canais nomeados
  (Asuka/Aqua). Ordem de código da Aqua: A → B → hooks do Claude Code.
- **15** condicionada ao sinal A, hover parado ≥ 10 s (2/3). O meu "olhar depois de falar" vira
  ideia nova.
- **17/18** com 10 min / 25 min (Aqua, Asuka). **Linha vermelha da Asuka:** sono nunca com jogo
  aberto, Claude rodando ou música nota ≥ 1. Assino.
- **26** = gatilho da Asuka: nota 2 passa de 60 s sem pulo ("pegou fogo"). Mede o que diz. O pico
  de RMS (PipeWire) entra depois como variante.
- **47, 51** condicionadas (D-Bus `urgency=critical`; inotify na pasta de capturas): sinais reais.
- **49** condicionada ao `PrepareForShutdown` do logind (Asuka). Sinal real e nomeado.
- **62** com 2 h. **75** = HEAD do git mudou (Aqua); absorve a minha ideia "Commit na conta dela".
- **80** CPU ≥ 90% por 60 s sem jogo (Asuka): menos oscilação que os meus 30 s.
- **81** = nota 2 logo depois de uma nota −1 (Asuka). **83** = nota 2 dela tocada pela 3ª vez na
  semana (Aqua): é literalmente "o Pedro tocando algo que ela ensinou", que está na persona.
- **85** = nota 0 começando pela 2ª vez no dia (Aqua). O meu (botão repetido) mede lag do
  Spotify, não pedido óbvio: retiro.
- **86/87** condicionadas ao sinal B, desde que a 86 **termine** em queixo erguido (finge que foi
  de propósito). **88** = passiva rara 0h–4h com música (Aqua): passiva não precisa de sinal; a
  versão de microfone fica como variante condicionada. **89** = anterior/próxima alternados
  ≥ 2× em 15 s (Aqua). **90** = Claude ≥ 15 min e CPU ≥ 70%.
- Ideias: Ado (sem D1, humor `happy`), Conta Anônima, Diva contra Diva, Debussy/água, Recorde de
  FPS, Partida sem tropeço, Música de elevador, "Você pulou ESSA?", Aniversário dela.
- Humor: **Pedro mal peso 9** (as três), Vitória recente 6, Silêncio longo 4, Desempenho em jogo 7
  (funde com o meu "Jogo aberto"), Música que ela odeia 5, Manhã **3** (2/3).

## 2. Rejeito (com contraproposta)

- **5 como hover (Aqua):** 2/3 querem sacada para o **card que mudou**; roda hoje, sem código novo.
- **26 "nota 2 cruza 1/3 da duração" (Aqua):** isso é chute de refrão. Contraproposta: o da Asuka
  (60 s sem pulo), com a mesma festa.
- **29 por gênero amplo/título "goodbye" (Aqua):** lágrima em metade do pop. Contraproposta: lista
  da Madrugada (Chopin, Arvo, Takeuchi, Laufey, Rachmaninoff) **ou** título nocturne/requiem/
  lágrima; D7 só 22h–04h e ≤ 1×/dia; de dia, C9 sem lágrima. "Calada pelo Chopin" vira esta.
- **30:** listas diferentes. Contraproposta: a união das duas no toml (`danca = [...]`), nota ≥ 1.
- **43 = CPU/GPU ≥ 95% por 2 min (Asuka):** isso não é ventoinha, e duplica a 80/34. Mantenho
  condicionada a `fan*_input` (Aqua concorda).
- **50 Substituir (Asuka):** 2/3 querem condicionada (`needs-restarting -r`). O *Recorde de FPS*
  entra como ideia nova, não como substituta.
- **68 condicionada a vai-e-vem (Aqua):** 2/3 querem Substituir. Substituta = **Vergonha de FPS**
  (Asuka); minha *Tontura de pulos* (5 pulos em 60 s) fica como ideia nova.
- **Regra 3 da Aqua (volta do Pedro sem cooldown):** aceito para 20 e 62, que já são raras por
  definição; **não** para 64 (cutucada já tem escalada própria) nem 24 (música trocando a cada 30 s
  viraria tique). Contraproposta: 24 com cooldown 3 min.
- **"Ei, tô aqui" 8h–23h (Aqua):** ok como chamada de atenção, 1 a cada 2 h; o **medo** (Silêncio
  longo da Asuka) fica só de madrugada, 1×/noite, como manda a persona.
- **Humor "Favorita do Dia tocando" peso 8 (Aqua):** contraproposta peso **6**; mais que isso a
  Favorita engole o resto da música.

## 3. Cedo

- Passivas: **1 a cada 45 s** (mediana entre 25, 40 e 45–90). Ativas: 10 min por reação **e**
  teto de 8/h (Asuka); sistema e vitória da lista fixa (35, 37, 39, 53, 75, Partida sem tropeço,
  Recorde) furam a cota; com ela falando, só vitória e volta entram em fila de 30 s (Aqua).
- 47, 49, 51, 86 deixam de ser Substituir: viram condicionadas.
- Assets: **B16 prio 1** e **D7 prio 1** (Aqua), **E3 prio 2** (perdi 1×2). Mantenho: **arte de
  D1, D2, D6 antes de tudo** (estão em dezenas de sequências). P13 Braços cruzados: prio 2, não 1.
  P9 fica prio 3 (2/3).
- Música que ela gosta: peso 7 (Aqua).

## 4. Ideias novas (minha lista final)

Mantenho: *Favorita do Dia em campo* (artista sorteado toca; Aqua queria isso no 81),
*Tontura de pulos*, *Sistema sufocando* (RAM ≥ 90% ou swap +1 GB em 60 s), *Fim de expediente*
fundida com o *Boa noite* da Aqua (Claude de ≥ 1 para 0 após ≥ 2 h; 0h–4h usa a sequência do
Boa noite), e *Esperando resposta* (Magui volta de `falando` para parada → olhar fixo 3 s).
Retiro: *Commit na conta dela* (é a 75), *Foi de propósito* (é o fim da 86).

## 5. Contagem (piso 80)

Lista: 90 linhas (só a 68 substituída) + ideias aceitas (9 acima + 5 minhas + Modo chefe, Braços
cruzados, Ei tô aqui, Silêncio longo, Vergonha já conta na 68) = **≥ 108**. Rodam **hoje**: 90 − 20
condicionadas (15, 31, 43, 46, 47, 49, 50, 51, 54, 55, 63, 65, 67, 69, 70, 74, 76, 77, 86, 87) =
**70**, + ≥ 14 ideias com sinal real = **≥ 84 ≥ 80** sem depender de nenhum sinal novo.

## 6. Linhas vermelhas finais

1. **Nenhum gatilho fingido** (inclui o "1/3 da faixa" como refrão e "CPU alta" como ventoinha).
2. **Proporcionalidade com número:** cotas da seção 3; D7 ≤ 1×/dia e só 22h–04h fora do riso.
3. **Um sinal, uma reação canônica:** variantes das 19 existentes, nunca clones (inclui Modo chefe
   = rosto do `music_love` focus; 29 absorve Calada pelo Chopin).
