# PRD — MAGI: assistente de voz (MVP)

Oct 1, 2026 · Projeto: gamerhud (MAGI Gamer)

> Cópia da revisão 34 do doc. A fonte da verdade é o doc editável:
> https://claude.ai/code/artifact/5504dd26-a040-4fda-9931-590a2883e45f
> Os diagramas estão desenhados no doc; aqui aparecem como texto.

## Visão

O Magui (escrito MAGI, pronuncia-se "Magui") é uma assistente de IA especializada em cultura pop, principalmente games, anime e cultura japonesa. Fala com voz feminina natural, jeito casual e amistoso, sem papas na língua. Vive dentro do MAGI Gamer: dorme custando cerca de 1% de um núcleo, acorda com "Ei Magui" ou um atalho, faz ações simples no PC e me ajuda no que estou jogando, olhando a tela quando precisa.

**Problema.** Hoje, trocar a música, abrir ou fechar um jogo ou pesquisar algo sobre o jogo exige sair dele. Assistentes comerciais não controlam Steam, OpenRGB nem o MAGI no Linux, e não entendem minha fala às vezes enrolada.

**Princípios**

- **Ociosidade mínima:** só o detector de "Ei Magui" roda sempre, local e sem rede. Todo o resto acorda sob demanda.
- **Token só quando precisa:** comandos conhecidos são resolvidos localmente, sem LLM.
- **Aprende sem inflar o prompt:** o prompt tem tamanho fixo; o que cresce é a memória, e dela entram só os trechos relevantes.
- **Privado por padrão:** áudio só sai do PC depois de "Ei Magui"; a tela só é capturada quando eu peço.

## Objetivos e fora de escopo

O MVP cobre tudo o que foi discutido, cada parte na versão mais enxuta que já seja útil no dia a dia.

**Objetivos do MVP**

- Comandos de voz para jogos, Spotify, MAGI, RGB e volume, por "Ei Magui" ou atalho.
- Perguntas gerais e sobre a tela (janela ativa; tela inteira quando eu disser "a tela"), com resposta falada curta e texto completo no MAGI.
- Spotify: controlar, tocar algo específico e "coloca uma boa" com gosto aprendido.
- Aprendizado contínuo nos dois sentidos: entender melhor minha fala e falar do meu jeito.
- Proatividade leve: alertas críticos e, às vezes, sugestão de música ao abrir um jogo.
- Gasto com a OpenAI abaixo de um teto mensal ajustável, US$ 5 por padrão.
- Notícias de anime e games: coletadas sozinhas, verificadas, sem spoiler e priorizadas pelo meu gosto, com aviso proativo só para o que for muito grande.

**Fora de escopo do MVP**

- Funcionar offline: precisão vem antes.
- Treinar ou ajustar modelos (fine-tuning) de voz ou de linguagem.
- Automação genérica de interface (clicar em botões de outros apps).
- Mais de um PC ou sincronização na nuvem (Supabase fica para depois).
- Conversa contínua por voz em tempo real: cada interação é pergunta e resposta.
- Aparelho físico tipo Alexa (caixinha própria com Raspberry Pi, microfone e alto-falante pela casa): fica para depois, mas a arquitetura já prevê.

## Cenários de uso

Um único usuário, eu, jogando no Nobara com headset, Discord aberto e o MAGI no monitor de cima. Estes cenários definem o "pronto" do MVP.

| Cenário | Eu falo | O que acontece |
| --- | --- | --- |
| Comando no meio do jogo | "Ei Magui, pausa a música" | Bip curto, música pausa. Nenhuma fala, zero token. |
| Abrir jogo falando enrolado | "Ei Magui, abre o dedi cels" | Entende Dead Cells por aproximação e memória de correções, diz "Abrindo Dead Cells" (áudio em cache) e abre pela Steam. |
| Pergunta sobre a tela | "Ei Magui, que bicho é esse?" | Captura a janela ativa, responde em 1–2 frases faladas e põe o detalhe no MAGI. |
| Tela inteira | "Ei Magui, olha a tela, o que é isso no canto?" | Captura o monitor principal inteiro em vez da janela. |
| Ação perigosa | "Ei Magui, fecha o jogo" | Pergunta "Fechar Dead Cells? Diz confirma" e só fecha com a confirmação. |
| Música pelo gosto | "Ei Magui, coloca uma boa" | Escolhe pelo meu gosto e pelo momento, diz o que colocou. Se eu pular em menos de 30 s, registra. |
| Correção | "Não, eu falei X" | Corrige agora e salva o par ouvido→certo pra não errar de novo. |
| Em call no Discord | Seguro o atalho e falo | "Ei Magui" fica desligado em call; enquanto seguro o atalho, meu microfone é mutado só para o Discord. |
| Alerta | (nada) | "GPU em 95 graus" ou "controle com 10% de bateria", falado e na tela. |

## Comportamento

Ele passa quase todo o tempo dormindo. Acorda com "Ei Magui" ou com o atalho, ouve, decide, responde e volta a dormir, e cada estado aparece na tela do MAGI.

> Diagrama (estados): Dormindo → (Ei Magui ou atalho) → Ouvindo → (fim da fala) → Pensando → (decidiu) → Respondendo → volta a dormir. De Pensando, uma ação perigosa passa por Confirmação ("eu digo confirma", MAGI vota 承認/否決) antes de Respondendo.

Só ações perigosas passam pela confirmação; todo o resto vai direto de pensar para responder.

**Como ele fala comigo:** voz feminina (TTS da OpenAI) no headset e legenda estilo Evangelion no MAGI. Enquanto ele fala, música e jogo abaixam e depois voltam.

| Situação | Voz | Tela do MAGI |
| --- | --- | --- |
| Comando simples | Bip ou 1–2 palavras de áudio pré-gerado, instantâneo e sem custo | Confirmação curta |
| Pergunta | 1–2 frases | Resposta completa e links |
| Ação perigosa | Pergunta antes de agir | MELCHIOR, BALTHASAR e CASPER "votam" 承認 / 否決 |
| Não entendeu | "Não peguei, repete?" | O que ele ouviu |
| Em call no Discord | Só se eu chamar pelo atalho | Normal |

**Persona:** amiga gamer que entende muito de cultura pop. Casual e amistosa, mas não passa pano: se eu falo besteira ou vou fazer algo ruim, ela diz.

| Traço | Como aparece | Exemplo |
| --- | --- | --- |
| Especialista em cultura pop | Games, anime e cultura japonesa primeiro: lore, builds, temporadas, estúdios, dubladores. Fora disso responde normal, sem fingir especialidade, e pesquisa quando precisa. | "Esse é do Trigger, mesmo estúdio de Kill la Kill." |
| Casual e amistosa | Fala como amiga, com gírias e respostas curtas. Pega minhas gírias com o tempo. | "Bora, abrindo." |
| Sem papas na língua | Discorda e corrige quando eu erro um fato ou tomo uma decisão ruim. Normalmente zoeira leve; pega pesado quando eu insisto no erro, calibrada pelo termômetro de humor. | "Não, Evangelion não é isekai, né." |
| Ajuda sem estragar | Ajuda no jogo em degraus (pista, dica direta, solução), a não ser que eu peça a solução direto. Lembra o que já pedi e há quanto tempo estou travado na mesma parte, e começa do degrau certo. | "Quer só uma pista ou a resposta?" |
| Honesta | Quando não sabe, diz e pesquisa; nunca inventa. | "Não sei de cabeça, vou ver." |

**Termômetro de humor.** O Magui estima meu humor do momento e calibra por ele a intensidade da zoeira e o tamanho das respostas.

- **Sinais:** o que eu falo e como falo (tom e volume da voz, palavrão, frases curtas), o contexto do jogo (muito tempo travado, pedidos repetidos), o horário e como reagi às últimas zoeiras.
- **Escala:** de "pega leve" a "pode zoar pesado". Frustrado ou cansado, ela fica mais leve e mais objetiva; de boa, zoa mais.
- **Eu mando:** "pega leve" ou "pode pegar pesado" muda na hora e vira aprendizado.
- **Na tela:** um termômetro discreto ao lado do rosto no MAGI.
- **Privacidade:** o tom da voz é medido localmente; o humor só sai do PC como parte do contexto de uma pergunta.

**Ajuda no jogo com contexto.** Ela guarda, por jogo, o que eu já pedi e quando. Se já dei pista antes da mesma parte, começa da dica direta; "manda a solução" pula direto. "Travado há tempo" vem de pedidos repetidos, tempo de sessão e conquistas paradas na Steam, sem vigiar a tela.

- RF-35: termômetro de humor calibra a zoeira e o tamanho das respostas; "pega leve" e "pode pegar pesado" ajustam na hora.
- RF-36: ajuda no jogo com histórico por jogo e trecho, começando do degrau certo.

Enquanto pensa, mostra os três MAGI "deliberando".

**Proatividade:** fala sem ser chamado só em dois casos.

- Alertas críticos: temperatura de CPU ou GPU em perigo, bateria do controle em 15% ou menos, gasto com a OpenAI em 80% e em 100% do teto.
- Sugestão de música ao abrir um jogo, às vezes, conforme o gênero: em jogos casuais (plataforma, futebol, corrida) pode sugerir com mais frequência; em jogos imersivos (exploração, RPG) ou competitivos, nenhuma sugestão. Com o Spotify tocando, pode sugerir ainda mais, de preferência na troca de música. Em call no Discord, alertas aparecem só na tela.

## Interface: o rosto do Magui

O Magui tem um rosto anime feminino feito só de caracteres, no estilo kaomoji: olhos, bochechas coradas e uma boca que fala em — o O. Ele vive na tela do MAGI e muda de expressão conforme o estado.

> Mock (6 expressões): Dormindo `— —` boca `‿` "z z" · Ouvindo `◉ ◉` boca `—` · Pensando `◔ ◔` boca `~` "· · ·" · Falando `◕ ◕` boca `— / o / O` · Feliz `^ ^` boca `‿` · Confusa `• •` boca `_` "?". Bochechas `//` na cor do tema.

A boca segue o volume da voz em tempo real: silêncio é —, voz baixa é o, voz alta é O.

- **Onde aparece:** na tela de ociosidade ocupa a metade direita, ao lado do relógio; no painel completo vira um rosto pequeno no cabeçalho. Nunca aparece no monitor do jogo.
- **Legenda:** o que ela fala aparece embaixo do rosto, em mincho branco, estilo Evangelion.
- **Animação:** pisca, olha para os lados e troca de expressão com transição suave. Dormindo fica quase parada, pra manter a ociosidade mínima.
- **Cor:** rosto branco; bochechas e detalhes na cor do tema (RGB da placa-mãe).

**Requisitos da interface**

- RF-24: expressão por estado: dormindo, ouvindo, pensando, falando, feliz, confusa e alerta (olhos arregalados).
- RF-25: boca sincronizada com o áudio da voz, em três formas: —, o e O.
- RF-26: microanimações: piscar, olhar de lado, transição entre expressões.
- RF-27: animação a até 30 fps só acordada; dormindo, no máximo um piscar lento a cada alguns segundos.

## Notícias de anime e games

O Magui coleta notícias de anime e games sozinho, guarda tudo na memória para responder perguntas (RAG) e só me avisa do que é confiável, sem spoiler e importante pra mim. Uma notícia como "Black Bullet volta depois de 10 anos" vira aviso falado; o resto espera eu perguntar.

> Diagrama (fluxo): Coleta (RSS, APIs e scraping leve, a cada 2 h) → Agrupar (mesma notícia em vários sites vira uma só) → Verificar (confiança da fonte, confirmada por 2 fontes?) → Anti-spoiler (usa meu progresso, reescreve a manchete) → Prioridade (meu gosto + tamanho da notícia + confiança + novidade) → Entrega (fala, card ou resumo). Meu retorno → Aprendizado (curti, não curti, ignorei, deu spoiler, larguei a obra) → ajusta pesos da Prioridade.

O que eu curto, ignoro ou marco como spoiler ajusta os pesos da prioridade; uma obra que larguei nunca mais aparece.

**Fontes** (preferir feed e API; scraping só onde não houver)

| Tipo | Exemplos | Como |
| --- | --- | --- |
| Jogos da minha biblioteca | Notícias oficiais de cada jogo que eu tenho | API de notícias da Steam |
| Sites de games | IGN, PC Gamer, Gematsu | RSS |
| Sites de anime | Anime News Network, Crunchyroll News | RSS |
| Calendário de anime | Temporadas, sequências, datas | API do AniList |
| Comunidade | r/anime, r/Games | API do Reddit, peso baixo, vale como rumor |
| Sites sem feed | A definir | Scraping leve, respeitando robots.txt e limites de acesso |

**Níveis de prioridade**

| Nível | Exemplo | Como chega |
| --- | --- | --- |
| Bomba | Sequência de obra que eu curto anunciada depois de anos | Fala na hora, fora de call; jogando, frase curta e card no MAGI |
| Alta | Data de lançamento, trailer, temporada nova do que acompanho | Card no MAGI, sem voz |
| Normal | Notícias gerais dos meus gostos | Só quando eu pedir "Ei Magui, novidades?" |
| Guardada | Rumor sem confirmação, tema que não curto | Não aparece; fica na memória e sobe se outra fonte confirmar |

**Regras**

- **Fonte:** cada fonte tem um nível de confiança. "Bomba" exige confirmação por pelo menos 2 fontes; rumor vem sempre marcado como rumor.
- **Spoiler:** por padrão, nada de spoiler. O Magui sabe até onde eu vi ou joguei (lista de anime e tempo de jogo na Steam) e reescreve manchetes que entregam a história. "Pode dar spoiler de X" libera só aquela obra.
- **Gosto:** começa pelos jogos mais jogados e pela minha lista de anime. "Não curti" e ignorar o mesmo tema 3 vezes baixam o peso; "mais disso" sobe.
- **Custo e carga:** coleta de cerca de 1 minuto a cada 2 h, só com o PC ligado; agrupamento, classificação, anti-spoiler e prioridade em lote no Gemini (cota gratuita), sem gastar o teto da OpenAI. Se a cota acabar, espera a próxima janela.

**Requisitos das notícias**

- RF-28: coleta agendada de feeds e APIs; scraping só onde não houver feed.
- RF-29: a mesma notícia em vários sites vira um item só.
- RF-30: nível de confiança por fonte e confirmação por 2 fontes para "bomba".
- RF-31: anti-spoiler pelo meu progresso, com manchete reescrita.
- RF-32: nota de prioridade aprendida, entregue em 4 níveis.
- RF-33: perguntas como "o que saiu de novo do Silksong?" respondidas com as notícias guardadas e os links das fontes.
- RF-34: aprendizado pelo meu retorno; obra largada nunca mais aparece.

## Requisitos funcionais

Vinte e três requisitos em dez módulos. Tudo aqui entra no MVP, na versão mais simples que funcione.

| ID | Módulo | Requisito |
| --- | --- | --- |
| RF-01 | Ativação | "Ei Magui" detectado localmente, sempre ligado fora de call, treinado com amostras da minha voz. |
| RF-02 | Ativação | Atalho de apertar pra falar no teclado e, se possível, num botão do DualSense. |
| RF-03 | Discord | Detecta quando estou em call e desliga o "Ei Magui" enquanto durar. |
| RF-04 | Discord | Enquanto seguro o atalho, meu microfone fica mudo só para o Discord. |
| RF-05 | Transcrição | Fala vira texto pela API da OpenAI, com dica de vocabulário: jogos da biblioteca, minhas gírias e correções salvas. |
| RF-06 | Transcrição | "Não, eu falei X" salva o par ouvido→certo, aplicado nas próximas vezes antes de decidir a ação. |
| RF-07 | Roteador | Comandos conhecidos resolvidos localmente por correspondência aproximada, sem LLM. |
| RF-08 | Jogos | Abrir qualquer jogo instalado na Steam pelo nome; fechar o jogo atual com confirmação. |
| RF-09 | MAGI | Abrir e fechar o MAGI, alternar a tela de ociosidade, abrir os detalhes de CPU, GPU ou memória, ligar e desligar o RGB Sync. |
| RF-10 | Sistema | Volume, mudo, cor e brilho do RGB pelo OpenRGB. |
| RF-11 | Spotify | Abrir o app; tocar, pausar, próxima, anterior e volume (MPRIS local). |
| RF-12 | Spotify | Tocar música, artista, álbum ou playlist pelo nome. |
| RF-13 | Spotify | "Coloca uma boa": escolhe pelo perfil de gosto e pelo contexto (horário, jogo aberto, pedido). |
| RF-14 | Spotify | Aprende o gosto: importa mais ouvidos e recentes, registra pulos (menos de 30 s) e músicas ouvidas inteiras, aceita "essa é boa" e "nunca mais". |
| RF-15 | Visão | Captura a janela ativa por padrão e o monitor principal inteiro quando eu disser "a tela". Só sob pedido. |
| RF-16 | Pesquisa | Busca na web quando a pergunta precisar (Gemini com busca do Google), com o link no MAGI. |
| RF-17 | Memória | Perfil compacto de tamanho fixo mais memórias buscadas por similaridade (pgvector) em cada pergunta. |
| RF-18 | Memória | Aprende como eu falo (gírias, formalidade, tamanho de resposta) e passa a responder assim. |
| RF-19 | Memória | "Esquece isso" apaga a memória correspondente; histórico local para revisar. |
| RF-20 | Resposta | Voz feminina e legenda no MAGI; frases curtas comuns pré-geradas e em cache. |
| RF-21 | Segurança | Confirmação falada para ações perigosas: fechar jogo, desligar ou reiniciar o PC. |
| RF-22 | Proatividade | Alertas críticos e sugestão ocasional de música ao abrir jogo (ver Comportamento). |
| RF-23 | Custo | Conta o gasto do mês; teto de US$ 5 ajustável por voz e por configuração; aviso em 80%; em 100% param perguntas, visão e pesquisa; transcrição e comandos locais continuam. |

## Requisitos não funcionais

As metas abaixo são propostas para validar no MVP. A principal: dormindo, ele não pode ser notado no jogo.

| Requisito | Meta |
| --- | --- |
| CPU dormindo | até 2% de um núcleo |
| RAM dormindo (assistente + Postgres) | até 300 MB |
| GPU | zero: nada de modelo local na GPU |
| Comando conhecido (fim da fala → ação) | até 1,5 s |
| Pergunta (fim da fala → começo da voz) | até 3 s; até 5 s com visão ou pesquisa |
| Falsos disparos de "Ei Magui" | até 1 por hora de jogo |
| Comandos conhecidos acertados | 95% ou mais após 2 semanas de uso |
| Prompt fixo por pergunta | até 1.500 tokens, sem crescer com o tempo |
| Gasto mensal | até o teto (US$ 5 por padrão, ajustável) |

**Privacidade**

- Áudio só é enviado depois de "Ei Magui" ou do atalho; nenhum áudio gravado em disco.
- Prints só sob pedido, apagados depois do envio.
- Histórico e memória ficam só no PC.
- Chaves da OpenAI e do Spotify no chaveiro do sistema, nunca em texto puro.

**Confiabilidade:** o assistente roda como serviço do usuário e reinicia sozinho se cair. Sem internet, avisa com uma frase em cache em vez de ficar mudo.

## Arquitetura

> Diagrama (arquitetura): Microfone (headset) → Ei Magui (local, ~1% de CPU) → Transcrição (OpenAI + vocabulário) → Roteador (correções e comandos). Comando conhecido → Comando local (sem LLM, zero token). Pergunta ou desconhecido → Agente LangChain + OpenAI (decide e chama ferramentas, busca memórias e respeita o teto) ↔ Memória (Postgres + pgvector, Docker local). Ambos → Ações e ferramentas (Steam · Spotify (MPRIS + Web API) · MAGI · OpenRGB · PipeWire (volume, Discord) · visão (print) · pesquisa web) → Voz no headset (feminina, frases em cache) e Tela do MAGI (legenda estilo Eva e estados).

Comandos conhecidos seguem pela direita, sem LLM e sem custo. Só perguntas passam pelo agente, que consulta a memória e o teto de gasto antes de chamar a OpenAI. O assistente roda como serviço próprio e conversa com o MAGI Gamer por um canal local.

| Peça | Tecnologia proposta |
| --- | --- |
| Detector "Ei Magui" | openWakeWord, modelo treinado com amostras da minha voz |
| Fim da fala | Detector de voz local (VAD) |
| Transcrição e voz | API de áudio da OpenAI, voz feminina, frases curtas em cache |
| Agente | LangChain (LangGraph) com ferramentas e LLM da OpenAI |
| Memória | Postgres + pgvector em Docker, embeddings da OpenAI |
| Spotify | MPRIS via D-Bus para controle; Web API para busca e gosto |
| Áudio do sistema | PipeWire: volume, abaixar música e jogo, mudo só para o Discord |
| Serviço | systemd do usuário, reinicia sozinho |

**Preparado para um aparelho tipo Alexa.** Desde a fase 1, o áudio fica separado do cérebro: o núcleo nunca acessa microfone nem alto-falante diretamente, só recebe áudio e devolve fala por um protocolo de rede local. O headset do PC é apenas o primeiro "satélite". Depois, uma caixinha própria com Raspberry Pi, microfone e alto-falante entra como mais um satélite, sem mudar o resto. Alexa da Amazon não entra.

- Protocolo candidato: Wyoming, o dos satélites de voz do Home Assistant, que já tem satélite pronto para Raspberry Pi.
- Cada satélite informa de onde fala (PC, sala, quarto) e o Magui responde no mesmo lugar.
- Ações do PC valem de qualquer satélite: "Ei Magui, abre o Dead Cells" dito na sala.

**Modelos e chaves por tarefa.** Cada tarefa usa o provedor que faz mais sentido; trocar é configuração, não código (LangChain). O papel do Gemini é experimental: resumos de pesquisa fora da especialidade e classificação de notícias, com um prompt fixo e poucos exemplos tirados do meu retorno. Se não render nos testes, a tarefa volta para a OpenAI.

| Tarefa | Provedor | Por quê |
| --- | --- | --- |
| Comandos conhecidos | Nenhum, local | Custo zero |
| Transcrição e voz | OpenAI | Precisão em português e voz natural |
| Agente, perguntas e visão | OpenAI | Qualidade; dentro do teto mensal |
| Memória pessoal (embeddings) | OpenAI | Dados pessoais não vão para cota gratuita |
| Notícias: agrupar, classificar, spoiler, prioridade | Gemini, cota gratuita | Volume alto e só dados públicos |

- **Várias chaves por provedor**, em rodízio: quando uma bate o limite ou falha, passa para a próxima. Ficam no chaveiro do sistema.
- No Gemini, a cota gratuita é por projeto do Google Cloud, não por chave: chaves do mesmo projeto dividem o limite.
- Na cota gratuita, o Google pode usar o que for enviado para melhorar os produtos dele. Por isso só vão notícias públicas, nunca memória, voz ou prints.
- **Pesquisa na web:** Gemini com busca do Google, na cota gratuita enquanto houver. Vai só a pergunta reescrita, sem memória, humor ou prints.

## Riscos e mitigações

Os dois maiores riscos são o "Ei Magui" disparar sozinho e a transcrição errar minha fala; os dois têm mitigação desde a fase 1.

| Risco | Mitigação |
| --- | --- |
| "Ei Magui" dispara sozinho (som do jogo, amigos no Discord) | Detector treinado com a minha voz, limiar ajustável, desligado em call, atalho como alternativa. |
| Transcrição erra minha fala enrolada | Vocabulário de dica, memória de correções e "você quis dizer X?" quando houver dúvida. |
| Gasto passa do teto | Roteador local para comandos, modelos pequenos por padrão, áudio em cache, teto que bloqueia o LLM. |
| Spotify limita a API: sem recomendações para apps novos; controle pela API exige Premium | Controle pelo MPRIS local; gosto calculado por nós com os dados ainda liberados. |
| Amigos ouvem "Ei Magui" no Discord | Em call só o atalho, que muta meu microfone apenas para o Discord. |
| Prints com informação sensível | Só sob pedido, janela ativa por padrão, apagados após o envio. |
| Resposta lenta | Fala e transcrição em streaming, frases em cache, modelo pequeno quando basta. |
| LangChain deixa o projeto pesado | Usar só o núcleo e o agente (LangGraph); roteador local e áudio ficam fora dele. |
| Memória aprende algo errado | "Esquece isso" e revisão do histórico de memórias. |

## Decisões e questões em aberto

Quatorze decisões tomadas na conversa; seis pontos ainda abertos, nenhum bloqueia começar a fase 1.

| Tema | Decisão |
| --- | --- |
| Ativação | Os dois: "Ei Magui" e atalho de apertar pra falar |
| Transcrição | API da OpenAI: precisão acima de funcionar offline |
| Microfone | Headset, com Discord aberto |
| Discord | Em call: só atalho, que muta meu microfone para o Discord |
| LLM | OpenAI na voz, no agente e na visão; Gemini (cota gratuita) nas notícias; várias chaves por provedor |
| Orquestração | LangChain |
| Memória | Postgres + pgvector em Docker local |
| Ações perigosas | Pede confirmação |
| Visão | Janela ativa; tela inteira quando eu disser "a tela" |
| Teto de gasto | US$ 5/mês, ajustável |
| Aprendizado | Os dois: entender minha fala e falar do meu jeito |
| Voz | Feminina |
| Proatividade | Alertas críticos e sugestão de música ao abrir jogo conforme o gênero (mais em casuais, nenhuma em imersivos ou competitivos) |
| Escopo | Tudo o que foi discutido, em versão MVP |

**Em aberto**

- [ ] Tenho Spotify Premium? Define se o controle pode ir também pela API.
- [ ] Qual tecla ou botão do DualSense para apertar pra falar?
- [ ] Frequência da sugestão de música: resolvido, depende do gênero do jogo (ver Comportamento).
- [ ] Qual voz feminina da OpenAI: escolher ouvindo amostras.
- [ ] Gravar cerca de 50 amostras de "Ei Magui" para treinar o detector.
- [ ] Criar o app de desenvolvedor no Spotify e autorizar minha conta.
- [ ] Uso AniList ou MyAnimeList? Serve para saber o que acompanho e até onde vi (anti-spoiler).

## Métricas e fases

O MVP está pronto quando eu uso o Magui todo dia sem pensar nele: nunca atrapalha o jogo, entende o que eu falo e cabe no teto.

**Métricas de sucesso**

- Uso: pelo menos 5 interações por dia de jogo, depois de 2 semanas.
- Entendimento: 95% dos comandos conhecidos certos e menos de 1 correção a cada 20 interações.
- Música: menos de 1 pulo a cada 4 músicas escolhidas por "coloca uma boa".
- Custo: mês fechado abaixo do teto.
- Imperceptível: nenhuma queda de FPS medida com ele dormindo.

**Fases do MVP** (cada uma já útil sozinha)

1. **Base de voz:** serviço do assistente, "Ei Magui" e atalho, transcrição, roteador local, comandos de jogos, MAGI e sistema, voz em cache, rosto e legenda no MAGI.
2. **Spotify:** controle local, tocar pelo nome, importar o gosto, registrar pulos.
3. **Agente:** LangChain com perguntas, pesquisa, visão e teto de gasto.
4. **Memória:** pgvector, correções, perfil compacto, estilo de fala, "coloca uma boa".
5. **Proatividade e Discord:** alertas, sugestão de música, detecção de call e mudo só para o Discord.
6. **Notícias:** coleta agendada, agrupamento, verificação, anti-spoiler, prioridade e avisos.

**Depois do MVP:** sincronizar memória (Supabase), transcrição local de reserva para ficar offline, conversa contínua por voz, mais apps, caixinha com Raspberry Pi como satélite de voz.
