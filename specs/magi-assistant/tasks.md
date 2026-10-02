# Tarefas — Magui (MVP)

Implementa [design.md](design.md). Cada tarefa cita os requisitos de
[requirements.md](requirements.md) (R*n*.*m*) e termina com um critério verificável.
Ordem pensada para cada fase já ser usável sozinha.

## Fase 0 — Base do projeto e spikes

- [ ] **0.1 Projeto Python** — `pyproject.toml` com `uv` e Python 3.12, pacote `magi/`, `ruff` e `pytest`; CI simples no GitHub Actions rodando lint e testes.
  *Pronto:* `uv run pytest` passa localmente e no CI.
- [ ] **0.2 Config e segredos** — `magi/common/config.py` lê `~/.config/magi/config.toml` (recarrega ao salvar); `magi/common/secrets.py` lê chaves do keyring; comando `magi-keys add <nome>` para cadastrar. *(R21.1, R21.4)*
  *Pronto:* teste carrega config de exemplo; nenhuma chave em arquivo.
- [ ] **0.3 Banco** — `deploy/docker-compose.yml` com `pgvector/pgvector:pg16` em `127.0.0.1`, memória limitada; migrações das tabelas do design §7. *(R11, RNF-02)*
  *Pronto:* `docker compose up -d` + migração criam o esquema; container ocioso < 80 MB.
- [ ] **0.4 Spike S1 — áudio no PipeWire** — captura com `sounddevice`, listar e mutar `source-output` do Discord e baixar `sink-input`s com `pulsectl`.
  *Pronto:* nota no design com o mecanismo escolhido.
- [ ] **0.5 Spike S2 — atalho** — testar `globalShortcutPressed/Released` do KGlobalAccel e evdev do DualSense.
  *Pronto:* mecanismo de PTT decidido; se precisar do grupo `input`, documentado.
- [ ] **0.6 Spike S3 — modelos** — medir latência e custo de transcrição PT-BR, TTS feminina, agente e pesquisa; ouvir as vozes femininas e escolher.
  *Pronto:* seção `[tasks]` da config preenchida.
- [ ] **0.7 Spike S4 — "Ei Magui"** — gravar ~50 amostras, treinar o modelo do openWakeWord, medir falsos disparos em 1 h de jogo.
  *Pronto:* `ei_magui.onnx` com ≤ 1 falso disparo/h (RNF-06).

## Fase 1 — Base de voz

- [ ] **1.1 Protocolo de eventos** — `magi/common/events.py`: eventos Wyoming + `magi-wake`, `magi-mouth`, `playback-done`. *(R22.1)*
  *Pronto:* testes de serialização ida e volta.
- [ ] **1.2 Satélite: captura e wake word** — captura 16 kHz, openWakeWord por bloco, limiar recarregável. *(R1.1, R1.2, R1.6)*
  *Pronto:* ativação aparece em log em < 300 ms; CPU ociosa ≤ 2% de um núcleo (RNF-01).
- [ ] **1.3 Satélite: VAD e envio** — Silero VAD, 700 ms de silêncio, máximo 15 s, envio ao núcleo. *(R1.5)*
  *Pronto:* frase falada chega inteira ao núcleo.
- [ ] **1.4 Satélite: atalho** — PTT pelo mecanismo do spike S2 (teclado; DualSense se viável). *(R1.3, R1.4, R1.7)*
  *Pronto:* grava enquanto o atalho está pressionado.
- [ ] **1.5 Núcleo: esqueleto e estados** — serviço asyncio, máquina de estados do design §3.1, interrupção por nova ativação. *(R12.5)*
  *Pronto:* teste com satélite falso percorre todos os estados.
- [ ] **1.6 Transcrição** — provedor da config, vocabulário de dica (jogos instalados + gírias + correções, ≤ 200 tokens), erro → "não peguei, repete?". *(R3.1, R3.2, R3.5, R3.6)*
  *Pronto:* frase de teste transcrita; nenhum arquivo de áudio criado.
- [ ] **1.7 Correções** — "não, eu falei X" salva o par e refaz o turno; correções aplicadas antes do roteador. *(R3.3, R3.4)*
  *Pronto:* teste unitário e turno real corrigido.
- [ ] **1.8 Roteador local** — `intents.yaml`, normalização, `rapidfuzz`, slots de jogo pelo catálogo da Steam, faixa de dúvida "você quis dizer X?". *(R4.1–R4.4)*
  *Pronto:* acerto ≥ 90% no conjunto inicial de frases de ouro (`tests/data/utterances.yaml`).
- [ ] **1.9 Ações: jogos** — abrir por `steam://rungameid`, sugestões quando não achar, fechar com confirmação (SIGTERM, SIGKILL só com nova confirmação). *(R5.1–R5.5)*
  *Pronto:* "abre o dedi cels" abre o Dead Cells; "fecha o jogo" exige "confirma".
- [ ] **1.10 Ações: HUD, volume e RGB** — abrir/fechar HUD, tela de ociosidade, detalhes, RGB Sync, volume, mudo, cor pelo OpenRGB. *(R6.1–R6.4)*
  *Pronto:* cada comando funciona por voz.
- [ ] **1.11 Voz e cache** — TTS em streaming; frases curtas pré-geradas no primeiro uso e guardadas; satélite reproduz e envia `magi-mouth`; ducking de música e jogo. *(R12.1, R12.2, R12.4)*
  *Pronto:* comando conhecido responde em ≤ 1,5 s (RNF-04).
- [ ] **1.12 HUD: socket e rosto** — `hud_bridge` no HUD, módulo `face` com as 7 expressões, boca por `magi-mouth`, legenda em mincho, 30 fps acordado e 1 quadro a cada 4 s dormindo; rosto na metade direita da tela de ociosidade e pequeno no cabeçalho do painel. *(R17.1–R17.7)*
  *Pronto:* HUD ocioso sem aumento de CPU; boca sincronizada à voz.
- [ ] **1.13 Serviços** — units systemd `--user` para satélite e núcleo com reinício automático; `hud/install.sh` passa a instalar também a Magui. *(RNF-11)*
  *Pronto:* `kill -9` em qualquer processo é recuperado em ≤ 5 s.
- [ ] **1.14 Medição da fase** — script de desempenho do design §10 (CPU/RAM ociosos, latência p90).
  *Pronto:* RNF-01, RNF-02, RNF-04 dentro da meta, registrados no PR.

## Fase 2 — Spotify

- [ ] **2.1 MPRIS** — abrir o flatpak, tocar, pausar, próxima, anterior, volume; esperar o MPRIS até 15 s. *(R7.1, R7.3)*
  *Pronto:* comandos funcionam com o Spotify fechado ou aberto.
- [ ] **2.2 Web API** — app de desenvolvedor, OAuth PKCE, tokens no keyring; busca por nome e reprodução no app local. *(R7.2)*
  *Pronto:* "toca Linkin Park" toca o artista.
- [ ] **2.3 Importar gosto** — mais ouvidos (3 prazos) e recentes para `taste`. *(R8.2)*
  *Pronto:* tabela preenchida na primeira execução.
- [ ] **2.4 Sinais** — pulo < 30 s, ouvida inteira, "essa é boa", "nunca mais" em `music_signals`. *(R8.3–R8.5)*
  *Pronto:* sinais aparecem ao pular ou terminar faixas escolhidas pela Magui.
- [ ] **2.5 "Coloca uma boa"** — escolha por gosto + contexto (horário, gênero do jogo, pedido); diz o que colocou. *(R8.1)*
  *Pronto:* responde em ≤ 3 s e evita faixas com "nunca mais".

## Fase 3 — Agente

- [ ] **3.1 Provedores e KeyPool** — registro por tarefa, rodízio de chaves com espera, bloqueio de dados pessoais em cota gratuita. *(R21.1–R21.5)*
  *Pronto:* teste simula 429 e troca de chave; teste de bloqueio `personal=True`.
- [ ] **3.2 Orçamento** — registro de custo por chamada, teto ajustável por voz e config, aviso em 80%, bloqueio em 100%, virada do mês. *(R16.1–R16.5)*
  *Pronto:* testes unitários de cada regra.
- [ ] **3.3 Persona** — prompt fixo (~500 tokens) com os 5 traços e regras de tom por nível de humor. *(R13.1, R13.2, R13.6)*
  *Pronto:* revisão com 10 perguntas de teste; nenhuma resposta inventada sem fonte.
- [ ] **3.4 Grafo do agente** — LangGraph com as ferramentas do design §4.3, ferramentas perigosas via `confirming`, limite de 4 passos e de 1.500 tokens de prompt. *(R11.3, R5.3)*
  *Pronto:* pergunta geral respondida em ≤ 3 s (RNF-05).
- [ ] **3.5 Resposta curta + completa** — até 2 frases faladas, resposta completa e links no HUD. *(R12.3)*
  *Pronto:* card com links aparece no HUD.
- [ ] **3.6 Visão** — `screenshot(window|screen)` só sob pedido, apaga o arquivo após envio. *(R9.1–R9.4)*
  *Pronto:* "que bicho é esse?" responde sobre a janela ativa em ≤ 5 s.
- [ ] **3.7 Pesquisa** — Gemini com busca do Google; envia só a pergunta reescrita; links no HUD. *(R10.1–R10.3)*
  *Pronto:* pergunta sobre algo recente vem com fonte.

## Fase 4 — Memória e personalidade

- [ ] **4.1 Memórias** — gravação de memórias dos turnos, busca de até 5 por similaridade, "esquece isso", histórico local. *(R11.2, R11.5, R11.6)*
  *Pronto:* fato contado num dia é lembrado no outro; "esquece isso" remove.
- [ ] **4.2 Perfil e estilo** — perfil compacto ≤ 300 tokens atualizado 1×/dia com gírias, formalidade e tamanho de resposta. *(R11.1, R11.4)*
  *Pronto:* perfil muda depois de uma semana de uso, sem passar do limite.
- [ ] **4.3 Termômetro de humor** — sinais locais, nota 0–4 suavizada, comandos "pega leve" / "pode pegar pesado", termômetro no HUD. *(R13.3–R13.5, R13.7)*
  *Pronto:* nível visível no HUD e respeitado no tom.
- [ ] **4.4 Ajuda no jogo** — `help_log`, tópico canônico, degraus, "manda a solução", estimativa de travado por pedidos repetidos e conquistas. *(R14.1–R14.5)*
  *Pronto:* segunda ajuda no mesmo trecho começa na dica direta.
- [ ] **4.5 Frases de ouro, rodada 2** — ampliar `utterances.yaml` com 2 semanas de turnos reais. *(RNF-07)*
  *Pronto:* acerto ≥ 95%.

## Fase 5 — Proatividade e Discord

- [ ] **5.1 Detecção de call** — `source-output` do Discord a cada 2 s; desliga e religa o "Ei Magui". *(R2.1, R2.2)*
  *Pronto:* entrar e sair de call alterna a detecção em ≤ 5 s.
- [ ] **5.2 Mudo só para o Discord** — PTT em call muta o `source-output` do Discord e restaura; recuperação após queda. *(R2.3, R2.4)*
  *Pronto:* amigos não ouvem a fala para a Magui.
- [ ] **5.3 Alertas** — temperatura de CPU/GPU, bateria do controle ≤ 15%, custo 80%/100%; só na tela em call. *(R15.1, R15.2)*
  *Pronto:* alerta simulado aparece por voz fora de call e só na tela em call.
- [ ] **5.4 Sugestão de música** — gênero pelas tags da Steam; casual sugere no máximo 1×/sessão; imersivo e competitivo nunca. *(R15.3–R15.6)*
  *Pronto:* abrir um jogo de corrida sugere; abrir um RPG não.

## Fase 6 — Notícias

- [ ] **6.1 Fontes e coleta** — tabela de fontes com confiança 1–3; RSS, Steam News dos jogos instalados, AniList, Reddit; scraping com `robots.txt` e 1 req/s; timer systemd a cada 2 h. *(R18.1, R18.2, R18.4)*
  *Pronto:* execução coleta itens novos em ≤ 1 min, sem duplicar URLs.
- [ ] **6.2 Agrupamento** — embeddings Gemini, cosseno ≥ 0,88 em 72 h. *(R18.3)*
  *Pronto:* a mesma notícia de 3 sites vira 1 item com 3 fontes.
- [ ] **6.3 Classificação** — Gemini em lote com saída JSON (franquia, tipo, spoiler, tamanho, manchete segura), prompt fixo + até 6 exemplos do meu retorno; cota esgotada adia. *(R18.6, R19.1)*
  *Pronto:* 20 itens reais classificados e revisados manualmente.
- [ ] **6.4 Progresso e anti-spoiler** — progresso pela lista de anime (AniList ou MAL, a decidir) e pela Steam; manchete reescrita ou escondida; "pode dar spoiler de X". *(R19.1–R19.3)*
  *Pronto:* notícia com spoiler de obra em andamento nunca aparece com o spoiler.
- [ ] **6.5 Prioridade e entrega** — fórmula do design §8, níveis, regra da bomba (2 fontes, uma de confiança 3), entrega via núcleo. *(R18.5, R19.4–R19.6)*
  *Pronto:* item "bomba" simulado é falado fora de call; "alta" vira card.
- [ ] **6.6 Retorno e aprendizado** — "não curti", ignorados 3×, "mais disso", obra largada. *(R19.7, R19.8)*
  *Pronto:* tema rejeitado cai de nível na execução seguinte.
- [ ] **6.7 Perguntas sobre novidades** — `news_query` no agente, "novidades?" com até 5 itens, fallback para pesquisa. *(R20.1–R20.3)*
  *Pronto:* "o que saiu de novo do Silksong?" responde com links.

## Encerramento do MVP

- [ ] **7.1 Medição final** — todos os RNF medidos e registrados no README.
- [ ] **7.2 Duas semanas de uso real** — conferir as métricas de sucesso do PRD.
