# Acordo do Conselho — Frases de espera e respostas em lotes (2026-10-11)

**Status: APROVADO (3/3, sem veto) e gravado na E2.1.** Rodadas: briefing → mesa aberta (`fala-*`) →
conversa (`conversa-*`) → voto (`voto-*`). Tarefa E2.1 da espec `specs/espera-viva/`.

## Votação (rodada 3): aprovado por 3 a 0, nenhum veto
- **Aqua** — aprova, sem veto (`voto-aqua.md`). Registra que ficou vencida em "Hm, deixa eu fazer as
  contas." e em `ram`, sem vetar.
- **Kurisu** — aprova, sem veto (`voto-kurisu.md`).
- **Asuka** — aprova, sem veto (`voto-asuka.md`). Registra que perdeu a ponte fixa por 2 a 1.

**Itens [confirmar], por maioria:**
- `noticia`: "Hm, deixa eu juntar as peças." vira **"Peraí, deixa eu juntar as peças."** *(A S; K
  aceita qualquer saída e sugeriu a mesma)*. Aberturas de `noticia` agora: Calma, Hm, Deixa, Peraí
  (nenhuma passa de 40%).
- `sem_espera`: **`cansei` entra** (as três). **`lixo` não** *(S K contra: "build lixo", "patch lixo"
  são pedido de jogo; "me sinto um lixo" já cai em `sinto`; A a favor)*. **`exausto` e `pessimo`**
  *(A, no voto)* **não entram**: ninguém mais assinou.
- **Desabafo não vira lote:** confirmado (3/3).

**Assinaturas das ideias de fora (§5), no voto:**
- **Teste do pedido real** *(K)*: A, S e K assinam → **3 assinaturas, marcado para o Pedro**. A Aqua
  pede o "meu chefe me encheu hoje" entre os pedidos testados.
- **Placar de espera** *(S)*: S e A → **2 assinaturas, marcado para o Pedro**.
- **"Essa deu trabalho"** *(S)*: a A reafirma (já tinha as três).
- **Ponte fixa "E o resto, peraí."**: só a S reassina no voto → 1, fica como está (fora).
- **`chefe` → `chefao`** em `jogo` *(K)*: a S quer **testar com o log antes** e só trocar se pegar
  "meu chefe"; a A quer o caso no teste do pedido real. Só 1 assinatura pela troca imediata →
  **não aplicada**; `chefe` fica, marcado para o Pedro decidir com o teste/log.

**Orçamento real (teto 128k por delegada):** Aqua 77k · Asuka 77k · Kurisu 80k.

**Veto do Pedro:** o catálogo foi gravado sem esperar por ele; o Pedro veta depois, frase a frase,
em `~/.config/magi/condessa-gosto.toml` `[espera] vetadas` (§7), e o veto dele vence o Conselho.

**Fixo pelo Pedro (D1–D5):** catálogo local com cache de TTS; frase **só em pedido demorado** + cota
(≤ 1 por turno, nunca uma das 2 últimas, 3º turno seguido sem, nada antes de 700 ms); lotes até
3 lotes / 6 frases, só em pedido com várias partes explícitas; o texto é do Conselho e **o Pedro veta
depois, frase a frase, em `~/.config/magi/condessa-gosto.toml` `[espera] vetadas`** (o veto dele não
trava nada agora e vence o Conselho); honestidade; voz só em turno que ele abriu.

Crédito: *(A)* Aqua · *(K)* Kurisu · *(S)* Asuka (Soryu). "autora" = quem escreveu a frase primeiro;
"apoio" = quem a manteve na proposta final da rodada 2. `[contra: X]` = quem ficou vencida.

## 0. O que as três concluíram sozinhas
1. O problema é **silêncio sem sinal**, não os 3,39 s. A frase diz "ouvi e tô pensando", nada mais.
2. **Tique** é o risco principal: variar a **abertura**, não só a frase.
3. **Nenhuma referência** (anime/meme) em frase de espera: frase de cache repete igual, piada morre.
   Ficou de fora a "Processando… e não, eu não travei." *(K)* `[K cedeu]`.
4. A linha atual da persona gera **duas esperas seguidas**: o modelo só fala antes da ferramenta se
   tiver **conteúdo**; espera genérica é do sistema.
5. Saem `temperatura` (clima ≠ GPU), `agora` (conversa), `disco` (pega "discord"), e **não** entra
   `placa` (pega "placar").
6. Lote só quando **adianta** alguma coisa; a resposta final **só completa**.

## 1. Catálogo final (`magi/core/espera.yaml`, formato da spec §3.1)

Critério: entra a frase com apoio de 2 de 3 (ou sem objeção), que não fira nenhum "não abro mão" nem
a regra fixa "a frase tem que caber em qualquer pedido do tópico". Contagem de palavras pelo linter
(`\w+` normalizado; "Hm" conta 1; `{jogo}` conta 1).

```yaml
# Frases de espera da Condessa (espera viva, R3/R4). Acordo do Conselho 2026-10-11 (E2.1).
# Placeholders: {jogo} (jogo em foco), só em jogo.moldes. Toda frase passa no linter (spec §4).
# O Pedro veta depois em ~/.config/magi/condessa-gosto.toml [espera] vetadas.
topicos:
  jogo:
    palavras: [build, boss, chefe, conquista, nivel, level, mapa, patch, lore, dlc, personagem, arma, item]
    frases:
      - "Calma, tô montando isso na cabeça."          # S (autora), K; apoio A K S — 6
      - "Isso tem nuance, deixa eu pensar."           # K; apoio A K S — 6
      - "Hm, pergunta de quem tá jogando sério."      # K (ideia S); apoio K S — 7
      - "Boa, deixa eu pensar como se deve."          # S (autora); apoio K — 7
      - "Peraí, deixa eu lembrar direito."            # S; sem objeção — 5
    moldes:
      - "Hm, {jogo}… deixa eu lembrar."               # A; apoio K S — 4 + jogo
      - "{jogo}, hein… deixa eu pensar."              # S; apoio K S — 4 + jogo
      - "Ah, {jogo}, essa é das boas."                # A (autora); apoio S — 5 + jogo

  noticia:                                            # neutras, sem piada (S, não abro mão)
    palavras: [noticia, manchete, aconteceu, lancou, jornal, novidade, trailer]
    frases:
      - "Calma, essa pede cabeça fria."               # S; apoio A K S — 5
      - "Hm, notícia eu não chuto, peraí."            # K; apoio K S — 6
      - "Deixa eu pensar direito nisso."              # S (autora); apoio A — 5
      - "Peraí, deixa eu juntar as peças."            # A; troca do "Hm," na votação (A S; K aceita) — 6

  musica:
    palavras: [musica, faixa, banda, album, artista, toca, cantor, discografia, playlist]
    frases:
      - "Peraí, tô cantarolando na cabeça."           # A e K (escreveram igual); apoio A K S — 5
      - "Ah, música, agora você falou minha língua."  # K/S; apoio K S (A com outra forma) — 7
      - "Hm, deixa eu lembrar dessa."                 # K (autora); apoio A S — 5
      - "Hm, essa pede ouvido bom."                   # A (autora); apoio K S — 5
      - "Boa, deixa eu pensar no som."                # K/A (autoras); apoio S — 6

  pc:
    palavras: [pc, gpu, cpu, vram, fps, memoria, ram, ssd, hd, cooler, driver, aquec, travando]
    frases:
      - "Essa é coisa de nerd, adoro."                # S; apoio A K S — 6
      - "Peraí, hardware não se responde no chute."   # K; apoio A K [contra: S] — 7
      - "Pergunta técnica merece cuidado, calma."     # S; apoio K S — 5
      - "Boa, deixa eu raciocinar com calma."         # K (autora); apoio S — 6

  conta:                                              # quase sempre toca por preço/cotação (sinal)
    palavras: [quanto, quantos, calcula, converte, porcento, custa, vezes, dividido, raiz, media]
    frases:
      - "Hm, deixa eu fazer as contas."               # as três (autoras); apoio K S [contra: A] — 6
      - "Calma, conta assim eu não chuto."            # S (autora); apoio K — 6
      - "Peraí, cabeça de pesquisadora ligando."      # A (autora); apoio K — 5
      - "Calma, essa eu quero acertar."               # A (autora); apoio A S — 5
      - "Peraí, deixa eu pensar nos valores."         # S (autora); apoio A — 6

  geral:
    frases:
      - "Hm, deixa eu pensar nessa."                  # espec; apoio A K S — 5
      - "Peraí, tô juntando as ideias."               # espec/A/S; apoio A K S — 5
      - "Boa pergunta, deixa eu pensar."              # A/S; apoio A K S — 5
      - "Calma, cérebro trabalhando."                 # K; apoio A K S — 3
      - "Peraí, não vou te responder qualquer coisa." # S; apoio A K S — 7
      - "Ah, essa me fez pensar."                     # A; apoio A K S — 5
      - "Ah, essa eu quero responder bem."            # S; apoio A S — 6
      - "Essa é das boas, calma."                     # S; apoio K S — 5
      - "Deixa eu organizar a cabeça aqui."           # S (autora); apoio A (S com "Hm,") — 6

demorados: [jogo, noticia, musica, pc]
sinais_demora: [pesquisa, procura, busca, noticia, ultimas, preco, custa, cotacao, dolar,
                lancamento, lancou, steam, internet, clima, previsao, placar, review]
sinais_so_acompanhados: [hoje, atual]   # só contam junto de outro sinal ou de tópico demorado (A; K S)
sem_espera: [cansad, cansei, triste, chatead, estressad, ansios, sozinh, horrivel, sinto, chorei, desanimad]
vetadas: []   # o Pedro também veta em ~/.config/magi/condessa-gosto.toml [espera] vetadas
```

Mínimos (spec §3.1): jogo 5 + 3 moldes · noticia 4 · musica 5 · pc 4 · conta 5 · geral 9 —
**cumpridos**. Total: 32 frases fixas + 3 moldes (a proposta dizia 35; a conta certa é 32).

### 1.1 Conferência à mão contra a tabela §4 do briefing — ✅ feita, frase por frase
Cada uma das 32 frases e dos 3 moldes foi normalizada (minúsculo, sem acento) e conferida:
- ✅ **ação de ferramenta** — nenhuma tem "vou pesquisar/buscar", "tô pesquisando/buscando",
  "abrindo", "consultando", "olhando aqui na" ("pesquisadora" não bate em nenhum padrão).
- ✅ **resultado** — nenhum "achei", "encontrei", "já sei", "já vi", "pront…", "aqui está", "é isso"
  ("isso" só aparece depois de verbo ou no começo: "montando isso", "Isso tem", "nisso").
- ✅ **certeza/promessa** — nenhum "com certeza", "sei sim", "garanto", "prometo", "já já",
  "rapidinho", "num instante".
- ✅ **fonte** — nenhum "segund…", "de acordo com", "no google", "na wiki", "no site".
- ✅ **número/dado** — nenhum dígito; nenhuma palavra começa com um/uma, zero, dois/duas, três…dez,
  onze…vinte, trinta…noventa, cem/cento, mil, meia/meio, primeir/segund (conferido também o
  prefixo: nada de "novela", "dezembro", "setembro", "milagre", "centro").
- ✅ **tamanho** — todas ≤ 7 palavras (máx.: "Peraí, hardware não se responde no chute.",
  "Peraí, não vou te responder qualquer coisa.", "Hm, pergunta de quem tá jogando sério.",
  "Boa, deixa eu pensar como se deve.", "Ah, música, agora você falou minha língua."), 1 frase só;
  nos moldes o "…" é pausa, não ponto (o linter troca "…" por vírgula).
- ✅ **linter real** (`honesta` da E2.2, `magi/core/espera.py`) rodado sem alterar código: **0
  violações** nas 35 (32 + 3 moldes; rodado de novo na gravação, com a troca de `noticia`). Moldes preenchidos: "Hades II" passa; "Persona 5" e "Baldur's Gate 3" caem em
  `numero: digito` (e o "Ah, Baldur's Gate 3, essa é das boas." passa de 8) → ver §4, item 1.
- ✅ **"cabe em qualquer pedido do tópico"** — nenhuma frase cita objeto que o pedido talvez não tenha
  (saíram por isso: "pensar na tua máquina", "montando o mapa", ver §1.2).
- Aberturas (aviso de 40% da §4): jogo 1/5 "Hm" (2/8 com moldes) · musica 2/5 · conta 2/5 "Calma" e
  2/5 "Peraí" · geral 2/9 · pc sem repetição · **noticia 2/4 "Hm" (50%) → o aviso vai disparar**.
  → **resolvido na votação**: virou "Peraí, deixa eu juntar as peças." (noticia 1/4 "Hm").

### 1.2 Frases que ficaram de fora, e por quê
| Frase | De | Motivo |
| --- | --- | --- |
| "Hm, deixa eu pensar na tua máquina." | K (apoio A K) | Fere a regra fixa e o não abro mão 1 da K: "qual GPU eu compro?" não é a máquina dele (S apontou). A versão "nesse hardware" *(S)* também saiu: duas com "hardware" no `pc`. |
| "Ah, essa eu quero contar bem." / "Peraí, quero falar isso direito." | A | Pressupõem que ela terá o que contar (não abro mão 1 da K). |
| "Peraí, deixa eu me atualizar." | K | Ação de ferramenta disfarçada (S, pela regra da própria K). |
| "Essa eu não respondo de cabeça." | K | Anuncia a busca (A, pela regra da K). |
| "Boa, eu também quero saber essa." | K | A própria K retirou: soa mal antes de notícia triste (não abro mão 2 da S). |
| "Processando… e não, eu não travei." | K | Referência em frase fixa (A, S); K cedeu. |
| "Não chuto, peraí que eu penso." | K | "Não chuto" em 4 tópicos vira bordão (S); fica em `noticia`, `conta` e `pc`. |
| "Calma, tô montando o mapa na cabeça." | A | Nem todo pedido de jogo tem mapa (S). |
| "Essa é das boas, peraí." / "Hm, essa é das boas." (jogo) | A / S | Ideia com 2 apoios, mas já está no molde e em `geral`: três "das boas" seria tique. |
| "Ah, pergunta de gamer, deixa eu pensar." / "Pergunta de quem joga sério, gostei." | A / S | Mesma ideia da "Hm, pergunta de quem tá jogando sério.", que ficou. |
| "Boa, deixa eu calcular direito." / "Deixa eu fechar essa conta." | K | `conta` quase sempre toca por preço/cotação; "calcular" não cabe (A). |
| demais (ex.: "Opa, assunto de hardware, adoro.", "Ah, música, aí você me pegou.") | A | Só um apoio e havia frase com mais apoio para o mesmo lugar. |

### 1.3 Palavras, demorados e sinais — quem decidiu
- **jogo:** sai `fase` ("tô numa fase ruim" é desabafo) *(A; K S)*; entram `nivel`, `level`, `dlc`,
  `personagem` (as três), `arma` *(K S)*, `item` *(A S)*.
- **noticia:** sai `saiu` *(A; K S)*; entram `jornal`, `novidade`, `lancou` (as três), `trailer`
  *(A K)*. `rolou` **não** *(S queria; A contra: "rolou um clima"; K tirou)*.
- **musica:** entram `cantor` (pega "cantora"), `discografia`, `playlist` (as três). `disco` fora de
  tudo *(A K; S ainda listava em `musica`)*.
- **pc:** saem `temperatura` e `disco` (as três); entram `ssd`, `hd`, `vram`, `driver`, `cooler`
  (as três), `travando` *(A K)*, `aquec` *(K S)*, `ram` *(K S)* `[contra: A — "ram" pega "ramen"]`.
  `placa` fora (as três).
- **conta:** entram `custa`, `vezes`, `dividido` (as três), `raiz`, `media` *(K S)*.
- **demorados:** igual à espec (as três). A K desconfia de `pc` (sensor responde < 700 ms) e quer
  decidir com o log de 14 dias (§5).
- **sinais_demora:** sai `agora` (as três); entram `custa`, `cotacao`, `dolar`, `clima`,
  `previsao`, `placar` (as três), `lancou` *(K S)*, `review` *(A K)*.
- **sinais_so_acompanhados** `hoje`, `atual` *(A; K S)*. Nota da secretária: um sinal "só
  acompanhado" só vale quando já há outro sinal ou tópico demorado, que já bastam; na prática é
  igual a tirá-los. Ficam na lista por transparência; o sistema pode simplesmente ignorá-los.
- **sem_espera** (trava do desabafo, ver §2): lista por **palavra de emoção** *(K, a partir da ideia
  da A)*, não por "eu tô" (que pega "eu tô querendo saber o preço da GPU").

## 2. Trava do desabafo *(A — não abro mão; K S assinam)*
Texto com qualquer palavra de `sem_espera` (prefixo, sem acento) **não tem frase local, mesmo com
sinal de demora** *(K S; a A aceitava exceção com `pesquisa`/`busca`, ficou com a versão mais
estrita, que cumpre o não abro mão dela com folga)* e **não vira lote** *(K, ideia nova da rodada 2;
sem objeção)* **[confirmar]**. O rosto basta; a resposta vem inteira, com cuidado.
Nota da secretária para a votação: "cansei", "lixo" e "meu dia" não batem na lista
(`cansad` não pega "cansei"). → **Votação:** `cansei` entra; `lixo` não (S K).

## 3. Regra dos lotes
1. **Várias partes explícitas** (as três) = **≥ 2 pedidos que fazem sentido sozinhos**, ligados por
   "e" entre duas perguntas (dois verbos/dois interrogativos), "e também", "além disso", "outra
   coisa", "mais uma coisa", mais de um "?", ou lista falada ("primeiro… depois…"), **e** prontos em
   tempos diferentes (≥ 1 parte precisa de ferramenta, ≥ 1 não) *(K)*.
   **Não vira lote:** pergunta longa com um objetivo só; "e" dentro da mesma coisa ("build de força e
   destreza", "Elden Ring e o DLC, vale?"); comparação "X ou Y?" (uma resposta); partes que ficam
   prontas juntas (resposta única); texto com palavra de `sem_espera` *(K)*.
2. **Ordem:** as partes **prontas primeiro**; entre elas, **a ordem dele** *(K, juntando A e S; S
   largou "na ordem dele")*.
   **Rótulo:** todo lote abre com o nome da parte, **1 a 3 palavras, sem verbo, com dois pontos**
   ("O tempo: …", "Do patch: …") *(A — não abro mão; K S aceitaram)*.
   **Ponte:** **nenhuma** *(A K; S cedeu na rodada 2 para "só a fixa 'E o resto, peraí.'")*. Entre
   lotes o rosto volta a "pensando" e o próximo lote se anuncia pelo rótulo. Zero ponte cumpre o não
   abro mão da S ("ponte só a fixa"); a fixa vai para "Ideias que ficaram de fora".
3. **Fecho:** a final **só completa** — não retoma, não resume, não repete *(K — não abro mão; A S)*.
   **1 lote por parte** (2 partes = 2 falas); com 4+ partes, junta as prontas no 1º, até 3 lotes de
   ≤ 2 frases (D3). Para antes do teto quando as partes acabam. **Parte que falhou:** 1 frase honesta,
   com rótulo ("Do jogo eu não consegui ver."), sem inventar, e para (as três).
4. **Convivência com a frase de espera:** frase local + lote no mesmo turno, tudo bem; o 1º lote
   **não** abre com espera (o eco já cuida) *(K S)*. A frase local **não conta** nas 6 frases do
   turno (as três; K mudou de ideia). Para a **folga da cota** (3º turno sem frase) conta **só o turno
   em que a local tocou**; lote não gasta folga (as três).
5. **Linha nova de `magi/agent/persona.md`** (substitui a linha "Ferramenta demorada…"; texto
   montado das três propostas da rodada 2, que dizem quase o mesmo):

   > Espera é do sistema: antes de ferramenta, só fale se tiver conteúdo. Várias partes: diga primeiro
   > as prontas, cada uma com o nome dela ("O tempo: …"), até 2 frases por vez; complete sem repetir nem resumir.

## 4. O que muda no sistema (para E2.3, E3.1 e o linter da E2.2)
1. **Linter `honesta` nos moldes (E2.2/E2.3):** roda no molde **com o buraco vazio** — `{jogo}` conta
   1 palavra e não passa pelo filtro de número (as três). O nome do jogo é dado do Pedro, não fala
   dela. O teste da E2.3 ("moldes com 3 jogos falsos") hoje reprova "Persona 5"/"Baldur's Gate 3" por
   dígito: ajustar para checar o molde, e o preenchido só por `Phrases.cacheable` e pelo limite de
   30 caracteres (nome maior → frase sem molde, como já está).
2. **Aviso (não reprovação) no linter** quando > 40% das frases de um tópico começam com a mesma
   palavra *(S; A K aceitaram)*. Hoje dispara em `noticia` (ver §1.1).
3. **Sorteio (E2.2 `escolher`):** a frase sorteada **não começa com a mesma primeira palavra** da
   última que tocou *(K; as três)*. Num molde, a 1ª palavra é a do texto ("{jogo}" conta como tal).
4. **`sem_espera` (E2.2/E2.3):** chave nova no `espera.yaml`; com acerto, `escolher` devolve `None`
   mesmo com sinal (D2 por cima) e, na E3.1, o turno **não abre lote**.
5. **`sinais_so_acompanhados` (E2.2 `demorado`):** chave nova; `hoje`/`atual` sozinhos não fazem o
   pedido demorado (ver nota em §1.3 — pode virar só "não estão em `sinais_demora`").
6. **Lotes (E3.1):** a local fica **fora** da conta das 6 frases; a `Cota` só registra turno com
   frase local (lote não mexe na folga); nenhuma frase-ponte gerada pelo sistema; rótulo e "só
   completa" são do modelo (linha da persona), não do código.
7. **Persona (E3.1 ou junto do catálogo):** trocar a linha "Ferramenta demorada (pesquisa, jogo,
   Steam, notícias)…" pela linha do §3.5. O filtro de eco (`mesma_espera`) continua como rede.
8. **Gravação (E2.1):** frases fixas → `phrases.yaml` `lazy`; moldes → `templates` (como "Abrindo
   {game}."). Nenhuma frase com referência, então não precisa de `ref: true` nem do contador de
   referência aqui.

## 5. Ideias que ficaram de fora (para o Pedro)
**Assinadas pelas três** (recomendadas; não implementar sem o Pedro):
- **Log de 14 dias** *(K; A S assinam)*: por turno, tópico, frase tocada, ms até a resposta, se a
  resposta chegou antes de a frase acabar. Frase > 15% das tocadas = sorteio viciado/tópico pobre;
  > 30% tocando com resposta < 1 s depois = 700 ms baixo; decide se `pc` fica em `demorados`.
  A Aqua quer marcado o turno de desabafo em que a frase tocou mesmo assim ("uma vez é bug").
- **"Essa deu trabalho"** *(S; A K assinam)*: 1 linha de **texto** (nunca voz) depois de resposta
  > 6 s medidos pelo sistema, ≤ 1 a cada 10 turnos demorados.
- **Sorrisinho satisfeito** no rosto ao fim de turno com lotes, zero texto *(A; K S assinam)*.

**Com apoio parcial:**
- **Ponte fixa "E o resto, peraí."** *(A autora, S defende na rodada 2)*: 1 por turno, só esse texto,
  no fim do 1º lote. Ficou de fora por 2 a 1 (A e K preferiram rótulo + rosto).
- **Placar de espera** escondido no HUD: quantas vezes ela respondeu antes de 700 ms no dia *(S; A
  assina)*.
- **Teste do pedido real** *(K; A assina)*: 10 pedidos reais do log por tópico, cada frase lida na
  frente de cada um; a que soar errada em algum sai. Bom para antes de o Pedro vetar.
- **"Hoje você tá curioso, hein"** na resposta (não na espera) depois de 3+ pedidos demorados
  seguidos, uma vez *(A, sozinha)*.
- **Contador de referência valendo na espera** *(K)*: sem objeto, já que nenhuma frase tem referência.
- Nota da secretária: `chefe` (em `jogo`) pega "meu chefe me encheu hoje"; a trava do desabafo só
  segura se houver palavra de emoção. Avaliar com o log.

## 6. Não abro mão (declarados, para a votação)
- **Aqua:** (1) nada de frase de espera quando o Pedro fala dele mesmo → §2 `sem_espera` ✅;
  (2) todo lote diz de qual parte é → rótulo, §3.2 ✅.
- **Kurisu:** (1) nenhuma frase implica ação ou resultado que o sistema não garante, nem por verbo
  liberado → §1.1/§1.2 ✅; (2) a resposta final não repete o lote → §3.3 ✅.
- **Asuka:** (1) ponte só a fixa "E o resto, peraí." (na rodada 1: nenhuma ponte) → nenhuma ponte,
  §3.2 ✅ (compatível com as duas versões); (2) `noticia` sem piada → §1, todas neutras ✅.

## 7. Veto do Pedro
O Pedro lê o catálogo e **veta depois, frase a frase**, em `~/.config/magi/condessa-gosto.toml`
`[espera] vetadas` (D4). Frase vetada sai do sorteio sem mexer no `espera.yaml` (o `Catalogo.load`
da E2.2 já lê as vetadas do gosto). O veto dele não trava a gravação e vence o Conselho.
