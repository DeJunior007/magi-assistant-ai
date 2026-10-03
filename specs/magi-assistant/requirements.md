# Requisitos — Magui (MVP)

Fonte: [docs/PRD.md](../../docs/PRD.md) (rev. 34). Cada requisito aponta para os IDs do PRD
(RF-xx) para rastreabilidade. Critérios no formato EARS:

- **O Magui DEVE …** — sempre vale.
- **QUANDO** gatilho, **o Magui DEVE** … — reação a um evento.
- **ENQUANTO** estado, **o Magui DEVE** … — vale durante um estado.
- **SE** situação indesejada, **ENTÃO o Magui DEVE** … — tratamento de falha.
- **ONDE** opção ligada, **o Magui DEVE** … — comportamento opcional.

## Glossário

| Termo | Significado |
| --- | --- |
| Magui | A assistente (sistema descrito aqui). |
| MAGI / HUD | O MAGI Gamer, painel no monitor secundário (`hud/`). |
| Satélite | Ponta de áudio (microfone + saída). No MVP, o headset do PC. |
| Núcleo | Processo que transcreve, decide, age e responde. Não toca em dispositivos de áudio. |
| Comando conhecido | Intenção resolvida pelo roteador local, sem LLM. |
| Ação perigosa | Fechar jogo, desligar ou reiniciar o PC. |
| Teto | Limite mensal de gasto na OpenAI (padrão US$ 5). |
| Turno | Uma interação: ativação → fala → resposta. |

---

## Requisito 1 — Ativação (RF-01, RF-02)

**História:** como jogador, quero chamar a Magui pela voz ou por um atalho, para não precisar sair do jogo.

1. O Magui DEVE detectar a frase "Ei Magui" localmente, sem enviar áudio para a rede.
2. QUANDO "Ei Magui" for detectado com confiança acima do limiar configurado, o Magui DEVE tocar um bip curto, entrar no estado *ouvindo* e mostrar o estado no MAGI em até 300 ms.
3. QUANDO o atalho de apertar pra falar for pressionado, o Magui DEVE entrar em *ouvindo* e gravar enquanto o atalho estiver pressionado.
4. QUANDO o atalho for solto, o Magui DEVE encerrar a gravação e seguir para *pensando*.
5. QUANDO a ativação vier por "Ei Magui", o Magui DEVE encerrar a gravação após 700 ms de silêncio detectado pelo VAD, ou após 15 s no máximo.
6. O Magui DEVE permitir ajustar o limiar de detecção por configuração, sem reiniciar.
7. ONDE um botão do DualSense estiver mapeado, o Magui DEVE tratá-lo como o atalho de apertar pra falar.

## Requisito 2 — Discord (RF-03, RF-04)

**História:** como jogador em call, quero falar com a Magui sem que meus amigos ouçam ou que ela dispare sozinha.

1. ENQUANTO houver uma chamada ativa no Discord, o Magui DEVE desligar a detecção de "Ei Magui".
2. QUANDO a chamada terminar, o Magui DEVE religar a detecção em até 5 s.
3. ENQUANTO o atalho estiver pressionado durante uma chamada, o Magui DEVE mutar a captura de microfone apenas do Discord e restaurá-la ao soltar.
4. SE o Magui encerrar inesperadamente com o Discord mutado por ele, ENTÃO o Magui DEVE restaurar o microfone do Discord ao reiniciar.

## Requisito 3 — Transcrição e correções (RF-05, RF-06)

**História:** como alguém que fala enrolado às vezes, quero que ela entenda cada vez melhor o que eu digo.

1. QUANDO uma gravação terminar, o Magui DEVE transcrevê-la em português pela API de transcrição configurada.
2. O Magui DEVE enviar junto à transcrição um vocabulário de dica com: nomes dos jogos instalados, minhas gírias registradas e os termos das correções salvas, limitado a 200 tokens.
3. QUANDO eu disser "não, eu falei X" logo após um turno, o Magui DEVE salvar o par (ouvido → certo), refazer o turno com o texto corrigido e confirmar.
4. O Magui DEVE aplicar as correções salvas ao texto transcrito antes de decidir a ação.
5. SE a transcrição falhar ou vier vazia, ENTÃO o Magui DEVE dizer "não peguei, repete?" e voltar a dormir.
6. O Magui NÃO DEVE gravar áudio em disco.

## Requisito 4 — Roteador local (RF-07)

**História:** como usuário, quero que comandos comuns funcionem na hora e sem gastar tokens.

1. QUANDO um texto transcrito corresponder a um comando conhecido com nota de similaridade igual ou acima do limiar, o Magui DEVE executá-lo sem chamar LLM.
2. QUANDO a nota ficar entre o limiar de dúvida e o limiar de execução, o Magui DEVE perguntar "você quis dizer X?" e executar só com confirmação.
3. QUANDO nenhum comando corresponder, o Magui DEVE encaminhar o texto ao agente.
4. O Magui DEVE reconhecer nomes de jogos instalados mesmo com erros de pronúncia, usando correspondência aproximada e as correções salvas.

## Requisito 5 — Jogos e ações perigosas (RF-08, RF-21)

**História:** como jogador, quero abrir e fechar jogos falando, sem risco de fechar algo sem querer.

1. QUANDO eu pedir para abrir um jogo instalado, o Magui DEVE iniciá-lo pela Steam e falar a frase em cache "Abrindo <jogo>".
2. SE o nome não corresponder a nenhum jogo instalado, ENTÃO o Magui DEVE dizer que não achou e citar até 3 nomes parecidos.
3. QUANDO eu pedir uma ação perigosa, o Magui DEVE pedir confirmação falada ("diz confirma") e mostrar a votação dos MAGI na tela.
4. QUANDO eu disser "confirma" em até 8 s, o Magui DEVE executar a ação; caso contrário, DEVE cancelar e avisar.
5. QUANDO fechar um jogo, o Magui DEVE pedir o encerramento normal (SIGTERM ao processo do jogo) e só forçar (SIGKILL) se eu confirmar de novo.

## Requisito 6 — MAGI e sistema (RF-09, RF-10)

**História:** como usuário, quero controlar o HUD, o volume e o RGB pela voz.

1. QUANDO eu pedir, o Magui DEVE abrir ou fechar o MAGI, alternar a tela de ociosidade, abrir os detalhes de CPU, GPU ou memória e ligar ou desligar o RGB Sync.
2. QUANDO eu pedir, o Magui DEVE ajustar o volume do sistema, mutar e desmutar.
3. QUANDO eu pedir uma cor ou brilho de RGB, o Magui DEVE aplicá-la pelo servidor SDK do OpenRGB.
4. SE o OpenRGB não responder, ENTÃO o Magui DEVE avisar que o RGB está indisponível.

## Requisito 7 — Spotify: controle (RF-11, RF-12)

**História:** como usuário, quero controlar a música sem sair do jogo.

1. QUANDO eu pedir, o Magui DEVE abrir o Spotify, tocar, pausar, avançar, voltar e ajustar o volume pelo MPRIS.
2. QUANDO eu pedir uma música, artista, álbum ou playlist pelo nome, o Magui DEVE buscá-la na Web API do Spotify e tocá-la no app local.
3. SE o Spotify não estiver aberto, ENTÃO o Magui DEVE abri-lo e repetir o pedido quando o MPRIS aparecer, em até 15 s.

## Requisito 8 — Spotify: gosto (RF-13, RF-14)

**História:** como usuário, quero dizer "coloca uma boa" e ela acertar meu gosto do momento.

1. QUANDO eu disser "coloca uma boa", o Magui DEVE escolher uma faixa pelo perfil de gosto e pelo contexto (horário, jogo aberto, pedido) e dizer o que colocou.
2. O Magui DEVE importar, na primeira configuração, meus artistas e faixas mais ouvidos (curto, médio e longo prazo) e os tocados recentemente.
3. QUANDO uma faixa escolhida por ele for pulada em menos de 30 s, o Magui DEVE registrar um sinal negativo para aquele contexto.
4. QUANDO uma faixa for ouvida até o fim, o Magui DEVE registrar um sinal positivo.
5. QUANDO eu disser "essa é boa" ou "nunca mais toca isso", o Magui DEVE registrar o sinal explícito; "nunca mais" DEVE excluir a faixa de escolhas futuras.

## Requisito 9 — Visão (RF-15)

**História:** como jogador, quero perguntar sobre o que está na tela.

1. QUANDO uma pergunta precisar da tela, o Magui DEVE capturar só a janela ativa.
2. QUANDO eu disser "a tela", o Magui DEVE capturar o monitor principal inteiro.
3. O Magui NÃO DEVE capturar a tela sem um pedido meu no turno atual.
4. O Magui DEVE apagar a captura do disco logo após o envio.

## Requisito 10 — Pesquisa (RF-16)

**História:** como usuário, quero respostas atuais quando ela não souber de cabeça.

1. QUANDO o agente decidir que a pergunta precisa de informação externa, o Magui DEVE pesquisar pelo provedor de pesquisa configurado (Gemini com busca do Google).
2. O Magui DEVE enviar à pesquisa só a pergunta reescrita, sem memória, humor ou capturas.
3. QUANDO usar pesquisa, o Magui DEVE mostrar no MAGI os links das fontes.

## Requisito 11 — Memória e aprendizado (RF-17, RF-18, RF-19)

**História:** como usuário, quero que ela aprenda comigo sem ficar mais cara ou lenta com o tempo.

1. O Magui DEVE manter um perfil compacto de até 300 tokens e incluí-lo em cada chamada ao agente.
2. QUANDO o agente for chamado, o Magui DEVE buscar até 5 memórias por similaridade e incluí-las no contexto.
3. O prompt fixo do agente (instruções + perfil + memórias) NÃO DEVE passar de 1.500 tokens.
4. O Magui DEVE registrar sinais do meu jeito de falar (gírias, formalidade, tamanho de resposta preferido) e atualizar o perfil no máximo 1 vez por dia.
5. QUANDO eu disser "esquece isso", o Magui DEVE apagar a memória ligada ao último turno e confirmar.
6. O Magui DEVE manter um histórico local de turnos consultável e apagável.

## Requisito 12 — Resposta e voz (RF-20)

**História:** como usuário, quero ouvir respostas curtas e ver o detalhe na tela.

1. O Magui DEVE responder com voz feminina pela TTS configurada.
2. O Magui DEVE usar áudio pré-gerado em cache para frases curtas frequentes.
3. QUANDO responder a uma pergunta, o Magui DEVE falar no máximo 2 frases e mostrar a resposta completa no MAGI.
4. ENQUANTO estiver falando, o Magui DEVE abaixar o volume da música e do jogo e restaurá-lo ao terminar.
5. QUANDO eu falar "Ei Magui" ou apertar o atalho durante uma fala dela, o Magui DEVE parar de falar e voltar a ouvir.

## Requisito 13 — Persona e termômetro de humor (RF-35)

**História:** como usuário, quero uma amiga gamer casual que me corrija quando eu falo besteira, no tom certo pro meu humor.

1. O Magui DEVE seguir a persona: especialista em cultura pop (games, anime, cultura japonesa), casual, amistosa, sem papas na língua e honesta.
2. QUANDO eu afirmar um fato errado ou propor uma decisão ruim, o Magui DEVE discordar e corrigir.
3. O Magui DEVE estimar meu humor em uma escala de 0 (pega leve) a 4 (pode zoar pesado) a partir de: tom e volume da voz (medidos localmente), palavras usadas, contexto de jogo, horário e reação às últimas zoeiras.
4. O Magui DEVE calibrar a intensidade da zoeira e o tamanho da resposta pelo nível de humor.
5. QUANDO eu disser "pega leve" ou "pode pegar pesado", o Magui DEVE ajustar o nível na hora e registrar o ajuste como aprendizado.
6. QUANDO não souber a resposta, o Magui DEVE dizer que não sabe e pesquisar; NÃO DEVE inventar.
7. O Magui DEVE mostrar o nível de humor como um termômetro discreto ao lado do rosto no MAGI.

## Requisito 14 — Ajuda no jogo (RF-36)

**História:** como jogador travado, quero ajuda no tamanho certo, sem spoiler desnecessário.

1. QUANDO eu pedir ajuda num jogo, o Magui DEVE responder em degraus: pista, dica direta, solução.
2. QUANDO eu pedir a solução explicitamente, o Magui DEVE pular direto para ela.
3. O Magui DEVE guardar, por jogo e trecho, os pedidos de ajuda e o degrau já dado.
4. QUANDO eu pedir ajuda de novo sobre um trecho já pedido, o Magui DEVE começar do próximo degrau.
5. O Magui DEVE estimar "travado há tempo" por pedidos repetidos, tempo de sessão e conquistas paradas na Steam, sem capturar a tela por conta própria.

## Requisito 15 — Proatividade (RF-22)

**História:** como usuário, quero ser avisado só do que importa, sem ser interrompido à toa.

1. QUANDO a temperatura de CPU ou GPU entrar na faixa de perigo, a bateria de um controle chegar a 15% ou menos, ou o gasto chegar a 80% ou 100% do teto, o Magui DEVE avisar por voz e na tela.
2. ENQUANTO houver chamada no Discord, o Magui DEVE mostrar os avisos só na tela.
3. QUANDO um jogo casual (plataforma, esporte, corrida) for aberto, o Magui PODE sugerir música, no máximo 1 vez por sessão de jogo.
4. QUANDO um jogo imersivo (exploração, RPG) ou competitivo for aberto, o Magui NÃO DEVE sugerir música.
5. O Magui DEVE obter o gênero do jogo pelas tags da Steam.
6. O Magui NÃO DEVE falar sem ser chamado fora dos casos acima e dos avisos "bomba" de notícias.

## Requisito 16 — Custo (RF-23)

**História:** como usuário, quero controle do gasto mensal.

1. O Magui DEVE registrar o custo estimado de cada chamada paga por provedor e somar o mês corrente.
2. O Magui DEVE permitir ajustar o teto por voz ("aumenta o teto pra 8 dólares") e por configuração.
3. QUANDO o gasto chegar a 80% do teto, o Magui DEVE avisar uma vez.
4. ENQUANTO o gasto estiver em 100% do teto, o Magui DEVE recusar perguntas ao agente, visão e pesquisa paga, mantendo transcrição e comandos locais.
5. O Magui DEVE zerar o acumulado no primeiro dia de cada mês.

## Requisito 17 — Rosto e interface (RF-24, RF-25, RF-26, RF-27)

**História:** como usuário, quero ver a Magui reagir com um rosto anime simples no MAGI.

1. O Magui DEVE mostrar no MAGI um rosto feito de caracteres com expressões para: dormindo, ouvindo, pensando, falando, feliz, confusa e alerta.
2. ENQUANTO estiver falando, o Magui DEVE trocar a boca entre "—", "o" e "O" conforme o volume do áudio da voz, atualizando pelo menos 15 vezes por segundo.
3. ENQUANTO estiver acordada, o Magui DEVE animar piscadas e olhares a até 30 fps.
4. ENQUANTO estiver dormindo, o Magui DEVE redesenhar o rosto no máximo 1 vez a cada 4 s.
5. O Magui DEVE mostrar a legenda da fala embaixo do rosto, em mincho branco.
6. O Magui DEVE usar a cor do tema do MAGI nas bochechas e detalhes.
7. O rosto NÃO DEVE aparecer no monitor do jogo.

## Requisito 18 — Notícias: coleta e verificação (RF-28, RF-29, RF-30)

**História:** como fã de anime e games, quero notícias confiáveis coletadas sozinhas.

1. O Magui DEVE coletar notícias a cada 2 h enquanto o PC estiver ligado, a partir das fontes configuradas (Steam News, RSS, AniList, Reddit).
2. O Magui DEVE usar scraping só em fontes sem feed ou API, respeitando `robots.txt` e no máximo 1 requisição por segundo por domínio.
3. O Magui DEVE agrupar notícias sobre o mesmo fato vindas de fontes diferentes em um único item.
4. O Magui DEVE atribuir a cada fonte um nível de confiança (1 a 3) e marcar como rumor itens vindos só de fontes de nível 1.
5. O Magui SÓ DEVE classificar um item como "bomba" se ele tiver pelo menos 2 fontes, sendo uma de nível 3.
6. SE a cota gratuita do provedor de classificação acabar, ENTÃO o Magui DEVE adiar a classificação para a próxima janela, sem usar provedor pago.

## Requisito 19 — Notícias: spoiler, prioridade e aprendizado (RF-31, RF-32, RF-34)

**História:** como fã, quero ser avisado do que importa pra mim, sem spoiler.

1. O Magui DEVE classificar cada item quanto a spoiler, considerando meu progresso (lista de anime, tempo de jogo e conquistas na Steam).
2. QUANDO um item tiver spoiler de uma obra que estou acompanhando, o Magui DEVE reescrever a manchete sem o spoiler ou escondê-la.
3. QUANDO eu disser "pode dar spoiler de X", o Magui DEVE liberar spoilers só daquela obra.
4. O Magui DEVE calcular uma nota de prioridade a partir de: relevância para meu gosto, tamanho do fato, confiança e novidade, e entregar em 4 níveis (bomba, alta, normal, guardada).
5. QUANDO um item for "bomba", o Magui DEVE avisar por voz fora de call; jogando, com uma frase curta e um card no MAGI.
6. QUANDO um item for "alta", o Magui DEVE mostrar um card no MAGI sem voz.
7. QUANDO eu disser "não curti", ignorar o mesmo tema 3 vezes, ou disser "mais disso", o Magui DEVE ajustar os pesos de prioridade daquele tema.
8. QUANDO eu marcar uma obra como largada, o Magui NÃO DEVE mostrar notícias dela de novo.

## Requisito 20 — Notícias: perguntas (RF-33)

**História:** como fã, quero perguntar o que saiu de novo sobre algo.

1. QUANDO eu perguntar sobre novidades de uma obra, o Magui DEVE responder a partir das notícias guardadas, respeitando o anti-spoiler, e mostrar os links das fontes.
2. SE não houver notícia guardada relevante, ENTÃO o Magui DEVE pesquisar (Requisito 10).
3. QUANDO eu disser "Ei Magui, novidades?", o Magui DEVE resumir os itens de nível normal e alta ainda não vistos, no máximo 5.

## Requisito 21 — Provedores e chaves

**História:** como dono do projeto, quero trocar provedores e usar várias chaves sem mexer no código.

1. O Magui DEVE ler de configuração qual provedor e modelo atende cada tarefa (transcrição, voz, agente, visão, embeddings, pesquisa, notícias).
2. O Magui DEVE aceitar várias chaves por provedor e usá-las em rodízio.
3. QUANDO uma chave retornar limite de uso ou erro de autenticação, o Magui DEVE passar para a próxima chave e marcar a anterior como indisponível por um tempo.
4. O Magui DEVE guardar as chaves no chaveiro do sistema, nunca em arquivo de texto puro.
5. O Magui NÃO DEVE enviar memória pessoal, voz, humor ou capturas para provedores em cota gratuita.

## Requisito 22 — Satélites de voz (preparação)

**História:** como dono do projeto, quero poder adicionar uma caixinha com Raspberry Pi depois sem refazer o núcleo.

1. O núcleo NÃO DEVE acessar dispositivos de áudio diretamente; DEVE receber áudio e devolver fala por um protocolo de satélite em rede local.
2. O satélite do PC DEVE ser um processo separado que fala esse protocolo.
3. O Magui DEVE registrar de qual satélite veio cada turno e responder no mesmo satélite.

## Requisito 23 — Interface "wired" do MAGI (redesign)

**História:** como usuário, quero o MAGI com o visual "wired" (fios, postes, scanlines, kanji) do handoff `docs/design/MAGI-HANDOFF.md`, sem perder nenhum dado que o painel já mostra.

1. O MAGI DEVE desenhar duas telas, Painel completo e Tela de espera, seguindo o layout, os tokens de cor e as fontes do handoff, numa grade lógica de 1920×1080 escalada para o monitor (2560×1440 = 4/3).
2. O MAGI DEVE manter as fontes de dados atuais (CPU, GPU, RAM, VRAM, FPS, controles, specs) e acrescentar rede (↓/↑), histórico de carga de 60 min, FPS mín/méd/máx e o Spotify em reprodução.
3. Quando um dado não existir, o MAGI DEVE mostrar "– –" ou um estado vazio; NÃO DEVE mostrar dado simulado.
4. O mascote do handoff DEVE substituir o rosto de caracteres do R17, mantendo as 7 expressões, a boca "—"/"o"/"O" pelo volume da voz, as piscadas e a legenda da fala (R17.1–R17.6 continuam valendo sobre o novo desenho).
5. O "Now playing" DEVE ler faixa, artista, álbum, capa, posição e estado pelo MPRIS do Spotify (sem Premium) e oferecer anterior/tocar-pausar/próxima; "a seguir" só aparece se houver fonte real.
6. O botão LED DEVE ligar/desligar o RGB Sync existente, persistir o estado e, ligado, tingir as 3 unidades MAGI, o ponto do botão, o rubor do mascote e o trilho da tela de espera com a cor atual do OpenRGB; se o OpenRGB não responder, volta a "off" visualmente com aviso no log.
7. Os controles clicáveis DEVEM ter área mínima de 44 px (lógicos) e a cor NUNCA DEVE ser a única informação (ex.: 正常 sempre com "NORMAL").
8. O redesenho NÃO DEVE usar GPU nem passar do consumo de CPU do painel atual (meta ≤ 10% de um núcleo no Painel completo, ≤ 3% na Tela de espera).
9. O tema antigo (Evangelion) DEVE continuar disponível por configuração até o novo ser aprovado em uso.

---

## Requisitos não funcionais

| ID | Requisito | Meta |
| --- | --- | --- |
| RNF-01 | CPU com a Magui dormindo | até 2% de um núcleo |
| RNF-02 | RAM dormindo (satélite + núcleo + Postgres) | até 300 MB |
| RNF-03 | GPU | nenhum modelo local na GPU |
| RNF-04 | Comando conhecido: fim da fala → ação | até 1,5 s (p90) |
| RNF-05 | Pergunta: fim da fala → início da voz | até 3 s; até 5 s com visão ou pesquisa (p90) |
| RNF-06 | Falsos disparos de "Ei Magui" | até 1 por hora de jogo |
| RNF-07 | Acerto em comandos conhecidos | 95% ou mais após 2 semanas de uso |
| RNF-08 | Prompt fixo por chamada ao agente | até 1.500 tokens |
| RNF-09 | Gasto mensal | dentro do teto |
| RNF-10 | Privacidade | áudio só após ativação; nada de áudio em disco; capturas só sob pedido e apagadas; memória e histórico só locais |
| RNF-11 | Confiabilidade | serviços do usuário com reinício automático; sem internet, aviso por frase em cache |
| RNF-12 | Impacto em jogo | nenhuma queda de FPS mensurável com a Magui dormindo |
