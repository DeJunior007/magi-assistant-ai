# Próximos passos

O MVP está implementado (ver [`README.md`](../README.md)). Na rodada de 2026-10-10/12 entraram a vida
da Condessa (placar e jogo), o overlay, o audiolivro, a espera viva e o learning imersivo (entrevista
por vaga + roleplay), e ficou pronto o SDD da Ayanami central; isto é o que falta, cada item com
**por quê**, **o que falta** e **como validar**. Fontes: `specs/magi-assistant/tasks.md` (itens
`[ ]`), [`specs/DECISOES-2026-10-10.md`](../specs/DECISOES-2026-10-10.md), os `specs/<sdd>/tasks.md`
(itens `[ ]` e *Sobras*), [`docs/perf/fase1.md`](perf/fase1.md), [`docs/spikes/S4.md`](spikes/S4.md)
e os relatórios das tarefas. A ordem está na [seção 15](#15-ordem-sugerida).

## 1. Wake word "Condessa" — resolvido no uso (2026-10-07)

No teste de bancada acertava 90,9% (meta 95%), mas no uso real o Pedro não teve problema: tarefas
0.7/0.8 fechadas. Se voltar a falhar com música/jogo alto, o caminho está no
[GUIA §12](GUIA.md#12-condessa-wake-word) (gravar positivas com jogo e re-treinar).

## 2. Latência do agente — meta aceita; o foco vira a espera

p90 de 3,39 s ficou bom pela qualidade da resposta. Em vez de cortar tempo, a espera vai ficar
viva: animação de "pensando" mais expressiva, uma frase curta relacionada enquanto ela pensa e,
em pedidos complexos, resposta em lotes (ela entrega uma parte enquanto prepara a próxima).

## 3. Validações ao vivo pendentes

Implementado e testado com dublês; falta conferir no uso real:

| Item | O que conferir |
| --- | --- |
| 5.2 Mudo só para o Discord | **Prioridade baixíssima (Pedro, 2026-10-09).** Numa call: segurar Pause/PS+Share muta só o Discord e restaura ao soltar; derrubar o satélite no meio e ver o mudo voltar ao reiniciar. |
| 1.26 Reconhecimento | Depois das mudanças (fim de fala 1 s, fala mínima 240 ms, ganho automático): usar alguns dias e conferir no log `ouvi "..."` se a queixa "reconhece mal" sumiu. |

Conferidos pelo Pedro em 2026-10-09: **U4 LED do HUD**, **2.5 "Coloca uma boa"**, **U5 papel de
parede**, **clique no rosto** (ouve sem wake word) e **digitação no Konsole** (texto e setas).

## 4. Lacunas conhecidas

| Lacuna | Por quê / o que falta | Como validar |
| --- | --- | --- |
| ~~Conquistas da Steam (4.5)~~ | **Feito (2026-10-07):** `magi/core/steam_local.py` lê horas e conquistas do disco; linha no prompt, gancho `achievements_idle` ligado e ferramenta `steam_game`. | "quantas horas eu tenho no Persona?"; travado há muito sem conquista pula para a dica direta. |
| Tags da Steam via SteamSpy | Gênero do jogo (sugestão de música, "coloca uma boa") vem de serviço de terceiro (cache em `~/.cache/magi/steam-tags.json`); pode sair do ar ou mudar. | Trocar por fonte oficial ou aceitar o risco; teste: jogo novo recebe tags. |
| "A seguir" no Now playing | O bloco fica escondido: a fila do Spotify precisaria de um escopo novo no OAuth. | Pedir o escopo, refazer `magi-spotify-login` e ver a próxima faixa no HUD. |
| Limites da memória sem calibração | `MIN_SCORE 0,35` (busca), `FORGET_MIN_SCORE 0,45` ("esquece"), `DUPLICATE_SCORE 0,93` (duplicata) foram escolhidos sem dados reais. | Revisar com 2 semanas de memórias reais: lembranças irrelevantes ou duplicadas indicam ajuste. |

## 5. Uso real de 2 semanas

| Tarefa | O que é |
| --- | --- |
| 4.6 Frases de ouro, rodada 2 | Ampliar as frases de teste com 2 semanas de turnos reais (RNF-07: ≥ 95% de acerto em comandos conhecidos). |
| 7.1 Medição final | Medir todos os RNF e registrar em `docs/perf/mvp.md`. O uso sai de `magi-uso` (métricas do PRD direto do banco); com 4 dias (2026-10-07): 24,5 interações/dia, 0,2 correção a cada 20, 2 pulos em 18 escolhas, custo projetado US$ 3,04 de 5. |
| 7.2 Métricas do PRD | Conferir as métricas de sucesso do PRD depois de 2 semanas de uso. **Precisa do Pedro.** |

## 6. Operação

- **Mover o repo de lugar:** já feito uma vez (`~/projetos` → `~/Documentos`). Parar
  `magi-core`/`magi-satellite`/`magi-ayanami.timer`, mover a pasta, apagar o `.venv` (os scripts dele
  guardam o caminho antigo) e rodar `hud/install.sh --start`: ele repõe o link
  `~/.local/share/gamerhud`, as units, o atalho "Gravar voz da Condessa" e o `uv sync`. O Postgres
  não muda (projeto compose `magi`, volume `magi_magi-pgdata`).
- **Satélite no Raspberry Pi (futuro, R22):** o protocolo já é Wyoming + eventos `magi-*` com
  identificador de satélite; falta empacotar o `magi-satellite` para ARM e um áudio de saída no Pi.

## 7. Condessa no HUD (retrato 2.5D, reações e conselho)

- **Feito:** retrato 2.5D em partes a 60 fps (respiração, cabelo em pêndulo, olhar com parallax,
  boca pela voz, fundo com parallax que muda de cor pelo humor e cresce com a voz); reações só no
  rosto ao HUD, à música e aos cliques (`hud/wired/reactions.py`); personalidade e gosto decididos
  pelo **Conselho da Condessa** (`persona/`, comando `/conselho`).
- **Reações (2026-10-09):** as 110 do Conselho implementadas (SDD `specs/condessa-reacoes/`, todas
  as tarefas R0–R3 feitas); 108 ativas (49 e 68 foram substituídas). Sinais novos ligados: retrato
  clicável/hover, tag do turno (elogio/zoeira/correção/sussurro), hooks do Claude Code (instalados no
  `~/.claude/settings.json`), volume do PipeWire, notificações (D-Bus, só escuta), ventoinha,
  reinício pendente, capturas e `[datas]`. Arte nova montada (E3, B16, B17, P9–P13); os efeitos D
  ficam em código por decisão do Pedro (animação própria).
- **O que falta:**
  - **Semana de validação** (até ~16/10): `uv run python -m hud.tools.reacoes_relatorio` e o roteiro
    `docs/perf/reacoes.md` (limiares chutados: sussurro −42 dBFS, ventoinha, capturas).
  - **P13** (braços cruzados) refeito com os braços na altura do peito: hoje cai na faixa em que o
    corpo esmaece e quase some.
  - **Favoritas do Pedro** automáticas: hoje só por `[pedro] favoritas` no
    `~/.config/magi/condessa-gosto.toml`; dá para puxar do top do Spotify (o núcleo já tem o OAuth).
  - **"Condessa, sem comentário de música"** por voz: hoje só pelo arquivo (`[falas] musica = false`).
- **Como validar:** uma semana de uso olhando se as reações e falas aparecem na medida (sem
  poluir) e se a Favorita do Dia/madrugada fazem sentido; CPU do HUD ≤ 10% de um núcleo.

## 8. Autoconserto — retomado (2026-10-07)

Níveis 0 e 1 implementados (ver `docs/design/AUTOCONSERTO.md`). **Como validar:** derrubar um
serviço de propósito (`systemctl --user stop magi-ayanami` e um `kill -9` no `magi-satellite`), ouvir
a pergunta, dizer "sim", ver o diagnóstico no card; depois "prepara um conserto" num bug simples
de teste e "aplica o conserto" para ver o vigia reiniciar (e desfazer, se quebrar).

## 9. Validações ao vivo das features novas

| Item | O que conferir |
| --- | --- |
| FIFA 22 por voz | "Bora bater uma bola": abre o `fifaconfig` centralizado no monitor principal; FPS do MangoHud aparece no HUD e trava em 188. |
| Faxina do SSD | O timer diário (`magi-clean`) roda, a Magui avisa e a Condessa sorri no HUD. |
| Rádio Ayanami | Notícias em PT, "quer ouvir outra?", "conta mais dessa" com resumo local. |
| **Reabrir o HUD** | Antes de tudo abaixo: o HUD aberto ainda roda o código de antes da rodada (vida, espera, learning). Fechar e abrir de novo (e reiniciar o `magi-core`). |
| Overlay O3.1 | Rodar `hud/install.sh`, sair e entrar na sessão. Aparece em ≤ 10 s no canto superior direito; clique fora da silhueta atravessa; arrasto move e a posição volta após relogar; fora do Alt+Tab; some com o HUD aberto e volta ao fechá-lo (D2); em jogo vai para o outro monitor (D3). Se a máscara não atravessar no Wayland: `MAGI_OVERLAY_XCB=1`. Anotar em `docs/perf/overlay.md` com a CPU. |
| Overlay O3.2 | Uma semana com o overlay; relatório de `reacoes-overlay.jsonl`; confirmar D2 (esconde com o HUD) ou trocar por espelho. |
| Audiolivro A3.1 | Pôr 2 livros (1 EPUB em PT, 1 PDF) em `~/Livros` e reiniciar o `magi-core`. "Lê o livro X", "volta um parágrafo", "mais devagar", pergunta outra coisa no meio, "continua", "para", reinicia e "continua o livro"; `costs` sem linha nova (Kokoro); voz por personagem estável em ~50 falas. |
| Espera viva E4.1 | Medida antes/depois (`tools/perf.py latency --turns 20`, frase/lotes desligados × ligados; p90 do primeiro som ≤ 1,8 s) e uma semana de uso olhando o log `espera:`. Frase que soar falsa ou chata: pôr em `[espera] vetadas` (ou voltar ao Conselho). Decidir se os lotes ficam ligados no dia a dia (`[espera] lotes_max`, `lotes_frases_max`). |
| Learning imersivo LIF.1 | **Gasta API.** 3 vagas reais (backend, full-stack, dados): perfil conferido à mão, uma simulação de 30 min por voz e uma por texto, o retorno (notas 0–100 fazem sentido?), um roleplay, o custo em `costs`. Conferir o Ctrl+V da vaga no Wayland real. Relatório em `docs/perf/learning-imersivo.md`. |
| Vida: placar e jogo | Escolher a tecla do "isso foi sem sentido" (`[vida.sem_sentido] atalho`) e se ela precisa ser global; conferir o hover do medidor maior (até 11 linhas) com o ✗, o `O1` de frente nas cenas e os roteiros novos; depois de 7 dias de log, calibrar o placar (o Pedro deve ganhar 40–60 % dos dias, senão mexer nos tetos de `[vida.placar]`; roteiro em `docs/perf/reacoes.md` §0b). |

## 10. Decisões em aberto

- **Nome da assistente:** "Magui" (nome no código, persona e HUD) ou "Condessa" (palavra de
  ativação e rosto do HUD).
- **Voz local (prioridade baixa, decidir depois):** trocar a síntese da OpenAI por uma local
  (sem custo, sem rede). Caminhos: clonar a `marin` a partir de `~/Music/magi-vozes/condessa-jovem`
  (F5-TTS/XTTS em PT-BR; medir latência na RX 9060 XT ou CPU) ou o Kokoro, já baixado em
  `~/.cache/magi/kokoro` (leve, voz `pf_dora`, mais robótica). Também abre a porta para a Ayanami
  ter voz própria no rádio.
- **Chamadas D-Bus antigas do `hud/install.sh`:** o `dbus-send` de `reconfigure` ao KWin e o
  `doRegister`/`setShortcut` do KGlobalAccel do `install_hud` continuam lá (Sobras O2.1). Remover,
  dado o risco de derrubar a sessão? O overlay não depende deles (a regra vale no próximo login).
- **Ideias recomendadas pelas três delegadas** (não implementar sem o "ok"): "pose de vitória" como
  3º número do truque, "bebe água" e a linha do ânimo do dia no hover (Conselho placar-e-jogo,
  `specs/condessa-vida/tasks.md`); teste do pedido real e placar de espera (Conselho da espera,
  Sobras E2.1). Também: `mexe_no_fone` no truque, clique do meio para "a última, agora" (só a
  Asuka), "dia com ≥ 1 commit" +1 Pedro (só a Kurisu), `chefe`→`chefao` (1 assinatura).
- **Fixture de teste com schema temporário no `magi-pg`:** liberar um fixture que cria e apaga um
  schema próprio por teste (hoje os testes `db` evitam mexer no banco real)? Destrava testes de
  migração e de repositório contra Postgres de verdade.
- **Ayanami central:** as D1–D15 de [`specs/ayanami-central/requirements.md`](../specs/ayanami-central/requirements.md)
  (rede, fila, app do celular, memória, storage do backup, a TCL, quem roda o `magi-casa`, gasto,
  canal de aviso, escopos do MCP, voz, retenção). Até ele decidir valem os padrões (a).
- **Voz:** decidida — `gpt-4o-mini-tts` com a voz `marin` e instruções de voz jovem
  (`~/.config/magi/config.toml`). Alternativas locais ficaram em `~/Music/magi-vozes/`.

## 11. Nova UI do painel e Konsole (2026-10-08)

Feito: painel redesenhado pelo mockup (`docs/design/nova-ui/`), Konsole interativo do Claude Code
no HUD (troca de lugar com o CAM 01 ao expandir), dados novos (clock, swap, disco, IP/DNS, git).
Regra do KWin "MAGI Gamer" sem `acceptfocus` forçado (backup `~/.config/kwinrulesrc.bak-acceptfocus`).
`settings.json` do HUD com `konsole_cwd = /home/pedrojr` (memória do Claude Code e `/resume`).

Próximos passos, em ordem:
1. ~~**Konsole persistente com tmux**~~ — feito: o `claude` roda em `tmux -L magi` (sessão
   `magi-claude`, config `hud/tmux-magi.conf`, sem barra/prefixo, `escape-time 0`); fechar o HUD
   só desconecta, e ao abrir o HUD reconecta sozinho. `konsole_tmux: false` no `settings.json`
   volta ao pty direto. Encerrar de vez: `tmux -L magi kill-session -t magi-claude` (ou sair do
   claude). Mudou o `.conf`? `tmux -L magi kill-server`.
2. ~~Konsole: TOKENS na barra de status; linhas cortadas no card recolhido~~ — feito: TOKENS =
   contexto do último turno (entrada + cache) lido do transcript via `~/.claude/sessions/<pid>.json`
   (`TokenMeter`); o card encolhe a fonte (até 7 px do mockup) para caber a largura da sessão.
3. Testes manuais: ~~digitação no Konsole (texto, setas)~~ conferida em 2026-10-09; falta ver o foco
   voltar ao recolher, o HUD não roubar o foco do jogo sem clique e a digitação na tela learning.
4. Learning Mode onda 6: LM3.4 (balão com resultado real), LM4.2, LM4.3 (observações na tela),
   LM1.8 (tema da sessão) — `specs/learning-mode/tasks.md`. Learning ligado na config, ações no
   gpt-5.4-mini, observações no Qwen local (`magi-qwen`, só CPU, só durante a aula).
5. ~~Pendências antigas~~ — feito (2026-10-09): tokens `glpat` tirados dos remotes, do
   `~/.gitconfig`, do `~/.git-credentials` e do `glab` (os acessos já estavam revogados);
   `scratch/` no `.gitignore`; `LearningConfig.enabled` já tinha padrão True. O comando
   `magi learning` de terminal foi descartado pelo Pedro.
6. ~~`git push` da `main`~~ — feito (2026-10-09).

## 12. Voz e serviços (2026-10-09)

- **Clique no rosto faz ela ouvir:** o `push_to_talk` do HUD agora ativa sem wake word e pede uma
  escuta ao satélite (`magi-listen`, `reason="tap"`), que termina pelo VAD.
- **Keyring trancado na subida:** a fala que chega sem STT faz o núcleo reler as chaves e remontar
  voz e agente (`Core.revive`, no máximo a cada 30 s). Antes, só reiniciando o `magi-core`.
- **`docker down-all`** (função no `~/.bashrc`) não derruba mais o projeto compose `magi`: ele tinha
  apagado o `magi-pg` (memórias, volume intacto) e o `magi-qwen`; os dois foram recriados.
- **Microfone em zero:** se o log do satélite disser "silêncio digital (só zeros)", é o mudo físico
  do headset (ELITE 08), não o software.

Próximos passos, do mais rápido ao mais trabalhoso:
1. Foco do Konsole (seção 11, item 3) e o reconhecimento de voz no uso (seção 3).
2. Refazer o P13 (seção 7).
3. Espera mais viva (seção 2): animação de "pensando", frase curta e resposta em lotes.
4. Learning Mode onda 6 (LM3.4, LM4.2, LM4.3, LM1.8), em agentes por tarefa como as reações.
5. Depois de uso: semana de validação das reações (~16/10) e calibração da memória (seção 4).

## 13. Ideias para desenvolver (Pedro, 2026-10-09)

Cada uma virou SDD (decisões em [`specs/DECISOES-2026-10-10.md`](../specs/DECISOES-2026-10-10.md)).
Estado em 2026-10-12:

| Ideia | Estado | O que entrou / o que falta |
| --- | --- | --- |
| **Ebook como audiolivro** | **feito (2026-10-11/12)** — `specs/audiolivro/` | EPUB/PDF (`pymupdf`), marcação por regras + Qwen local, elenco de vozes Kokoro, marcador de onde parou, intents `book.*`. Falta a validação do Pedro (A3.1, seção 9). |
| **Learning Mode mais imersivo** | **feito (2026-10-11/12)** — `specs/learning-imersivo/` | Entrevista pela vaga colada (perfil, roteiro de 30 min, condução, retorno 0–100 por aspecto, painéis no HUD) e roleplay (4 cenários). Falta a validação do Pedro (LIF.1, gasta API). |
| **Overlay só da Condessa** | **feito (2026-10-11/12)** — `specs/condessa-overlay/` | Janela própria (`hud/condessa_overlay.py`), retrato sem fundo, gestos, autostart e regra do KWin; esconde com o HUD e foge do jogo. Falta a validação do Pedro (O3.1/O3.2). |
| **FIFA 22: reagir a lances** | SDD pronto, não começado — `specs/fifa-lances/` | 12 tarefas (OCR do placar primeiro; narrador só com o "vai" do Pedro). |
| **Retrato com ângulos de verdade** | SDD pronto, não começado — `specs/condessa-angulos/` | 9 tarefas; o código (A0–A2) anda sem o Pedro, a arte (A3.1) é dele. |
| **Ayanami central + casa + celular** (nova) | SDD pronto, não começado — `specs/ayanami-central/` | Ayanami como API central no node 2 (fila, notícias, backup, MCP, modo nuvem), `magi-casa` para as TVs (Samsung, Roku, Android TV) e PWA no Android. 54 tarefas em 10 ondas. Trava: o Pedro confirmar o node 2 e dar acesso SSH, o Tailscale (PC, node 2, celular) e as decisões D1–D15 (seção 10). As ondas 1–3 andam sem ele. |

Primeira leitura de viabilidade (2026-10-09, mantida como histórico):

| Ideia | O que é | Primeira leitura |
| --- | --- | --- |
| **Ebook como audiolivro** | A Condessa lê um ebook com entonação que varia (narração, diálogo, emoção da cena). | Viável com o TTS atual (`gpt-4o-mini-tts` aceita instruções de voz por trecho): dividir o texto em trechos, marcar fala/narração/emoção e mandar a instrução junto. Custo por página a medir; voz local (seção 10) baratearia. Precisa de leitor de EPUB/PDF, marcador de onde parou e controles por voz (pausa, volta, "lê mais devagar"). |
| **Learning Mode mais imersivo** | Mais temas e preparação de entrevista: o Pedro manda a descrição da vaga e ela prepara a conversa para aquela vaga. | Extensão natural do LM1.8 (tema `interview` já existe, genérico): um tema "vaga colada" que lê a descrição, extrai stack/senioridade/requisitos e monta o roteiro da entrevista. É a "coisa nova" do Learning depois da versão inicial. |
| **FIFA 22: reagir a lances** | Ela reage a gol, entrada forte etc. e comenta o jogo ("PSG x Barcelona"). | O jogo não expõe eventos. Caminhos, do mais simples ao mais caro: (1) ler o placar na tela (OCR de um recorte, a cada segundo) para gol/fim de jogo; (2) transcrever o áudio do narrador (monitor do PipeWire só do jogo + STT local) e casar palavras-chave ("goal", "what a tackle"); (3) ler a memória do processo (frágil e arriscado). Começar pelo (1), que já dá gol, placar e times. |
| **Overlay só da Condessa** | Só o retrato dela, pequeno, por cima do desktop, ligado no login, como Siri/Alexa, sem o HUD inteiro. | Viável: uma janela Qt sem moldura, sempre no topo e transparente a cliques fora do rosto, reaproveitando o `PartsPortrait` e o `Reactor`. Autostart no login. Clique no rosto = falar (já existe no núcleo). |
| **Retrato com ângulos de verdade** | Usar a folha de 16 rostos (frente, 3/4, perfil, olhando para cima/baixo, mão no queixo/boca) para ela virar a cabeça e mexer o corpo, mesmo sem animação de verdade. | Viável em "2.5D de troca": cada ângulo vira um conjunto de camadas próprio (como a A1 hoje), e a troca entre ângulos é uma transição curta (dissolve + leve deslocamento/escala na direção do giro) em vez de animação. Usos: olhar para o lado do painel que reagiu, virar de perfil ao pensar, mão no queixo no "Ideia!". O custo maior é a arte: cada ângulo precisa das suas bocas/olhos para falar e piscar (ou fala só no ângulo de frente). |

## 14. Sobras desta rodada (para uma rodada de limpeza)

Coisas técnicas que um agente resolve sem o Pedro, anotadas nas *Sobras* dos `tasks.md`. Uma tarefa
de limpeza por grupo, cada uma com testes.

| Item | O que conferir |
| --- | --- |
| Roleplay não volta ao cenário após reiniciar | O id do cenário fica só em memória (`LearningWiring._scenario_of`); a sessão retomada cai em `free`. Gravar o `scenario` na entrada de `topics` (`repo.set_topic`, `SessionInfo.scenario`, `session.set_topic`). *(LI4.2)* |
| Retorno da entrevista depois de reiniciar | Sem `repo.interview_of(run_id)`: o retorno pendente sai como "MOCK INTERVIEW", sem empresa. *(LI2.3)* |
| Retry do retorno no painel | A spec §10 pede; falta comando no núcleo (ex.: `lm_interview {"cmd":"debrief"}` + enum + `wiring.py`) e o botão. Esc com a lista de temas aberta fecha a lista antes do painel. *(LI2.3, LI2.5)* |
| Rótulo de custo `learning_job` | `LearningCostTask` não tem `learning_job`: a extração da vaga sai como `learning_actions` em `costs`; `config.example.toml` sem `[tasks.learning_job]`. *(LI1.1)* |
| Faixa da entrevista por cima do histórico | `strip_rect` (60 px) cobre o topo de `L.history`; reservar `STRIP_H` no layout durante a simulação, se incomodar. *(LI2.2)* |
| Moldes `{jogo}` da espera nunca usados | `TurnContext` não tem jogo em foco, então o turno passa `jogo=None` e os moldes com `{jogo}` não saem. Pôr o jogo em foco no contexto. *(E0.1, E2.3)* |
| Coluna `primeiro_som` no `tools/perf.py` | Não feita (fora do Escreve); a E4.1 precisa dela antes da medida. *(E2.3)* |
| Teto de 780 tokens do `persona.md` | A persona está em 779 tokens estimados; a próxima linha quebra o `test_prompt.py`. Subir o teto (ou enxugar) antes da próxima mudança. *(E2.1, E3.1b)* |
| `registrar_sessao` do audiolivro | O registro A10 não é chamado por ninguém. *(A2.3)* |
| Música volta antes do fim do áudio | O gerador da leitura acaba antes do áudio das últimas frases (o `say_parts` pré-sintetiza); esperar o fim do áudio. *(A2.3)* |
| Frases soltas do audiolivro | Sem leitura, "chega" vira pergunta de `book.stop` e "lê mais rápido" vira `book.read` ("não achei esse livro"); legenda de call sem en-gb. *(A2.2, A2.3)* |
| Gestos do overlay diferentes do HUD | `Gestos` usa `LONG_S = 0,6` / `DRAG_PX = 18`; o HUD usa `0,8` / `40`. Igualar (o comentário "copiados" não bate). *(O1.1)* |
| Overlay sem descobrir o monitor do jogo | `tela_jogo` = monitor principal (descobrir exigiria D-Bus do KWin); `reacoes_relatorio.py` pode não aceitar caminho do `reacoes-overlay.jsonl`. *(O0.1, O3.2)* |
| `magi-elo parear` sem script | O design da Ayanami fala em `magi-elo parear`, mas a Y6.6 só prevê `uv run python -m magi.elo.parear` (sem script no `pyproject`). Alinhar o design/GUIA ou criar o script quando a Y6.6 entrar. *(Y6.6, design §12)* |

## 15. Ordem sugerida

1. **Pedro valida o que está pronto** e reabre o HUD (seção 9): overlay, audiolivro, espera viva,
   learning imersivo e o placar da vida; decide o que está na seção 10.
2. **Rodada de limpeza** das sobras (seção 14), por agentes, sem o Pedro.
3. **Ayanami ondas 1–3** (sem o Pedro: contratos, esqueleto, spikes locais, drivers das TVs com
   dublês) enquanto ele confirma o node 2 (SSH) e o Tailscale.
4. Depois, **`condessa-angulos`** (o código; a arte é do Pedro) e, com o "ok" dele,
   **`condessa-engine`** e **FIFA** (`fifa-lances`).
