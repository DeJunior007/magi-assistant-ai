# Brainstorm 4 — Condessa mais esperta, proativa e presente (2026-10-28)

Lente: **o que a Ayanami no node 2 pode fazer, em lote ou assíncrono, para a Condessa ficar mais
esperta, proativa e presente na vida do Pedro.** Coisa que hoje pesa no PC ou que só faz sentido com
um servidor sempre ligado. Base: `brainstorm/contexto.md`, `persona/condessa.md`,
`docs/PROXIMOS-PASSOS.md` §13–§15 e os SDDs learning-mode, learning-imersivo, audiolivro, espera-viva,
condessa-engine, fifa-lances e condessa-vida. Sem código: só ideias para virar SDD.

## Premissas de recurso e custo

- **Node 2:** 8 vCPU, 23 GiB, 221 GB livres, sem GPU. Com o Minecraft fora, a janela **00h–07h** fica
  livre para lote pesado (a vigia limita a ~6 vCPU para o SSH e a API continuarem respondendo).
- **LLM local em CPU (reabre a D8 → (b) "só lote noturno"):** pelos benchmarks públicos, um 7B Q4_K_M
  gera ~4–8 tok/s em 4–8 vCPU (a Ayanami estimou 45–140 s por chamada, 5–8 GB). Um **Qwen 3B/4B Q4**
  deve dar ~10–15 tok/s em ~3 GB. Em 6 h de madrugada a 5 tok/s são ~100k tokens gerados: sobra para
  resumos, marcação de livro e filtro de spoiler. **A medir no Y0.8** (`llama-bench -t 6`).
- **API paga (budget total US$ 5/mês; modo nuvem já tem sub-teto de US$ 2):** proposta de
  **sub-teto "lote" de US$ 1/mês**. Referências (agregadores, conferir na página do Google): Gemini
  Flash-Lite ~US$ 0,10–0,25 por 1M de entrada e US$ 0,40–1,50 por 1M de saída, **batch com 50% de
  desconto**; o `search` já usa a cota gratuita do Gemini Flash com Google Search. Regra prática:
  resumir 1M de tokens de entrada por mês em batch custa **~US$ 0,10–0,15**. Tudo que for privado ou
  volumoso vai primeiro para o modelo local; a API fica para qualidade quando o local não dá conta.
- **Kokoro em CPU:** já roda no node 2; o 82M deve passar de 3× tempo real em 6 vCPU (a medir no
  Y0.8). Opus a 32 kbps ≈ 14 MB por hora de áudio.
- **Claude Code (Engine):** roda na **assinatura** do Pedro (condessa-engine R6), custo de API zero;
  o limite é a janela de 5 h da assinatura.
- **Princípio da persona:** tudo que ela faz sozinha precisa de **causa registrada** ("dá para dizer
  por que ela fez isso agora?") e não pode virar spam: proatividade entra no teto de cenas (≤ 8/h) e
  nunca no meio de jogo (exceto o que for do jogo).

## Ranking (valor ÷ esforço)

★ = as 5 melhores. Esforço: P (≤ 1 semana de agente), M (2–3 semanas), G (mais que isso / depende do Pedro).

| # | Ideia | Valor | Esforço | API/mês | Cabe? |
| --- | --- | --- | --- | --- | --- |
| 1 ★ | Bom dia da Condessa (briefing pré-renderizado) | alto | P | ~US$ 0,05 | sim |
| 2 ★ | Diário da Condessa (resumo diário/semanal das conversas) | alto | P | US$ 0–0,15 | sim |
| 3 ★ | Aula do dia (Learning Mode revisa os erros da véspera) | alto | P | US$ 0–0,10 | sim |
| 4 ★ | Pesquisa enquanto ele dorme | alto | P | ~US$ 0 (cota grátis) | sim |
| 5 ★ | Audiolivro renderizado de madrugada | alto | M | US$ 0 | sim |
| 6 | Radar anti-spoiler (anime, jogos, Ado & cia.) | alto | M | US$ 0–0,05 | sim |
| 7 | Caderno de fatos ("lembra que…") com confirmação | alto | M | US$ 0–0,10 | sim |
| 8 | Banco de frases pré-renderizadas | médio | P | US$ 0 | sim |
| 9 | Lembrete que escolhe a hora (fora da partida) | médio | P | US$ 0 | sim |
| 10 | Relatório semanal de jogo (Steam, FIFA, FPS) | médio | P | US$ 0 | sim |
| 11 | Domingo da Condessa (retrospectiva semanal em áudio) | médio | P | ~US$ 0,02 | sim |
| 12 | Pauta automática do Conselho (log de reações) | médio | P | US$ 0 | sim |
| 13 | Saúde do PC preditiva (SMART, updates, temperaturas) | médio | P | US$ 0 | sim |
| 14 | Monitor de preços com memória (wishlist Steam + hardware) | médio | P | US$ 0 | sim |
| 15 | Sono e ritmo pelo uso do PC | médio | P | US$ 0 | sim |
| 16 | Favorita do Dia com dossiê (créditos, "tese ou fórmula") | médio | P | US$ 0 | sim |
| 17 | Vigia do node 1 só leitura, contada pela Condessa | médio | M | US$ 0 | sim |
| 18 | Briefing de projeto ao abrir o editor | médio | M | US$ 0–0,05 | sim |
| 19 | Revisor noturno de repositórios (Engine leve, só propõe) | médio | M | US$ 0 (assinatura) | sim |
| 20 | Caça-vagas + entrevista pronta | médio | M | ~US$ 0,05 | sim |
| 21 | "Onde eu vi aquilo?" (busca semântica pessoal) | médio | M | US$ 0 | sim |
| 22 | "Assiste por mim" (transcrever e resumir vídeo/podcast) | médio | M | US$ 0–0,10 | sim |
| 23 | Condessa Engine no node 2 com aprovação por voz | muito alto | G | US$ 0 (assinatura) | sim |

Soma pessimista de 1–22 juntos: **~US$ 0,80/mês** — cabe no sub-teto de US$ 1 e deixa os US$ 2 do modo
nuvem intactos. O que manda no custo é a escolha local × API nos itens 2, 3 e 7.

---

## As ideias

### 1 ★ Bom dia da Condessa
- **O que é:** às 6h a Ayanami monta o briefing do dia e já o **renderiza em Kokoro**; o PC (ou o
  celular, pela ponte de turno) só toca quando o Pedro aparece pela primeira vez.
- **Ela diz:** "Bom dia. 19 graus, chuva às 16h, leva o guarda-chuva se for sair. Duas notícias que
  importam, o servidor passou a noite limpo, e o placar ficou 3 × 2 para mim ontem. A aula de hoje
  tem cinco frases suas. Ah, e pesquisei aquilo do SSD: está no card." No HUD, um card com os itens.
- **Peças:** fila `agendada` (cron 6h), clima (Open-Meteo, grátis, sem chave), notícias já
  clusterizadas, vigia, placar (fecha às 4h), itens 3/4/9; texto montado por molde + 1 frase de humor
  do LLM; Kokoro; evento SSE "briefing pronto"; gatilho "primeira presença do dia" no PC.
- **Recursos:** segundos de CPU; ~1 MB de áudio/dia.
- **API:** 1 chamada curta/dia (~US$ 0,05/mês) ou zero com o Qwen local.
- **Privacidade:** tudo no tailnet; agenda só se o Pedro conectar (CalDAV/Google), opcional.
- **Esforço:** P. É a vitrine de todos os outros itens: começa aqui.

### 2 ★ Diário da Condessa
- **O que é:** toda madrugada (depois do fechamento das 4h) ela lê as conversas, os turnos do agente
  e os eventos do dia e escreve um **diário curto** em primeira pessoa (5–10 linhas) + um resumo
  factual (tópicos, decisões, pendências). No domingo, consolida a semana.
- **Ela diz/faz:** "Ontem você perguntou três vezes sobre o deploy da Ayanami. Quarta vez hoje,
  estou registrando." Passa a responder "o que a gente falou semana passada sobre X?" com o resumo,
  sem precisar do histórico inteiro no contexto (contexto menor = turno mais barato e rápido).
- **Peças:** tabela `diario` (dia, texto, tópicos, embeddings e5), job noturno, tool MCP
  `memoria.diario(dia|busca)`, entra no prompt como 1 linha de "ontem".
- **Recursos:** Qwen 3B local, ~15–30 min de CPU por noite; KB de disco.
- **API:** zero local; Flash-Lite batch ~30k tokens/dia de entrada ≈ US$ 0,10–0,15/mês.
- **Privacidade:** é o dado mais íntimo do projeto: **local por padrão**, API só com opt-in, nunca
  sai do Postgres do node 2 (que vai para o backup cifrado).
- **Esforço:** P (texto) → M quando alimentar o item 7.

### 3 ★ Aula do dia (Learning Mode)
- **O que é:** à noite a Ayanami lê as observações e correções da sessão de inglês (os
  `learning_observe`), agrupa os erros recorrentes e prepara a **aula do dia seguinte**: 5 frases dele
  para reescrever, 1 cenário de roleplay que força o erro mais comum, revisão espaçada (SM-2) do
  vocabulário que ele salvou. Sem "curso" (CTX-002): é material em cima do que **ele** falou.
- **Ela diz:** "Ontem você disse *I have 30 years* duas vezes. Hoje o cenário é uma consulta médica,
  e eu vou perguntar a sua idade. Prepare-se." Painel do learning abre já com os cards.
- **Peças:** job noturno sobre `learning` do Postgres do PC (sincronizado), fila SM-2, roteiro do
  roleplay (os 4 cenários existentes + parâmetros), card no HUD; áudio das frases-modelo em Kokoro
  `bf_isabella` pré-renderizado.
- **Recursos:** minutos de CPU; áudio de ~2 MB/dia.
- **API:** zero com o Qwen local (as correções já foram pagas no dia); gpt-5.4-mini só para o roteiro,
  ~US$ 0,10/mês.
- **Privacidade:** voz dele não sobe; só texto das sessões.
- **Esforço:** P (cards + roteiro) → M (SM-2 completo e painel).

### 4 ★ Pesquisa enquanto ele dorme
- **O que é:** "Condessa, pesquisa até amanhã qual SSD NVMe vale mais a pena até 500 reais" vira uma
  tarefa da fila `lenta` com prazo; a Ayanami busca em várias rodadas, lê as páginas, cruza, e
  entrega um relatório de 1 tela + 3 frases no bom dia.
- **Ela diz:** "Fiz o dever de casa: top 3, o primeiro ganha por preço por TB, o terceiro está aqui
  só porque você ia perguntar. Fontes no card. De nada."
- **Peças:** a tarefa longa `pesquisar` já existe; falta modo "profundo" (N rodadas, orçamento de
  chamadas por tarefa), fetch + extração local (trafilatura), relatório em Markdown no PWA/HUD,
  ligação com o item 1.
- **Recursos:** baixo (rede + parsing); o Qwen local pode resumir as páginas.
- **API:** busca no Gemini com Google Search na **cota gratuita**; fallback gpt-5.4-mini limitado a
  N chamadas/tarefa → ~US$ 0–0,10/mês com 1 pesquisa/dia.
- **Privacidade:** a consulta sai para o buscador (como hoje); o relatório fica no node 2.
- **Esforço:** P.

### 5 ★ Audiolivro renderizado de madrugada
- **O que é:** o pipeline do audiolivro (marcação por regras + Qwen, elenco Kokoro) roda **no node 2
  à noite**, sempre mantendo os **próximos 2 capítulos** prontos a partir do marcador. O PC deixa de
  sintetizar durante a leitura (some o problema da música voltando antes do fim) e o celular passa a
  ouvir o livro fora de casa.
- **Ela diz:** "O capítulo 7 está pronto, e o vilão tem a minha voz de propósito." No celular:
  "Continuo de onde você parou no PC?"
- **Peças:** worker `audiolivro` na fila lenta, EPUB enviado pelo PWA/HUD, armazenamento Opus por
  capítulo, marcador sincronizado PC↔celular (ponte de turno), streaming pelo `tailscale serve`.
- **Recursos:** livro de 300 páginas ≈ 10 h de áudio ≈ 3–4 h de CPU (6 vCPU) + Qwen para marcação
  (~1–2 noites); ~150 MB por livro (apagar livro terminado após 30 dias).
- **API:** zero (D1/D2 do audiolivro).
- **Privacidade:** EPUB pessoal fica no node 2 (backup cifrado).
- **Esforço:** M (código do PC já existe; precisa virar worker e ganhar o player do PWA).

### 6 Radar anti-spoiler
- **O que é:** monitores de lançamento para o que **ele e ela** acompanham: episódios de anime
  (AniList GraphQL, grátis), jogos (notícias da Steam por app id, wishlist), música (MusicBrainz:
  Ado, Kenshi Yonezu, Laufey, Lady Gaga). Um filtro local reescreve títulos e chamadas **sem spoiler**
  ("episódio 9 saiu" e não "episódio 9: a morte de X").
- **Ela diz:** "A Ado lançou single. Vou ouvir primeiro e depois te digo se perde para a versão ao
  vivo." (Persona: tudo é comparado com a Ado; a Conta Anônima sabe do Kenshi antes de todo mundo.)
- **Peças:** tabela `acompanho` (obra, fonte, episódio visto), jobs a cada 2 h, filtro anti-spoiler
  (regras + Qwen), entrega no bom dia ou toast quando ele não está jogando.
- **Recursos:** baixo. **API:** zero/US$ 0,05. **Privacidade:** só ids públicos.
- **Esforço:** M (a parte difícil é o filtro e o "onde ele parou").

### 7 Caderno de fatos ("lembra que…")
- **O que é:** memória de longo prazo estruturada: o job noturno extrai fatos das conversas (gostos,
  pessoas, datas, decisões de projeto), deduplica por embeddings, guarda com **fonte, data e validade**
  e só promove fato novo depois de confirmado. "Lembra que…" grava na hora.
- **Ela diz:** "Anotei que o aniversário da sua mãe é 14/11 — confere?" Dias antes: "Faltam 5 dias.
  Quer que eu procure presente, ou vai improvisar de novo?"
- **Peças:** `fatos` (sujeito, relação, valor, fonte, confiança, expira), grafo leve em Postgres
  (sem Neo4j), confirmação no card/voz, MCP `memoria.fatos` (leitura já existe; falta escrita
  controlada), "esquece isso" apaga de verdade.
- **Recursos:** Qwen local ~10 min/noite. **API:** zero/US$ 0,10.
- **Privacidade:** alto risco → só local, auditável no PWA ("o que você sabe de mim?").
- **Esforço:** M.

### 8 Banco de frases pré-renderizadas
- **O que é:** a Ayanami renderiza de madrugada **variações** das frases fixas (espera viva, volta
  orgulhosa, pós-batalha, avisos, bom dia) e envia o pacote para o cache do PC. O primeiro som da
  espera passa a ser instantâneo e a voz deixa de gastar CPU do PC durante o jogo.
- **Ela diz:** o mesmo de sempre, só que sem a pausa — e sem repetir a mesma frase ("quinta vez hoje"
  vira piada dela, não defeito do sistema).
- **Peças:** catálogo de moldes, Kokoro, cache por hash (texto+voz+velocidade), sincronização.
- **Recursos:** minutos de CPU; ~50 MB. **API:** zero. **Esforço:** P.

### 9 Lembrete que escolhe a hora
- **O que é:** lembretes sem horário rígido ("me lembra de ligar para o banco hoje") que a Ayanami
  entrega no **melhor momento**: quando ele sai da partida, volta ao PC ou abre o celular, nunca no
  meio do jogo. Aprende a janela em que ele costuma resolver coisas.
- **Ela diz:** "Fim de partida, então agora: o banco fecha em 40 minutos."
- **Peças:** lembretes já existem; falta o gatilho por estado (presença, jogo, celular) e a política
  de hora. **Recursos/API:** zero. **Esforço:** P.

### 10 Relatório semanal de jogo
- **O que é:** horas por jogo (Steam Web API `GetRecentlyPlayedGames`, grátis), resultados do FIFA
  (log do `fifa-lances`, quando existir), FPS/temperatura média (MangoHud), placar Condessa × Pedro.
- **Ela diz:** "Top 3 da semana: FIFA, 9 h; você perdeu de 4 × 1 duas vezes para o PSG, eu
  contei. FPS caiu na quinta, culpa do driver, não sua."
- **Peças:** coletor diário, tabela `jogo_semana`, card no HUD/PWA. **Recursos/API:** zero.
- **Esforço:** P.

### 11 Domingo da Condessa
- **O que é:** retrospectiva semanal em **áudio de 3–5 min** (Kokoro, voz dela) que junta o diário
  (2), o jogo (10), o inglês (3), a música e o placar da semana. Ouve no celular ou no PC.
- **Ela diz:** "Semana 43. Favorita da semana: minha, claro. Você ganhou 4 dos 7 dias, não se
  acostume." **Peças:** itens 2/10 + molde + 1 chamada. **API:** ~US$ 0,02. **Esforço:** P.

### 12 Pauta automática do Conselho
- **O que é:** o job noturno lê o log de reações, as marcas de "isso foi sem sentido", a meta de
  ≥ 1 positiva/h e o equilíbrio do placar (Pedro ganhando 40–60 % dos dias) e escreve a **pauta da
  semana** do Conselho, com números. A persona evolui com dado, não com palpite.
- **Peças:** script de análise (já existe `reacoes_relatorio.py`), arquivo de pauta, skill
  `conselho`. **Recursos/API:** zero. **Esforço:** P.

### 13 Saúde do PC preditiva
- **O que é:** o PC manda SMART do SSD, temperaturas, erros do journal e updates pendentes do Nobara;
  a Ayanami acha tendência ("desgaste subiu 2 % no mês") e sugere a faxina na hora certa.
- **Ela diz:** "O SSD está bem. A faxina de ontem? Fui eu." **Recursos/API:** zero. **Esforço:** P.

### 14 Monitor de preços com memória
- **O que é:** o monitor existente ganha histórico e contexto: wishlist da Steam (preço via
  IsThereAnyDeal/Steam), hardware, e avisa só em **mínima de 6 meses** ou abaixo do teto que ele
  disse. **Ela diz:** "Menor preço do ano no Persona 5, 70 % off. Não me olhe assim, eu só aviso."
- **Recursos/API:** zero. **Esforço:** P.

### 15 Sono e ritmo pelo uso do PC
- **O que é:** último e primeiro input do dia, sessões longas sem pausa, madrugadas; tendência
  semanal, **nunca sermão**. Alimenta o filtro "madrugada/Pedro mal" da condessa-vida com dado real.
- **Ela diz:** (à 1h40, quarta madrugada seguida, frase curta) "Amanhã você agradece se fechar
  agora." No domingo: "Dormiu em média às 2h10. Não é crítica. É registro."
- **Peças:** heartbeat de presença do PC (já existe para a ponte), agregação diária.
- **Privacidade:** dado de saúde inferido → só node 2, apagável, sem API. **Esforço:** P.

### 16 Favorita do Dia com dossiê
- **O que é:** de madrugada ela já escolhe a **Favorita do Dia** (persona) e monta o dossiê: créditos
  (MusicBrainz), produtor, "tese ou fórmula", comparação com a Ado. Também prepara os créditos das
  faixas que ele mais tocou.
- **Ela diz:** "Favorita de hoje: *Hyperballad*. Motivo? Nenhum. Defendo até a meia-noite."
- **Recursos/API:** zero (MusicBrainz grátis, texto local). **Esforço:** P.

### 17 Vigia do node 1 contada pela Condessa
- **O que é:** só leitura do node 1 (MultiVideos, gold-crm, wedding): uptime HTTP, certificado TLS,
  disco, erros 5xx no log, backup do banco feito. Resumo vira 1 linha do bom dia; incidente vira
  alerta. **Não toca** o node 1 (credencial só de leitura, combinada com o Pedro).
- **Ela diz:** "O gold-crm teve 12 erros 500 às 3h; voltou sozinho. O certificado do wedding vence
  em 9 dias." **Recursos/API:** zero. **Esforço:** M (acesso a combinar).

### 18 Briefing de projeto ao abrir o editor
- **O que é:** a Ayanami mantém, por repositório, um resumo de estado (últimos commits, CI, PRs,
  tarefas abertas dos `tasks.md`, sobras do PROXIMOS-PASSOS §14). Quando ele abre o KPCeramica no
  editor, ela já sabe onde ele parou.
- **Ela diz:** "KPCeramica: você parou no icon-picker, o build da Vercel do tensura-mine está
  vermelho desde ontem." **Peças:** clone espelho (somente leitura) dos repos no node 2, `gh`
  API, job noturno. **API:** zero/US$ 0,05. **Esforço:** M.

### 19 Revisor noturno de repositórios
- **O que é:** versão leve do Engine: Claude Code headless no node 2, em **modo só leitura**, roda à
  noite sobre CI vermelho, alertas de dependência e sobras catalogadas, e entrega **propostas**
  (diagnóstico + plano), sem commit. Primeiro degrau de confiança antes do item 23.
- **Ela diz:** "Achei o motivo do CI vermelho do tensura-mine: versão do Node. Quer que eu faça?"
- **API:** zero (assinatura; usar a janela da madrugada, que ele não usa). **Esforço:** M.

### 20 Caça-vagas + entrevista pronta
- **O que é:** monitor de vagas (RSS/feeds de vagas públicas, filtradas pela stack dele); quando
  ele marca uma, a Ayanami já roda a extração da vaga do learning-imersivo e deixa a entrevista
  simulada pronta.
- **Ela diz:** "Achei duas vagas de Laravel remoto. Uma é furada; a outra está com a entrevista
  montada para hoje à noite." **API:** ~US$ 0,05 (extração). **Esforço:** M.

### 21 "Onde eu vi aquilo?"
- **O que é:** índice semântico pessoal (e5-small já está no node 2) de notas, docs dos projetos,
  diário (2), relatórios (4) e histórico de conversas; tool MCP `procura`.
- **Ela diz:** "Foi no runbook da Ayanami, §2, e você reclamou disso numa conversa do dia 21."
- **Recursos:** ~1–2 GB de índice no pgvector. **API:** zero. **Esforço:** M.

### 22 "Assiste por mim"
- **O que é:** manda um link (vídeo, podcast, aula) pelo celular; a Ayanami baixa o áudio,
  transcreve com faster-whisper em lote e devolve resumo + capítulos + "vale a pena ver inteiro?".
- **Recursos:** whisper small int8 em CPU ~1–2× tempo real (vídeo de 1 h ≈ 30–60 min de CPU, de
  madrugada). **API:** zero local; resumo longo pela API ~US$ 0,01/vídeo. **Esforço:** M.

### 23 Condessa Engine no node 2 com aprovação por voz
- **O que é:** o SDD `condessa-engine` hospedado na Ayanami: intenções abertas por voz ("Condessa,
  quero …") viram tasks rodando **Claude Code headless em worktrees** no node 2, com o Jev
  (portão de qualidade), PAUSED na janela de 5 h e **um único "aprova"** do Pedro no merge, por voz
  no PC ou botão no celular. O PC fica livre para jogar enquanto ela programa.
- **Ela diz:** "A task de plugins passou nos testes, o Jev aprovou, falta você. Resumo no card.
  Digo 'aprova' por você? Brincadeira. Diga você."
- **Peças:** todo o SDD + runner isolado no node 2 (container sem acesso a segredos de produção,
  token do GitHub com escopo mínimo), aprovação com confirmação forte (padrão do `confirma` do push),
  vigia de uso da assinatura.
- **Recursos:** 2–4 GB de RAM por sessão, 1 de cada vez; disco dos worktrees (~5–20 GB).
- **API:** zero (assinatura). **Privacidade/risco:** o mais sensível da lista (agente escrevendo
  código); por isso o item 19 vem antes.
- **Esforço:** G. Maior valor de longo prazo, mas depende do "ok" do Pedro (§15 item 4).

---

## Ordem sugerida

1. **Pacote "madrugada" (P):** 1 Bom dia + 2 Diário + 3 Aula do dia + 4 Pesquisa — um job
   agendado com 4 etapas, e o bom dia é a vitrine. Antes, medir no Y0.8 o Qwen 3B e o Kokoro no node 2
   e decidir a D8 → (b).
2. **5 Audiolivro no node 2** e **8 Frases pré-renderizadas** (mesmo worker Kokoro).
3. **6 Radar** e **7 Caderno de fatos** (a memória de verdade).
4. Os P baratos (9–16) em rodadas de agente.
5. **19 → 23:** revisor só leitura primeiro; o Engine completo com o "ok" do Pedro.

## Fontes

- Benchmarks de LLM em CPU: [edge-cpu-inference](https://github.com/nandan2003/edge-cpu-inference),
  [DEV: LLMs em CPU 2026 (Xeon 4 núcleos)](https://dev.to/manoir_yantai_f22f01340f0/-running-llms-on-cpu-in-2026-real-benchmarks-from-a-4-core-xeon-server-a-4-1438),
  [llama-bench](https://github.com/ggerganov/llama.cpp/blob/b8c1476e44cc1f3a1811613f65251cf779067636/examples/llama-bench),
  [It's FOSS: 8 modelos sem GPU](https://itsfoss.com/testing-local-llms-without-gpu).
- Preços Gemini (agregadores, conferir na página oficial):
  [Puter](https://developer.puter.com/tutorials/gemini-api-pricing/),
  [MorphLLM](https://www.morphllm.com/gemini-api-pricing),
  [mem0](https://mem0.ai/library/llms-and-models/gemini-api-pricing).
