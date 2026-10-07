# Tarefas — Condessa Learning Mode

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **uma sessão de agente** com janela de até 128k tokens, conduzida pelo Pedro
com o Claude Code (como `specs/condessa-engine/tasks.md`). Fases seguem o roadmap do PDF §14:
**LM1–LM4 = MVP**; fases 5–8 são FUTURE e **não têm tarefas** (lista no fim).

## Regras para o agente

1. **Leia só o pacote de contexto da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`,
   requisitos pelo ID do PDF (`SEL-001`) ou `LM-nnn`.
2. **Orçamento planejado ≤ 60k tokens** por tarefa; o resto da janela de 128k é margem.
3. **Contratos primeiro:** módulos de outras tarefas são usados pelo que está em
   `magi/learning/contracts.py` (LM0.1) e pela tabela de mensagens de spec §6, sem ler o código deles.
4. **Arquivos grandes por trecho:** `grep -n` + leitura por intervalo. Nunca leia inteiros
   `hud/gamerhud.py` (~2,3k linhas), `hud/wired/main_screen.py` (~1,2k), `magi/core/assemble.py`,
   `magi/common/contracts.py`; as tarefas dizem o que abrir.
5. **Saída de testes curta:** `uv run pytest -q -x tests/learning/<arquivo>`.
6. **Banco compartilhado:** nunca `docker compose down`, `docker rm`, `DROP` ou `TRUNCATE` no
   `magi-pg`. Testes de banco só em schema próprio (`migrate.py --schema learning_test`); o schema
   de teste pode ser apagado **só** por ele mesmo (`DROP SCHEMA learning_test CASCADE` no teardown
   do teste é a única exceção, e nunca em `public`).
7. **Nada de chamada real a LLM em teste:** só `FakeModel`. Chamada real só nas tarefas marcadas
   *(gasta API)* e com o Pedro ciente.
8. **Não remover nada do HUD/MAGI existente** (PDF §13 "Safe Modifications"); o Learning Mode é
   aditivo.
9. **No Feature Creep** (PDF §13): nada de XP, badges, lições, Ask Condessa, Learning Profile real.
   O cartão `LAST SESSION` não tem nota/streak; a lista de palavras salvas não tem quiz/revisão; o
   tema é assunto, não roteiro.
10. **Uma tarefa = um commit**, com o ID da tarefa na mensagem.

Estimativa: 1k tokens ≈ 3,5 KB de texto em português ou 4 KB de código. Tamanhos: `design.md`
~11k, `spec.md` ~9k, `requirements.md` ~6,5k; uma seção 0,3–1,5k.

Formato de cada tarefa:
**Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** (critério verificável) ·
**Paralelo** (com quais pode rodar ao mesmo tempo).

**Decisões:** P1 e P8 decididas pelo Pedro em 2026-10-07 — a UI é a tela `view = "learning"`
dentro do `gamerhud` (`hud/wired/learning_*.py`, QPainter, seleção feita pelo HUD), e o modo entra/sai
por botão no HUD e por voz (PT e EN). Ainda abertas: P4 (banco) muda só o backend padrão em LM1.1;
P2 (modelo) só afeta LM4.4; P10 (monitor do HUD) só as resoluções de teste/captura. Ver design §16.
**Acréscimos do MVP (Pedro, 2026-10-07):** resumo ao sair (LM-011 → LM4.5, LM4.6), guardar palavra
(LM-012 → LM3.5), tema da sessão (LM-013/LM-014 → LM1.8, LM1.9) e retrato da tela learning do
tamanho do painel, `MASCOT_MAIN` 302 de altura na base 1920 (LM-015 → LM1.5). Abertas novas: P11–P14.

---

## Fase LM0 — Base e spikes

- [ ] **LM0.1 Pacote, contratos e config** — `magi/learning/` com `contracts.py` (enums e dataclasses de spec §3, inclusive `Topic`, `TopicContext`, `SessionSummary` e `SavedWord`; serialização JSON ida e volta), seção `[learning]` (com `default_topic`, `topic_picker_s`, `summary_show_s`) e chaves `[tasks] learning_*` em `config.example.toml` com leitura tipada. *(spec §2–§3, ENG-002, LM-008, LM-009)*
  - Lê: design §2–§3, spec §1–§3, `config.example.toml` (só `[tasks]` e `[speech]`, por grep)
  - Escreve: `magi/learning/__init__.py`, `magi/learning/contracts.py`, `magi/learning/config.py`, `config.example.toml`, `tests/learning/test_contracts.py`
  - Depende de: —
  - Orçamento: ~25k
  - Pronto: `uv run pytest -q tests/learning/test_contracts.py` e `uv run ruff check magi/learning` verdes; docstring de cada contrato cita o ID do requisito.
  - Paralelo: LM0.2, LM0.3

- [ ] **LM0.2 Spike: socket do HUD com tipos novos** — confirmar o que o cliente do `gamerhud` faz ao receber tipo desconhecido (`decode_hud` levanta `HudDecodeError`): ignora ou derruba? Decidir entre (a) `lm_hello` + envio só para clientes Learning ou (b) decoder tolerante. Registrar a resposta no fim de design §9 (texto curto). Sem código de produção.
  - Lê: design §9, spec §6, `magi/common/events.py` (`decode_hud` e `_HUD_DECODERS`), `magi/core/hud_client.py` (classe `HudServer`), `hud/hud_bridge.py` (só o laço de leitura, por grep `decode_hud`)
  - Escreve: `specs/learning-mode/design.md` (§9, nota)
  - Depende de: —
  - Orçamento: ~20k
  - Pronto: nota com a opção escolhida e o trecho que a justifica (arquivo:linha).
  - Paralelo: LM0.1, LM0.3

- [ ] **LM0.3 Spike: seleção e hit-test dentro do gamerhud** — script descartável em `scratch/` que abre um `QWidget` com as **mesmas flags do `gamerhud`** (`FramelessWindowHint | WindowDoesNotAcceptFocus`, `WA_OpaquePaintEvent`) no monitor do HUD (`GAMERHUD_SCREEN`), pinta 3 mensagens do exemplo do PDF com fontes de `hud/wired/fonts.py` e cores de `theme.py` usando um protótipo de quebra com caixa por palavra (`QFontMetricsF.horizontalAdvance`). Medir: (1) clique cai na palavra certa, arrasto estende por palavra, duplo clique pega a frase; (2) repintar só o retângulo do histórico/sobreposição leva < 16 ms; (3) menu QPainter ancorado na última palavra; (4) **entrada de texto**: `QLineEdit` filho + tirar/devolver `WindowDoesNotAcceptFocus` em tempo de execução no KWin (pisca? perde posição? recebe teclado?) × reserva `Qt.Tool` só com o `QLineEdit` (design §4.3); (5) qual monitor e resolução é o `DP-1` (P10). Gravar 2 capturas.
  - Lê: design §4 (inteira, com §4.1–§4.4), §16 P1/P10, `hud/wired/theme.py` (constantes), `hud/wired/fonts.py` (por grep `def `), `hud/wired/main_screen.py` (classe `Screen`, linhas ~423–560: `groups`, `group_key`, `paint`, `dirty_regions`, `scale`), `hud/gamerhud.py` (só `setWindowFlags` e `mousePressEvent`, por grep)
  - Escreve: `scratch/learning_spike.py` (não versionado), nota curta no fim de design §4.2 (hit-test/ms) e §4.3 (caminho da entrada escolhido) e resposta factual em §16 P10
  - Depende de: — (P1 já decidida)
  - Orçamento: ~40k
  - Pronto: capturas + nota "hit-test ok / repintura N ms / entrada: filho com troca de flag | reserva Tool / monitor WxH"; se nenhum caminho de entrada funcionar, parar e levar ao Pedro antes de LM1.6.
  - Paralelo: LM0.1, LM0.2

## Fase LM1 — Interface core e conversa primeiro (PDF Phase 1)

- [ ] **LM1.1 Migração e repositório** — `003_learning.sql` exatamente como spec §8 (aditiva, sem `vector`; inclui `learning_saved_words` e as colunas `topic`/`topics`/`summary` de `learning_sessions`); `magi/learning/repo.py` com interface `LearningRepo` e dois backends (`PostgresRepo` via `magi/memory/conn.py`, `JsonlRepo`); gravação em memória quando o banco cai (até 500); métodos `set_topic`, `session_stats`, `save_summary`, `save_word`, `unsave_word`, `saved_norms` (assim LM1.8/LM3.5/LM4.5 não mexem em `repo.py`). *(DAT-001..003, MEM-002, LM-010, LM-011, LM-012, spec §8, §10, §10.1–§10.3)*
  - Lê: design §8, spec §3, §8, §10–§10.3, `magi/memory/migrate.py` (docstring), `magi/memory/conn.py` (por grep `def `), `magi/memory/costs_repo.py` (só o padrão de um método)
  - Escreve: `magi/memory/migrations/003_learning.sql`, `magi/learning/repo.py`, `tests/learning/test_repo.py`, `tests/learning/test_migration.py`
  - Depende de: LM0.1
  - Orçamento: ~40k
  - Pronto: CA-15 e CA-16 verdes em schema `learning_test`, mais a parte de repo do CA-22 (um ativo por `norm`, desfazer por `removed_at`); `grep -Ei 'drop|vector' 003_learning.sql` vazio. **Não** aplicar no `public` nesta tarefa (o Pedro aplica com `uv run python -m magi.memory.migrate`).
  - Paralelo: LM1.2, LM2.1, LM3.1

- [ ] **LM1.2 Mensagens `lm_*` no socket** — classes das mensagens de spec §6 (inclusive `lm_topic`, `lm_save`, `lm_saved`, `lm_summary`) no padrão de `magi/common/contracts.py`, decoders, e roteamento no `HudServer` conforme a opção do LM0.2 (só conexões que mandaram `lm_hello` recebem `lm_*`; fora do modo só passa `lm_summary`). *(LM-005, spec §6)*
  - Lê: design §9, spec §6, nota do LM0.2, `magi/common/contracts.py` (linhas das classes `_HudMsg`, `SubtitleMsg`, `CmdMsg`, por grep), `magi/common/events.py` (`decode_hud`), `magi/core/hud_client.py`
  - Escreve: `magi/common/contracts.py`, `magi/common/events.py`, `magi/core/hud_client.py`, `tests/learning/test_socket.py`
  - Depende de: LM0.1, LM0.2
  - Orçamento: ~35k
  - Pronto: CA-18 verde; testes antigos de `tests/core` e `tests/hud` que tocam o socket continuam verdes.
  - Paralelo: LM1.1, LM2.1, LM3.1

- [ ] **LM1.3 Sessão, texto e histórico no núcleo** — `magi/learning/session.py` (IDs `LS-`, retomada, fim por inatividade); `magi/learning/wiring.py` com um único ponto de registro dos handlers `lm_*` (as próximas tarefas só acrescentam handlers lá); `lm_say` → `Transcript.raw` → `TurnPipeline.respond`; gancho **depois** da entrega que grava/publica as duas `lm_msg` (voz: `heard` em `text`, `final` em `text_final`); `speak_replies`. *(LM-001..LM-004, CNV-001, spec §4, §10)*
  - Lê: design §5, §10, spec §4, §6, §10, `magi/core/turn.py` (linhas 200–420: `TurnPipeline.respond`, `_respond`, `_save_turn`), `magi/core/service.py` (onde o `HudServer` recebe `cmd`, por grep `on_command`), contrato de `repo.py` (LM1.1)
  - Escreve: `magi/learning/session.py`, `magi/learning/wiring.py`, `magi/core/turn.py` (só o gancho), `magi/core/service.py` (só registrar `wiring`), `tests/learning/test_conversation.py`, `tests/learning/test_session.py`
  - Depende de: LM1.1, LM1.2
  - Orçamento: ~55k
  - Pronto: CA-05 verde; testes de `tests/core/test_turn*.py` continuam verdes; com `[learning] enabled = false` nada muda (teste).
  - Paralelo: LM1.5, LM3.2

- [ ] **LM1.4 Entrar/sair por voz e persona** — intents `learning.start` e `learning.stop` em `magi/core/intents.yaml` com as frases **em português e em inglês** da tabela de design §10 (a fala chega em PT ou EN, STT com idioma automático); ids novos em `contracts.IntentId`; ação que liga/desliga o modo (mesmo caminho do `lm_mode` do botão: cria/retoma ou fecha a sessão e confirma `lm_mode` aos clientes Learning, `end_reason = "voice"`), registrada onde as ações atuais registram seus `IntentId` (achar por grep); respostas curtas em `i18n/en-gb.yaml`; bloco de persona `prompts/persona.md` acrescentado ao system prompt só com sessão ativa. Sem comando de terminal e sem atalho global. *(CNV-001, CNV-002, LM-005, design §5, §10, P8)*
  - Lê: design §5, §10, spec §4 (item 4), §10, §11, `magi/core/intents.yaml` (cabeçalho + 2 intents de exemplo), `magi/core/router.py` (docstring e a função de pontuação, por grep `token_set_ratio`), `magi/common/contracts.py` (classe `IntentId`), `magi/core/i18n/__init__.py` (por grep `def `), `magi/core/assemble.py` (linhas ~520–540, onde o agente é montado), API de `session.py` (LM1.3)
  - Escreve: `magi/core/intents.yaml`, `magi/common/contracts.py` (só `IntentId`), `magi/core/i18n/en-gb.yaml`, `magi/learning/intent_action.py`, o arquivo de registro das ações (só uma linha), `magi/learning/prompts/persona.md`, `magi/learning/persona.py`, `magi/core/assemble.py` (só a injeção), `tests/learning/test_persona.py`, `tests/learning/test_learning_intents.py`
  - Depende de: LM1.3
  - Orçamento: ~45k
  - Pronto: CA-06 e CA-05b verdes (frases PT e EN casam; frases de conversa com "session"/"class" não casam); testes atuais do roteador continuam verdes; nenhum atalho global (KGlobalAccel) nem `magi/cli/learning.py`.
  - Paralelo: LM1.6, LM3.3 (arquivos distintos: LM3.3 só mexe em `magi/learning/engine.py`/`wiring.py`)

- [ ] **LM1.5 Tela learning: layout e painéis secundários** — `hud/wired/learning_layout.py` (puro: 3 colunas + topo + rodapé + retângulo da entrada a partir do tamanho, coluna central ≤ ~110 caracteres; acrescenta ao arquivo criado no LM2.1), `hud/wired/learning_screen.py` com `LearningScreen(Screen)` no estilo de `standby_screen.py`: `draw_static`, `groups()`, `group_key()`, `draw_group()` para `header`, `condessa` (retrato reusando o `mascot` do `WiredUI` **no mesmo tamanho do painel gamer: `MASCOT_MAIN.size()` importado de `main_screen.py`, 302 de altura na base 1920 (antes 252); coluna direita com largura mínima para caber, design §4 "Retrato"**, rótulo de estado pela tabela spec §7, nível `B2 / CONVERSATION`), `system` (MAGI SYSTEM recolhível, `TEXT_DIM`) e `footer`; botão `[ END SESSION // 終了 ]` desenhado no `header` com alvo `"learning"` no `hit_test` (a ação é ligada no LM1.7); grupos `history`/`input`/`obs`/`overlay`/`topic` existem como retângulos vazios. `WiredUI.screen("learning")` em `integration.py` e `gamerhud.py` aceitando `view = "learning"` (só pintura; sem mouse ainda). *(PRN-001, PRN-003, UI-001, UI-002, SYS-001, SYS-002, RNF-06, LM-015, P1)*
  - Lê: design §4, §4.1, §7, spec §7, nota do LM0.3, `hud/wired/standby_screen.py` (inteiro, ~240 linhas: é o molde), `hud/wired/main_screen.py` (classe `Screen`, por grep `def `; `MASCOT_MAIN`, por grep), `hud/wired/theme.py, `hud/wired/kit.py` (assinaturas por grep), `hud/wired/integration.py` (`screen`, `hit`), `hud/gamerhud.py` (só onde `self.view` é lido, por grep `self.view`)
  - Escreve: `hud/wired/learning_layout.py`, `hud/wired/learning_screen.py`, `hud/wired/integration.py` (só `screen`), `hud/gamerhud.py` (só aceitar a view), `tests/learning/test_layout.py`, `tests/learning/test_state_label.py`, `tests/learning/test_learning_screen.py` (offscreen: pinta em `QImage` sem erro; `group_key` muda só quando o dado do grupo muda)
  - Depende de: LM0.3, LM2.1
  - Orçamento: ~55k
  - Pronto: CA-17 e CA-26 verdes; parte de layout do CA-11 verde; `tests/hud` antigos verdes; captura offscreen da tela com dados fixos do exemplo do PDF.
  - Paralelo: LM1.3, LM3.2

- [ ] **LM1.6 Tela learning: conversa, entrada e bridge** — `hud/wired/learning_model.py` (puro: estado da tela alimentado por **todos** os `lm_*` de spec §6 — `lm_session`/`lm_msg`/`lm_mode`/`lm_obs`/`lm_result` por `id`/`lm_topic`/`lm_saved`/`lm_summary` — mais `state`/`mouth`, para LM3.4/LM4.3 não precisarem mexer nele; ordem das mensagens, rolagem, mensagem "em fala" revelada com a lógica de `hud/speech_caption.py`); grupos `history` (pinta as caixas de `learning_text.wrap`, rótulos CONDESSA/YOU) e `input` (moldura, onda de áudio por `mouth`, `STATUS // CONNECTED/DISCONNECTED`) na `LearningScreen`; **entrada de texto** pelo caminho escolhido no LM0.3 (`QLineEdit` filho posicionado no retângulo `input` × escala, visível só na view learning, troca de `WindowDoesNotAcceptFocus` ao entrar/sair — ou a reserva `Qt.Tool`), Enter → `lm_say`; no `gamerhud`, um despachante único: com `view == "learning"`, press/move/release/duplo clique/roda vão para `WiredUI.learning_mouse(kind, pos)` (as próximas tarefas só mexem na `LearningScreen`); `hud/hud_bridge.py` manda `lm_hello` ao conectar, entrega todos os `lm_*` ao `learning_model` e expõe `send_lm(tipo, campos)` (`lm_say`, `lm_mode`, `lm_cfg`, `lm_action`, `lm_topic`, `lm_save`). *(LM-001..LM-004, CTX-003, P1)*
  - Lê: design §4.1–§4.3, §5, §9, spec §4, §6, §10, nota do LM0.3, `hud/speech_caption.py` (docstring + API pública por grep `def `), `hud/hud_bridge.py` (laço de leitura e `send_cmd`, por grep), `hud/gamerhud.py` (eventos de mouse ~1470–1530 e `setWindowFlags`), contratos `lm_*` (LM1.2), API de `learning_text.py` (LM2.1) e `learning_screen.py` (LM1.5) por grep `def `
  - Escreve: `hud/wired/learning_model.py`, `hud/wired/learning_screen.py` (grupos `history`/`input`), `hud/wired/integration.py` (só `learning_mouse`), `hud/gamerhud.py` (despachante de mouse + entrada), `hud/hud_bridge.py`, `tests/learning/test_learning_model.py`, `tests/learning/test_bridge.py`
  - Depende de: LM1.2, LM1.5, LM2.1
  - Orçamento: ~60k
  - Pronto: testes com servidor falso (ordem de `lm_msg`, reconexão, `lm_hello` só do `gamerhud`) verdes; `tests/hud` antigos verdes; manual: com o núcleo rodando e a view forçada em `learning`, uma frase por voz e uma digitada aparecem no histórico e a da Condessa revela em sincronia; painel e espera continuam sem foco de teclado.
  - Paralelo: LM1.4, LM3.3

- [ ] **LM1.7 Botão LEARNING e troca de tela** — botão `[ LEARNING // 学習 ]` no painel (`MainScreen`, coluna da Condessa abaixo de `TALK`) e na espera (`StandbyScreen`, linha acima de `y_rule2`), `[ END SESSION // 終了 ]` já desenhado pelo LM1.5 no cabeçalho da `LearningScreen` (design §4.4), todos com alvo `"learning"` no `hit_test`; `gamerhud.wired_click("learning")` → `send_lm("lm_mode", on=…)`; ao receber `lm_mode` confirmado, guarda a view atual (`full`/`idle`) e vai para `learning` com a cortina; `lm_mode off` volta à view guardada; Meta+M durante o modo só muda a view de retorno; com o núcleo fora, rodapé mostra `DISCONNECTED` e nada muda. Lógica de troca pura (`learning_toggle(view_atual, retorno, msg) -> (view, retorno)`) em `integration.py`. *(LM-005, P8)*
  - Lê: design §4.4, §10, spec §6 (`lm_mode`), §10, §11, `hud/wired/main_screen.py` (`hit_test`, `TALK`, `SIDE_X`, por grep), `hud/wired/standby_screen.py` (`hit_test`/`groups`, `y_rule2`), `hud/wired/integration.py` (`hit`), `hud/gamerhud.py` (`wired_click` e a troca de view ~1240–1400, por grep `new_view`)
  - Escreve: `hud/wired/main_screen.py` (só o botão), `hud/wired/standby_screen.py` (só o botão), `hud/wired/integration.py` (só `hit` + `learning_toggle`), `hud/gamerhud.py` (só `wired_click` e a troca), `tests/learning/test_learning_toggle.py`
  - Depende de: LM1.5, LM1.6
  - Orçamento: ~40k
  - Pronto: CA-18b verde; `tests/hud` antigos verdes; manual: botão no painel e na espera entra no modo, END volta para a tela de onde saiu; voz (LM1.4) faz o mesmo.
  - Paralelo: LM2.2, LM4.1 (LM1.7 não escreve `learning_screen.py`)

- [ ] **LM1.8 Tema da sessão no núcleo** — `magi/learning/topic.py` (`build(requested) -> TopicContext`, spec §10.1: free/interview/game/news, fallback com `detail`, bloco ≤ 1500, nada de LLM/rede, news **sem** `mark_delivered`); `prompts/topics/{interview,game,news}.md`; tema atual e histórico em `session.py` (`repo.set_topic`); handler `lm_topic` em `wiring.py` (confirma a todos os clientes Learning); `persona.py` compõe persona + `<topic_context>`; abertura do tema (P11) quando o estado volta a `listening`, cancelada se o Pedro falar antes; intents `learning.topic.{free,interview,game,news}` com as frases PT/EN de design §10, **só com sessão ativa** (registro condicional ou filtro, o que o roteador permitir), mesma ação do botão; respostas curtas em `i18n/en-gb.yaml`. *(LM-013, LM-014, design §5.1, §10)*
  - Lê: design §5.1, §10, §16 P11/P12/P14, spec §3 (`Topic`, `TopicContext`), §6 (`lm_topic`), §10.1, §11, `magi/core/game_context.py` (classes `RunningGame`, `GameWatcher`, por grep `def `), `magi/agent/tools/steam.py` (`describe`, `SteamGameTool.__init__`), `magi/agent/tools/news.py` (`NewsQuery.__init__`/`whats_new`, linhas ~185–232) e o `NewsRepo` (por grep `async def`), `magi/core/assemble.py` (onde `GameWatcher`/`NewsQuery` são criados, por grep), APIs de `session.py`, `persona.py`, `intent_action.py`, `wiring.py` por grep `def `
  - Escreve: `magi/learning/topic.py`, `magi/learning/prompts/topics/*.md`, `magi/learning/session.py` (só tema), `magi/learning/wiring.py` (só `lm_topic`), `magi/learning/persona.py` (só compor o bloco), `magi/learning/intent_action.py`, `magi/core/intents.yaml`, `magi/common/contracts.py` (só `IntentId`), `magi/core/i18n/en-gb.yaml`, `magi/core/assemble.py` (só passar `GameWatcher`/Steam/`NewsRepo` ao `topic`), `tests/learning/test_topic.py`, `tests/learning/test_learning_intents.py` (casos novos)
  - Depende de: LM1.4 (persona, intents), LM1.3
  - Orçamento: ~55k
  - Pronto: CA-23 e CA-24 verdes; CA-05b e testes atuais do roteador/notícias/jogo continuam verdes; fora da sessão "vamos falar do jogo" segue o caminho antigo (teste).
  - Paralelo: LM3.4, LM4.2, LM4.3

- [ ] **LM1.9 Seletor de tema na tela** — `hud/wired/learning_topic.py` (puro + pintura: chip `TOPIC // … ▾`, lista de 4 itens ancorada no chip, item sob o mouse, abre sozinho só em sessão nova, fecha em `topic_picker_s`/clique fora/Esc/mensagem, `detail` do fallback no chip); grupo `topic` na `LearningScreen` e clique nele → `send_lm("lm_topic", topic=…)`; o chip mostra só o tema **confirmado** pelo núcleo (`lm_topic` no `learning_model`). *(LM-013, design §4.5)*
  - Lê: design §4, §4.5, spec §6 (`lm_topic`, `lm_session`), §10.1 itens 1–2, §11, APIs de `learning_screen.py`, `learning_model.py`, `learning_layout.py` por grep `def `
  - Escreve: `hud/wired/learning_topic.py`, `hud/wired/learning_screen.py` (só grupo `topic` e clique), `tests/learning/test_topic_view.py`
  - Depende de: LM1.6 (pode usar `lm_topic` falso antes do LM1.8)
  - Orçamento: ~35k
  - Pronto: CA-25 verde; `tests/hud` antigos verdes; manual: ao entrar, a lista abre, some em 10 s sem escolha e não cobre a última mensagem por mais que o tempo dela aberta.
  - Paralelo: LM3.5, LM4.5, LM4.6

## Fase LM2 — Seleção contextual (PDF Phase 2)

- [ ] **LM2.1 Lógica pura de texto, hit-test, seleção e posição do menu** — `hud/wired/learning_text.py` sem Qt: `wrap(messages, width, measure)` → linhas e `WordBox(message_id, start, end, rect)` com medidor injetado; `hit(boxes, ponto)`; clique = palavra, arrasto = intervalo de palavras, duplo clique = frase; recorte à mensagem de início; disponibilidade por ação (spec §5, tabela; Improve desabilitado em mensagem da Condessa — P7); `hud/wired/learning_layout.py` com só `menu_rect`/`bubble_rect` (sem cobrir a seleção nem sair da tela). *(SEL-001, SEL-002, VOC-002, P1, P7)*
  - Lê: spec §5 (disponibilidade e regra de seleção), §11, design §4, §4.2, contrato `Selection` (LM0.1), nota do LM0.3
  - Escreve: `hud/wired/learning_text.py`, `hud/wired/learning_layout.py` (só menu/balão), `tests/learning/test_learning_text.py`, `tests/learning/test_selection.py`, `tests/learning/test_menu_layout.py`
  - Depende de: LM0.1, LM0.3
  - Orçamento: ~35k
  - Pronto: CA-10, CA-10b e a parte de menu do CA-11 verdes, tudo sem importar PySide6.
  - Paralelo: LM1.1, LM1.2, LM3.1

- [ ] **LM2.2 Seleção na tela, menu e balão (com dados falsos)** — na `LearningScreen`: `learning_mouse` aplica `learning_text` (destaque lilás translúcido no grupo `history`; mensagem em fala não abre menu) e, ao soltar, abre o grupo `overlay`; `hud/wired/learning_overlay.py` desenha em QPainter o menu (`selected: "…"`, ✦ Improve, ? Explain, ⇄ Translate, ◇ Vocabulary; hover; ↑↓/Enter/Esc só se a entrada do LM0.3 deixou o HUD com foco) e o balão (carregando ≤ 100 ms, resultado por `kind`, erro com retry, "more ▸" do Vocabulary); fecha ao clicar fora, Esc, nova seleção ou rolagem; repinta só `history`/`overlay`. Resultados de um provedor falso local. *(SEL-001..003, IMP-001, VOC-002, LM-007, RNF-02, RNF-03)*
  - Lê: design §4, §4.2, spec §5 (schemas e balão), §11, APIs de `learning_text.py`/`learning_layout.py` (LM2.1), `learning_screen.py` e `learning_model.py` (LM1.6) por grep `def `
  - Escreve: `hud/wired/learning_overlay.py`, `hud/wired/learning_screen.py` (só seleção/`overlay`), `tests/learning/test_bubble_model.py` (lógica pura de formatação por kind e itens do menu)
  - Depende de: LM1.6, LM2.1
  - Orçamento: ~50k
  - Pronto: teste de formatação verde; manual com dados fixos: clicar e arrastar "I make" mostra o menu e o balão Improve do mockup em ≤ 50 ms após soltar; duplo clique pega a frase.
  - Paralelo: LM1.7, LM4.1

## Fase LM3 — Ações ativas (PDF Phase 3)

- [ ] **LM3.1 Modelo e orçamento** — protocolo `LearningModel`, `OpenAIModel` sobre os providers atuais (lendo `[tasks] learning_*`), `FakeModel` (respostas gravadas por chave), verificação de teto e registro em `costs` com rótulos `learning_actions`/`learning_observe`. *(ENG-002, LM-006, spec §2–§3)*
  - Lê: design §6 (Modelo), spec §2, §3 (`LearningModel`), `magi/core/budget.py` (por grep `def `), `magi/memory/costs_repo.py` (por grep `def `), `magi/providers/` (só o provider OpenAI de chat, por grep `class `)
  - Escreve: `magi/learning/model.py`, `magi/learning/budget.py`, `tests/learning/test_model.py`
  - Depende de: LM0.1
  - Orçamento: ~40k
  - Pronto: CA-04 verde; parte de CA-13 (recusa sem chamada) verde.
  - Paralelo: LM1.1, LM1.2, LM2.1

- [ ] **LM3.2 Analisadores e prompts** — `analyzers/improve.py`, `explain.py`, `translate.py`, `vocabulary.py` + `prompts/*.md` (texto do usuário em bloco `<conversation>` como dado; aviso de transcrição de voz; `kind = none` permitido) + validação de schema e cortes de tamanho (spec §5). *(IMP-001..003, EXP-001, TRA-001, VOC-001, VOC-002, LM-008)*
  - Lê: spec §5 (inteira), design §6, contrato `LearningModel` (LM3.1)
  - Escreve: `magi/learning/analyzers/__init__.py`, os 4 analisadores, `magi/learning/prompts/{improve,explain,translate,vocabulary}.md`, `tests/learning/test_analyzers.py`, `tests/learning/fixtures/*.json`
  - Depende de: LM3.1
  - Orçamento: ~50k
  - Pronto: CA-07, CA-08, CA-09 (parte de schema) verdes com `FakeModel`. Opcional *(gasta API, ~US$ 0,01)*: rodar os 4 analisadores uma vez no exemplo do PDF e colar as saídas no PR.
  - Paralelo: LM1.3, LM1.5

- [ ] **LM3.3 Learning Engine — fila de ações** — `engine.py`: fila de ações (prioridade alta), `Semaphore(1)`, cache por (`message_id`, `kind`, intervalo), cancelamento da anterior do mesmo cliente, 1 retry só em `invalid`, gravação em `learning_action_results`; handlers `lm_action` → `lm_result` registrados em `wiring.py`. *(ENG-001, LM-006, LM-007, spec §5 "Ciclo")*
  - Lê: design §6, spec §5 (Ciclo), §6, §11, contratos de `repo.py`, `model.py`, analisadores, `wiring.py` (APIs por grep `def `)
  - Escreve: `magi/learning/engine.py`, `magi/learning/wiring.py` (só handlers de ação), `tests/learning/test_engine.py`
  - Depende de: LM1.1, LM1.3, LM3.2
  - Orçamento: ~50k
  - Pronto: CA-12, CA-13 verdes; teste de cache (2ª ação igual não chama o modelo).
  - Paralelo: LM1.4, LM1.6

- [ ] **LM3.4 Balão com resultados reais** — trocar o provedor falso do LM2.2 por `lm_action`/`lm_result` via `hud_bridge`; correlação por `id`; "retry"; timeout de UI 12 s. *(SEL-001..003, IMP-*, EXP-001, TRA-001, VOC-*, LM-007)*
  - Lê: spec §5–§6, APIs de `learning_overlay.py`, `learning_model.py`, `hud_bridge.send_lm` (por grep `def `)
  - Escreve: `hud/wired/learning_overlay.py`, `tests/learning/test_overlay_action.py` (correlação por `id`, retry, timeout de 12 s — lógica pura)
  - Depende de: LM2.2, LM3.3
  - Orçamento: ~35k
  - Pronto: `test_overlay_action.py` verde; manual *(gasta API)*: as 4 ações no exemplo do PDF respondem em ≤ 4 s.
  - Paralelo: LM4.2, LM4.3

- [ ] **LM3.5 Guardar palavra (★ no Vocabulary)** — núcleo: handler `lm_save` em `wiring.py` (resolve pelo `action_id`, recusa se não for vocabulary `ok`, `repo.save_word`/`unsave_word`, responde `lm_saved`); `engine.py` manda `lm_saved` do `norm` depois de cada `lm_result` de vocabulary (inclusive cache). HUD: `☆ SAVE`/`★ SAVED` no balão Vocabulary em `learning_overlay.py`, marca otimista desfeita se `lm_saved` não vier em 3 s ou vier contrário ("not saved"); estado por `norm` lido do `learning_model` (o LM1.6 já guarda `lm_saved`; esta tarefa não o altera). *(LM-012, spec §10.3, design §11.1)*
  - Lê: design §11.1, spec §3 (`SavedWord`), §6 (`lm_save`, `lm_saved`), §8 (`learning_saved_words`), §10.3, §11, APIs de `repo.py`, `engine.py`, `wiring.py`, `learning_overlay.py`, `learning_model.py` por grep `def `
  - Escreve: `magi/learning/wiring.py` (só `lm_save`), `magi/learning/engine.py` (só `lm_saved` após vocabulary), `hud/wired/learning_overlay.py` (só a estrela), `tests/learning/test_saved_words.py`
  - Depende de: LM3.4, LM1.1
  - Orçamento: ~40k
  - Pronto: CA-22 verde; manual: ★ em "authentication", fechar e reabrir o balão mostra ★ marcada; desfazer e guardar de novo gera linha nova e só uma ativa no banco.
  - Paralelo: LM1.9, LM4.5, LM4.6

## Fase LM4 — Engine assíncrono de observações (PDF Phase 4)

- [ ] **LM4.1 Bus, gate e observações** — `bus.py` (fila limitada, `put_nowait`, descarta o mais antigo), gate de estado (só `listening`/`sleeping`/`followup`), `analyzers/observe.py` + `prompts/observe.md`, derivação de `recurring` (2ª ocorrência do `rule_key` na sessão), limite diário, `lm_obs` com a lista inteira. *(CNV-003, ENG-001, ENG-002, OBS-002, MEM-002, spec §9)*
  - Lê: design §6, §11, spec §9, §11, APIs de `engine.py`, `repo.py`, `model.py`, `wiring.py`
  - Escreve: `magi/learning/bus.py`, `magi/learning/analyzers/observe.py`, `magi/learning/prompts/observe.md`, `magi/learning/engine.py` (fila de observação), `magi/learning/wiring.py` (só `publish` → bus), `tests/learning/test_bus.py`, `tests/learning/test_observations.py`, `tests/learning/test_engine.py::test_gate`
  - Depende de: LM3.3
  - Orçamento: ~50k
  - Pronto: CA-02, CA-03, CA-14 verdes.
  - Paralelo: LM2.2, LM4.3

- [ ] **LM4.2 Medição de latência** — teste CA-01 (200 turnos falsos, engine ligado × desligado) e medição real curta com o núcleo (10 turnos por texto) registrada no PR. *(ENG-001, RNF-01)*
  - Lê: spec §12 (CA-01), design §6, §15, `magi/core/turn.py` (linhas do gancho do LM1.3)
  - Escreve: `tests/learning/test_latency.py`
  - Depende de: LM1.3, LM4.1
  - Orçamento: ~30k
  - Pronto: CA-01 verde; se falhar, a tarefa para e propõe tirar o worker para processo à parte (design §1), sem implementar.
  - Paralelo: LM3.4, LM4.3

- [ ] **LM4.3 Indicador e drawer de observações** — `hud/wired/learning_obs.py` (grupo `obs` da `LearningScreen`, QPainter): `OBSERVATIONS [nn] ▾` recolhido por padrão; drawer na coluna direita com VOCABULARY / GRAMMAR / RECURRING; clique rola até a mensagem e destaca uma vez; contador atualiza sem animação piscante; botão `[ VIEW LEARNING PROFILE ]` desabilitado ("coming later"). Lógica de agrupamento pura e testada. *(OBS-001, OBS-002, PRN-003, PRN-004, UI-003)*
  - Lê: design §4.1, §11, spec §6 (`lm_obs`), §9 (itens 4–6), APIs de `learning_model.py` (rolar/destacar) e `learning_screen.py` (grupos, `learning_mouse`) por grep `def `
  - Escreve: `hud/wired/learning_obs.py`, `hud/wired/learning_screen.py` (só grupo `obs` e clique nele), `tests/learning/test_obs_view.py`
  - Depende de: LM1.6 (pode usar `lm_obs` falso antes do LM4.1)
  - Orçamento: ~40k
  - Pronto: teste de agrupamento/contagem verde; manual com dados fixos: `[03]` com repository/deploy/assistant, Past tense, Prepositions.
  - Paralelo: LM3.4, LM4.2 (não junto do LM2.2: ambos mexem em `learning_screen.py`)

- [ ] **LM4.4 Spike opcional: Qwen local** *(só se o Pedro aprovar P2; gasta disco/GPU)* — medir Ollama ou llama.cpp com Qwen 7B–14B na GPU: latência do `observe` no exemplo do PDF, VRAM, efeito na latência da conversa e em jogo; implementar `OllamaModel` só se a medição passar. Não trocar o padrão da config sem o Pedro.
  - Lê: design §6 (Modelo), §16 P2, spec §3 (`LearningModel`), `model.py`
  - Escreve: nota em design §16; opcional `magi/learning/model.py` (`OllamaModel`) + teste
  - Depende de: LM3.1, decisão P2
  - Orçamento: ~30k
  - Pronto: tabela com ms, VRAM e qualidade em 5 frases de exemplo.
  - Paralelo: qualquer tarefa da Fase LM4

- [ ] **LM4.5 Resumo ao sair — núcleo** — `magi/learning/summary.py` (puro: `summarize(...) -> SessionSummary`, regras de spec §10.2 item 3); em `session.py`, no fechamento (qualquer `end_reason`): confirma `lm_mode off` **antes**, depois tarefa própria lê `repo.session_stats` com timeout de 2 s (ou o buffer em memória), grava `repo.save_summary` e publica `lm_summary` (só `n_you > 0` e `end_reason ≠ shutdown`) pela mesma função de publicação que a sessão já usa — sem tocar em `wiring.py`. Sem LLM. *(LM-011, spec §10.2)*
  - Lê: spec §3 (`SessionSummary`), §6 (`lm_summary`), §9 item 5, §10, §10.2, §11, design §10, APIs de `session.py` e `repo.py` por grep `def `
  - Escreve: `magi/learning/summary.py`, `magi/learning/session.py` (só o fechamento), `tests/learning/test_summary.py`
  - Depende de: LM4.1 (observações e contagem), LM1.8 (dono anterior de `session.py`)
  - Orçamento: ~35k
  - Pronto: CA-20 verde; CA-18 continua verde (só `lm_summary` passa depois do `off`); `tests/learning/test_session.py` verde.
  - Paralelo: LM1.9, LM3.5, LM4.6

- [ ] **LM4.6 Cartão LAST SESSION no painel e na espera** — `hud/wired/learning_summary.py` (puro: linhas do cartão a partir do `SessionSummary`, `+N`, ★ nas salvas, `visible(now)`; descarta `lm_summary` > 10 s após o `off`; pintura); o `WiredUI` (`integration.py`) lê o resumo e o instante de chegada do `learning_model` (LM1.6 já guarda `lm_summary`), aplica `visible(now)` (inclusive sumir ao `lm_mode on` e depois do clique) e expõe o alvo `"lm_summary"` no `hit`; grupo do cartão em `MainScreen` (abaixo do botão LEARNING, P13) e `StandbyScreen` (acima de `y_rule2`), com `group_key` que muda só ao aparecer/sumir; `gamerhud.py`: `QTimer.singleShot(summary_show_s)` para marcar o grupo sujo e clique → fecha. *(LM-011, design §4.6)*
  - Lê: design §4.4, §4.6, §16 P13, spec §6 (`lm_summary`), §10.2 itens 5–6, §11, `hud/wired/main_screen.py` (botão LEARNING do LM1.7, `MASCOT_MAIN`/`CHIP_TOP`, `groups`/`hit_test`, por grep), `hud/wired/standby_screen.py` (`groups`, `hit_test`, `y_rule2`), `hud/wired/integration.py` (`hit`, `learning_toggle`), `hud/gamerhud.py` (`wired_click`, por grep), API de `hud_bridge.py` por grep `lm_`
  - Escreve: `hud/wired/learning_summary.py`, `hud/wired/main_screen.py` (só o grupo do cartão), `hud/wired/standby_screen.py` (só o grupo do cartão), `hud/wired/integration.py` (só estado/alvo do cartão), `hud/gamerhud.py` (só timer e clique), `tests/learning/test_summary_card.py`
  - Depende de: LM1.7 (pode usar `lm_summary` falso antes do LM4.5)
  - Orçamento: ~45k
  - Pronto: CA-21 verde; CA-18b e `tests/hud` antigos verdes; captura offscreen do painel e da espera com o cartão de exemplo, sem cobrir retrato nem player.
  - Paralelo: LM1.9, LM3.5, LM4.5

## Fechamento do MVP

- [ ] **LMF.1 Ponta a ponta e revisão visual** — roteiro manual: entrar no modo pelo botão do painel, escolher "Talk about the game I'm playing" no seletor e trocar por voz para "Today's news" ("let's talk about the news") e de volta ("conversa livre") e sair por voz em português; entrar por voz em inglês ("learning mode") a partir da espera, 3 trocas (voz e texto) com o exemplo do PDF, selecionar "I make" → Improve/Explain/Translate, "authentication" → Vocabulary → ★ guardar, desfazer e guardar de novo, abrir/fechar observações, encerrar sessão; conferir `learning_*` no banco (só `SELECT`); captura na resolução do monitor do HUD (P10) do estado padrão, do estado com balão e do painel/espera com o botão para o Pedro aprovar (CA-19). Atualizar a classificação dos requisitos que mudaram.
  - Lê: requirements.md (Critérios de sucesso), spec §12
  - Escreve: `specs/learning-mode/requirements.md` (só classificações), capturas em `docs/img/learning-*.png` se o Pedro quiser versionar
  - Depende de: LM1.4, LM1.7, LM1.8, LM1.9, LM3.4, LM3.5, LM4.2, LM4.3, LM4.5, LM4.6
  - Orçamento: ~30k
  - Pronto: roteiro todo ok; CA-19 aprovado pelo Pedro.
  - Paralelo: —

## Paralelismo

| Onda | Tarefas que podem rodar juntas |
| --- | --- |
| 1 | LM0.1, LM0.2, LM0.3 |
| 2 | LM1.1, LM1.2, LM2.1, LM3.1 |
| 3 | LM1.3, LM1.5, LM3.2 |
| 4 | LM1.4, LM1.6, LM3.3 |
| 5 | LM1.7, LM2.2, LM4.1 |
| 6 | LM3.4, LM4.2, LM4.3, LM1.8 (LM4.4 opcional em qualquer onda após LM3.1) |
| 7 | LM1.9, LM3.5, LM4.5, LM4.6 |
| 8 | LMF.1 |

Duas tarefas da mesma onda nunca escrevem o mesmo arquivo. Arquivos com mais de um dono, sempre em
ondas diferentes: `hud/wired/learning_layout.py` (LM2.1 menu/balão → LM1.5 colunas),
`hud/wired/learning_screen.py` (LM1.5 → LM1.6 → LM2.2 → LM4.3 → LM1.9, cada uma só nos seus grupos),
`hud/gamerhud.py` e `hud/wired/integration.py` (LM1.5 → LM1.6 → LM1.7 → LM4.6),
`hud/wired/main_screen.py` e `standby_screen.py` (LM1.7 botão → LM4.6 cartão),
`hud/wired/learning_overlay.py` (LM2.2 → LM3.4 → LM3.5), `magi/common/contracts.py` (LM1.2 → LM1.4 →
LM1.8, as duas últimas só `IntentId`), `magi/core/intents.yaml`, `i18n/en-gb.yaml`,
`magi/learning/intent_action.py`, `persona.py` e `magi/core/assemble.py` (LM1.4 → LM1.8),
`magi/learning/session.py` (LM1.3 → LM1.8 → LM4.5), `magi/learning/engine.py` (LM3.3 → LM4.1 →
LM3.5) e `magi/learning/wiring.py` (LM1.3 → LM3.3 → LM4.1 → LM1.8 → LM3.5). `repo.py` tem dono único
(LM1.1, com todos os métodos novos). O `gamerhud` é um processo só: toda tarefa que mexe em `hud/` roda
`tests/hud` antes e depois.

## Fora do MVP (FUTURE — sem tarefas)

| Fase / ID | Conteúdo | Por que não agora |
| --- | --- | --- |
| Phase 5 / DAT-002 | `users`, `vocabulary`, `grammar_patterns`, `learning_progress` como tabelas | PDF §12: malha completa de banco fora do ciclo |
| Phase 6 / DAT-003 | Memória semântica com pgvector | Só com necessidade explícita de busca semântica |
| MEM-001 | Recorrência entre sessões ("I have went" nas sessões 12, 27, 41) | FUTURE; `rule_key` já permite |
| Phase 7 / UI-003 | Painel Learning Profile | FUTURE; botão fica desabilitado |
| Phase 8 | Pedagogia adaptada ao nível; nível estimado (P3) | FUTURE |
| ASK-001 | Ask Condessa sobre o trecho | FUTURE; contrato de ação já leva o intervalo |
| PDF §12 | Gamificação, currículo formal, redesign do tema, prender a Qwen | Fora de escopo |
| LM-012 / LM-011 | Revisão das palavras salvas (quiz, repetição espaçada); Learning Profile lendo `learning_saved_words` e `learning_sessions.summary` | MVP só guarda; uso fica para a Fase 7 |

## Riscos

Ver design §15. Os que afetam a ordem das tarefas:

1. **Seleção e entrada dentro do `gamerhud` (P1 = A)** — sem seleção nativa e com a janela sem
   foco de teclado. O LM0.3 mede hit-test e o caminho da entrada antes de qualquer tarefa de UI; se
   nenhum caminho de entrada servir, para e volta ao Pedro. A lógica de seleção é pura (LM2.1) e
   testada sem Qt; o núcleo (LM1.1–LM1.4, LM3.x, LM4.1–LM4.2) anda independente.
2. **Mexer no `gamerhud` em uso** (LM1.5–LM1.7) → mouse/teclado novos só agem com
   `view == "learning"`; `tests/hud` antes e depois; captura do painel/espera no LMF.1.
3. **LM0.2 pode mostrar que o `gamerhud` cai com tipo desconhecido** → LM1.2 implementa `lm_hello`
   obrigatoriamente (já é a proposta).
4. **LM4.2 pode reprovar o p95** → parar e propor worker em processo separado (nova tarefa).
5. **LM1.3 mexe no `TurnPipeline` em uso** → rodar `tests/core` antes e depois; gancho atrás de
   `[learning] enabled`.
6. **Custo das observações** maior que o previsto → `observe_daily_max` menor ou `observe = false`
   até haver modelo local (P2).
7. **STT corrige a gramática** (Corrector/`listen = auto`) → Improve usa `heard`; validar em LMF.1.

## Perguntas em aberto

Ver design §16 (P1–P10). **Decididas em 2026-10-07:** **P1** = tela "learning" dentro do
`gamerhud` (QPainter, seleção pelo HUD); **P8** = botão no HUD + voz em PT e EN, sem atalho global.
Resumo do impacto das abertas:
**P2** (Qwen local × cloud) só LM4.4 e o padrão de `[tasks] learning_observe`; **P3** (nível) só o
valor exibido; **P4** (Postgres × JSONL, `public` × schema próprio) só o backend padrão de LM1.1;
**P5** (idioma das explicações) só prompts de LM3.2; **P6** (falar o balão) nada no MVP;
**P7** (Improve em mensagem da Condessa) só LM2.1; **P9** (inatividade) só um valor de config;
**P10** (monitor do HUD) só as resoluções de teste e captura (LM0.3 responde).
Novas (2026-10-07): **P11** (abertura do tema pela Condessa) só LM1.8; **P12** (Game sem jogo
aberto) só o fallback de `topic.py` (LM1.8); **P13** (lugar do cartão no painel) só LM4.6;
**P14** (vaga da Tech interview) só `prompts/topics/interview.md`.
