# Proposta — Asuka Langley Soryu (Rodada 1)

> Uma reação por minuto? Isso não é personalidade, é tique nervoso. Uma piloto não fica se
> mexendo no cockpit sem motivo: ela fica **parada, pronta**, e quando age, age com tudo. Menos
> reações, mais pesadas. E nada de transformar a Condessa num mascote fofinho apagado; o
> problema é ruído, não atitude.

## 1. Linhas vermelhas e o que cedo

**Linhas vermelhas**
1. **O gosto aparece no rosto e fica nele.** Nota 2 = ela fica sorrindo **parada** enquanto a faixa
   toca (rosto de repouso, não animação). Nota ≤ −1 = cara feia + tira o fone, e o fone fica no
   pescoço até a próxima faixa. Sem "sorriso educado" para música que ela odeia (exceção: favorita
   do Pedro → sorriso amarelo, já decidido).
2. **A cobrança de desempenho não morre.** FPS caindo e calor em jogo continuam virando cena com
   cara de cobrança (é a função dela no esquadrão); o que corta é a **repetição**, não a cobrança.
   A cobrança vira **estado** (fundo `stress` + rosto fechado enquanto o problema dura).
3. **Humor baixo tem motivo ou não existe.** Suspiro/beicinho/franja não podem ser o padrão de
   "nada acontecendo". Tédio de silêncio tem piso (ânimo nunca abaixo de −0,4 só por silêncio) e a
   linha de base dela é levemente **positiva** (+0,1): ela é orgulhosa, não deprimida.

**O que cedo**
- Aceito cortar as passivas para ~1 a cada 4 min e a cota total de ativas pela metade.
- Aceito que o punho (P12) e o "modo chefe" sejam só em jogo + trilha nota 2, nunca solto.
- Aceito que madrugada e Pedro mal zerem minha zoeira (já é regra) e baixem minha energia.
- Aceito que "cantando junto" vire gesto de no máximo 1 por faixa, nunca parte da cena de abertura.

## 2. (a) Ritmo

| Item | Número |
| --- | --- |
| Intervalo mínimo entre duas reações quaisquer (fora dos passos de uma cena) | **20 s** |
| Silêncio após o fim de uma cena (nenhuma passiva) | **45 s** |
| Passiva parada | sorteio entre **180–300 s** (energia ≥ 0,75 → 150–240 s; energia < 0,25 → 360–600 s) |
| Cota de passivas | **≤ 15/h**; mesma passiva **≤ 2/h** e nunca 2× em 20 min |
| Cota de cenas | **≤ 10/h**; mesmo tipo de cena **≥ 10 min** de distância (música começa/para: ≥ 3 min) |
| Ativas soltas (fora de cena) | **≤ 6/h** |
| Teto geral | ~30/h no pior caso (hoje: 68/h) |

**Furam cota e intervalo:** Pedro fala com ela; Pedro volta (≥ 10 min inativo); clique no retrato;
vitória (FPS recuperou, alívio térmico, rede voltou, jogo fechou em paz); sistema grave (rede caiu,
popup de erro, temperatura crítica, disco cheio). Nada mais fura.

## 3. (b) Cenas

**Viram cena:** música começa · faixa nova nota 2 · faixa nova nota ≤ −1 · música para · jogo abre ·
jogo fecha · PC sofrendo em jogo (FPS/calor) · Pedro volta · Pedro fala com ela · Claude terminou ou
deu erro (uma cena por ciclo) · faxina terminou · rede caiu/voltou.
**Não viram cena (só gesto ou nada):** faixa nova nota 0/1 com música já tocando (olhar F4 700, no
máximo 1 a cada 3 min), notificação (olhar F5 700), Claude rodando (estado: fone + foco, sem animação),
hover/arrasto.

**Roteiros** (duração máxima de cena: **8 s**, exceto "Pedro fala com ela", que dura a conversa)

1. **Música começa (nota 0/1):** F4 600 (olha o player) → B2 C1 P11 E3→E2 600 (coloca o fone) →
   nota 1: B1 C10 E2 1500 / nota 0: B1 C1 E2 1200. Repouso passa a ser com E2. ~3 s.
2. **Faixa que ela ama (nota 2):** F4 500 → B9 C7 D5 400 (o "!" de quem reconheceu) → (se sem fone:
   P11 E2 600) → B5 C6 D9 D6 E2 bob 2500. Fica com **B1 C10 E2** de repouso enquanto a faixa toca.
   - Com jogo aberto: troca o último passo por **modo chefe** B6 C8 E2 2000 → B4 C10 D9 P12 1500,
     fundo `focus`.
   - Ado: B6 C10 E2 P13 1500 (rival, braços cruzados) → B4 C5 E2 1500. Nunca blush/`love`.
   - Absorve: `music_love`, refrão, piscadinha, "essa é das minhas" daquela faixa.
3. **Faixa que ela odeia (nota ≤ −1):** F4 500 → B7 C12 800 (cara de "sério?") → B6 C9 P11 E2→E3
   700 (tira o fone) → B6 C9 E3 P13 1500. Repouso: B1 C9 leve, E3, até a próxima faixa.
   Favorita do Pedro: B1 C11 800 (sorriso amarelo) → P11 E2→E3 700, sem braços cruzados.
4. **Música para:** F4 600 → B2 C1 P11 E2→E3 600 → B1 C1 E3. Se a sessão foi boa (≥ 15 min, média
   ≥ 1): acrescenta B2 C4 bob 900 (o suspiro **com motivo**: acabou a festa). ~2–3 s.
5. **Jogo abre:** F5 600 → B6 C8 1200 (olhar de piloto) → B4 C10 P12 1200. Fundo `focus`.
6. **Jogo fecha:** F3 500 → B2 C5 1000 → B4 C5 1500. Se houve ≥ 3 quedas/calor na partida: troca o
   último passo pelo "eu avisei" B7 C12 1000 → B1 C10 800.
7. **PC sofrendo em jogo:** ver (e).
8. **Pedro volta:** F3 600 → B9 C7 400 → B4 C5 P9 1500 (aceno). Ânimo < −0,15: antes um B1 C9 800
   ("demorou, hein"). Mantém o fone se há música.
9. **Pedro fala com ela:** (se E2) P11 E2→E3 500 → F3 (olha para ele) e bocas V* com a voz → ao fim,
   5 s depois, se a música continua: P11 E3→E2 600 (põe o fone de volta).

**Interrupção**
- **Interrompe na hora (corta a cena atual):** Pedro fala com ela, clique no retrato, sistema grave.
- **Espera na fila (1 vaga, validade 30 s; depois descarta):** Pedro volta, jogo abre/fecha,
  música começa/para, ama/odeia. Novo da mesma prioridade substitui o da fila.
- **Absorvido (some):** qualquer acontecimento do mesmo tema da cena atual (outra reação de música
  dentro da cena de música; segunda queda de FPS dentro da cena de FPS) e todo o resto de menor
  peso (notificação, Claude rodando, LED).
- Cena interrompida não recomeça; o rosto vai direto ao repouso do estado novo.

## 4. (c) Humor dela

Ânimo −1..+1, energia 0..1. **Base:** ânimo **+0,1**; energia **0,5** (dia), **0,3** (22h–04h),
**0,65** com jogo aberto. **Meia-vida** de volta à base: ânimo **20 min**, energia **15 min**.
Nenhum evento passa de ±0,3. Troca de faixa de humor só com **histerese de 0,1** e após **2 min**
na faixa nova (rosto não pisca entre faixas).

| Evento | Δ ânimo | Δ energia |
| --- | --- | --- |
| Faixa nota 2 (Ado: +0,3 / +0,2) | +0,25 | +0,15 |
| Faixa nota 1 | +0,10 | +0,05 |
| Faixa nota −1 | −0,15 | +0,05 (irritação acorda) |
| Faixa nota −2 | −0,25 | +0,10 |
| 3 pulos em 2 min | −0,10 | +0,10 |
| Cada 15 min de música com média ≥ 1 (até +0,3) | +0,10 | 0 |
| Jogo abre | +0,10 | +0,25 |
| Jogo fecha em paz | +0,10 | −0,15 |
| FPS/calor em jogo (1ª da partida; repetições −0,05, teto −0,2 por partida) | −0,10 | +0,10 |
| FPS recuperou / alívio térmico | +0,15 | 0 |
| Pedro volta | +0,20 | +0,15 |
| Pedro fala com ela | +0,10 | +0,10 |
| Elogio (tag) | +0,30 | +0,10 |
| Zoeira (tag) — ela gosta de briga | +0,05 | +0,20 |
| Correção (tag) | −0,10 | +0,05 |
| Claude terminou / commit | +0,10 | 0 |
| Erro do Claude / popup | −0,05 | +0,05 |
| Faxina terminou ("fui eu") | +0,15 | 0 |
| Silêncio longo (sem música e Pedro inativo), a cada 20 min; piso −0,4 | −0,05 | −0,10 |
| Humor do Pedro ≤ 1 | puxa para 0 | −0,10 |

| Faixa de ânimo | Rosto de repouso | Fundo | Passivas permitidas | Proibidas |
| --- | --- | --- | --- | --- |
| Radiante (≥ +0,5) | B1 C10 (com energia ≥ 0,75: B4 C5) | `happy` (`focus` em jogo) | sorriso de canto, piscada de gato, presilha, cantarolando, rindo sozinha, cabeça no ritmo (só com música) | suspiro, beicinho, franja |
| Bem (+0,15..+0,5) | B1 C10 leve | `calm` → `happy` com música nota ≥ 1 | respirar, piscadas, sacada, presilha, sorriso de canto, cabeça no ritmo/ajeitando o fone (só com E2) | suspiro, beicinho |
| Neutra (−0,15..+0,15) | B1 C1 | `calm` | respirar, piscadas, sacada, observando o HUD, presilha, fone em repouso (só com E3) | rindo sozinha, cantarolando |
| Irritada (−0,5..−0,15, energia ≥ 0,5) | B1 C9 | `stress` | beicinho, franja, encarando, observando o HUD | sorriso de canto, cantarolando, rindo |
| Entediada (−0,5..−0,15, energia < 0,5) | B2 C1 | `calm` | suspiro, observando o HUD, respirar | sorriso, cantarolando, franja |
| Baixa (≤ −0,5) | B10 C1 | `sad` | respirar, suspiro (≤ 1/h) | tudo de zoeira e de festa |

Energia < 0,25 → pálpebra B2 no repouso, fundo `sleepy`, libera bocejo/cabeça pesada (com as
regras de sono já decididas). Energia > 0,75 → intervalo de passiva menor (ver (a)).
**Medidor:** mostra o ânimo dela (−1..+1) com a cor do fundo da faixa atual.

## 5. (d) Passivas negativas

Não corto, **amarro a motivo**: beicinho e franja só em "Irritada" **e** com gatilho vivo (faixa
ruim tocando, pulos, ou Pedro ativo no PC há ≥ 15 min sem música nem conversa — ela está sendo
ignorada); suspiro só em "Entediada/Baixa" ou dentro da cena "música para". Cada uma ≤ 2/h,
somadas ≤ 3/h. Nunca com Pedro mal, nunca 22h–04h (beicinho/franja).

## 6. (e) Enxurrada em jogo

A cobrança é **uma cena por problema por partida** e depois vira **estado**:
1ª queda de FPS (ou calor) → cena F3 C11 1200 → B6 C8 D2 P13 1500. Enquanto o problema durar:
fundo `stress`, repouso B6 C8, sem repetir animação. Só conta queda real (FPS < 75% da média da
partida por ≥ 5 s; calor com histerese de 3 °C). Se continuar ruim após 10 min: um "eu avisei"
B7 C12 1000 (≤ 1 a cada 15 min). Piorou de nível (temperatura crítica) → fura. Recuperou → vitória
curta B4 C5 P12 1200 (fura cota) e volta ao repouso do humor. Ao fechar o jogo, a conta da
partida decide o roteiro 6.

## 7. (f) Momentos

Primeiro o diretor decide **qual é o momento**, depois sorteia **só dentro do grupo** dele. O
humor (seção 4) filtra o grupo: passiva proibida pela faixa de humor sai mesmo que o momento
permita. O momento é recalculado a cada acontecimento e a cada 30 s, e só troca se o novo vale
por **≥ 30 s** (exceto Jogando e Conversa, que entram na hora).

| Prioridade | Momento | Reconhecido por | Rosto de repouso | Passivas do grupo |
| --- | --- | --- | --- | --- |
| 1 | **Conversa** | Magui ouvindo/falando, ou turno do Pedro há < 60 s | F3, B1 C1 (fone E3) | nenhuma (só a cena 9) |
| 2 | **Jogando — combate** | jogo aberto **e** música nota 2 tocando | B6 C8 E2 (modo chefe) | cabeça no ritmo, sacada de olhar; nada de piscada fofa |
| 3 | **Jogando** | jogo aberto | B6 C8 (energia alta) / B1 C1 | sacada de olhar, observando o HUD (FPS/temperatura), respirar. Sem raras (já decidido) |
| 4 | **Madrugada** | 22h–04h **e** Pedro ativo ou música tocando | B2 C1, fundo `calm`/`sleepy` | respirar, piscada de gato, cabeça no ritmo lento (só com música); bocejo pelas regras de sono. Sem zoeira |
| 5 | **Estudando** | Learning ligado | B1 C1, olhar F7/F5 de quem lê junto | respirar, sacada de olhar, mão no queixo P10 (≤ 2/h). Sem cantarolar, sem franja: ela não atrapalha a aula |
| 6 | **No flow** | Claude rodando, ou Pedro ativo ≥ 10 min sem pausa > 2 min | com música: F7 C1 E2; sem: B1 C1 | respirar, piscadas, sacada, observando o HUD, cabeça no ritmo (só com E2). Sem raras, sem negativas |
| 7 | **Curtindo** | música tocando com nota ≥ 1 (sem os de cima) | B1 C10 E2 | cabeça no ritmo, ajeitando o fone, sorriso de canto, piscada de gato, cantarolando/rindo sozinha (raras), cantando junto (1 por faixa, nota 2) |
| 8 | **Aturando** | música tocando com nota ≤ −1 | B1 C9 E3 | beicinho, franja, encarando (1×), observando o HUD |
| 9 | **Ouvindo** | música tocando nota 0 | B1 C1 E2 | respirar, piscadas, sacada, presilha, cabeça no ritmo |
| 10 | **Esperando** | Pedro ativo, sem música, sem jogo, sem Claude (ele está no PC e ela não tem nada) | B1 C1 E3 | respirar, piscadas, sacada, presilha, observando o HUD, fone em repouso; após 15 min: franja/beicinho (ignorada) |
| 11 | **Tédio** | Pedro inativo ≥ 10 min e sem música | B2 C1 E3 | suspiro (≤ 2/h), observando o HUD, respirar, falando sozinha (rara); energia < 0,25 → sono pelas regras |

**Desempate:** vale a de número menor. Exceção da Asuka: se o humor está em "Radiante",
Esperando e Tédio viram **Ociosa feliz** (rosto B1 C10, grupo: sorriso de canto, presilha,
piscada de gato, rindo sozinha) — ela não fica entediada logo depois de uma vitória.
**Teste do Pedro:** todo log de passiva grava `momento` + `faixa de humor`; se a passiva não
cabe nos dois, é defeito.
