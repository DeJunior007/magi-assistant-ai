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
10. **Uma tarefa = um commit**, com o ID da tarefa na mensagem.

Estimativa: 1k tokens ≈ 3,5 KB de texto em português ou 4 KB de código. Tamanhos: `design.md`
~6k, `spec.md` ~7k, `requirements.md` ~6k; uma seção 0,3–1,5k.

Formato de cada tarefa:
**Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** (critério verificável) ·
**Paralelo** (com quais pode rodar ao mesmo tempo).

**Decisões que travam tarefas:** P1 (UI) trava LM0.3 e tudo de `hud/learning/`; P4 (banco) muda só
o backend padrão em LM1.1; P2 (modelo) só afeta LM4.4. Ver design §16.

---

## Fase LM0 — Base e spikes

- [ ] **LM0.1 Pacote, contratos e config** — `magi/learning/` com `contracts.py` (enums e dataclasses de spec §3, serialização JSON ida e volta), seção `[learning]` e chaves `[tasks] learning_*` em `config.example.toml` com leitura tipada. *(spec §2–§3, ENG-002, LM-008, LM-009)*
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

- [ ] **LM0.3 Spike: janela PySide6 com seleção no tema wired** *(só após o Pedro responder P1)* — script descartável em `scratch/` que abre uma janela 3440×1440 sem moldura, `QTextBrowser` só leitura com 3 mensagens do exemplo do PDF, fontes de `hud/wired/fonts.py` e cores de `theme.py`; medir: seleção nativa funciona, `selectionChanged` + posição do cursor (`cursorRect`) dão a âncora do menu, render em < 16 ms. Gravar 2 capturas.
  - Lê: design §2, §4, §16 P1, `hud/wired/theme.py` (constantes), `hud/wired/fonts.py` (por grep `def `)
  - Escreve: `scratch/learning_spike.py` (não versionado), nota no fim de design §4
  - Depende de: decisão P1
  - Orçamento: ~35k
  - Pronto: capturas + nota "seleção ok / âncora ok / ms"; se a opção for C (web), esta tarefa vira spike de QtWebEngine e as tarefas `hud/learning/` são reescritas antes de seguir.
  - Paralelo: LM0.1, LM0.2

## Fase LM1 — Interface core e conversa primeiro (PDF Phase 1)

- [ ] **LM1.1 Migração e repositório** — `003_learning.sql` exatamente como spec §8 (aditiva, sem `vector`); `magi/learning/repo.py` com interface `LearningRepo` e dois backends (`PostgresRepo` via `magi/memory/conn.py`, `JsonlRepo`); gravação em memória quando o banco cai (até 500). *(DAT-001..003, MEM-002, LM-010, spec §8, §10)*
  - Lê: design §8, spec §3, §8, §10, `magi/memory/migrate.py` (docstring), `magi/memory/conn.py` (por grep `def `), `magi/memory/costs_repo.py` (só o padrão de um método)
  - Escreve: `magi/memory/migrations/003_learning.sql`, `magi/learning/repo.py`, `tests/learning/test_repo.py`, `tests/learning/test_migration.py`
  - Depende de: LM0.1
  - Orçamento: ~40k
  - Pronto: CA-15 e CA-16 verdes em schema `learning_test`; `grep -Ei 'drop|vector' 003_learning.sql` vazio. **Não** aplicar no `public` nesta tarefa (o Pedro aplica com `uv run python -m magi.memory.migrate`).
  - Paralelo: LM1.2, LM2.1, LM3.1

- [ ] **LM1.2 Mensagens `lm_*` no socket** — classes das mensagens de spec §6 no padrão de `magi/common/contracts.py`, decoders, e roteamento no `HudServer` conforme a opção do LM0.2 (só conexões que mandaram `lm_hello` recebem `lm_*`). *(LM-005, spec §6)*
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

- [ ] **LM1.4 Entrar/sair do modo e persona** — intents de voz ("learning mode", "modo de estudo", "end session") em `intents.yaml` + frases em `i18n/en-gb.yaml`; comando `magi learning` que abre a janela; bloco de persona `prompts/persona.md` acrescentado ao system prompt só com sessão ativa. *(CNV-001, CNV-002, LM-005, design §5, §10)*
  - Lê: design §5, §10, spec §4 (item 4), `magi/core/intents.yaml` (2 intents de exemplo, por grep), `magi/core/i18n/__init__.py` (por grep `def `), `magi/core/assemble.py` (linhas ~520–540, onde o agente é montado), `magi/cli/__init__.py`
  - Escreve: `magi/core/intents.yaml`, `magi/core/i18n/en-gb.yaml`, `magi/learning/prompts/persona.md`, `magi/learning/persona.py`, `magi/core/assemble.py` (só a injeção), `magi/cli/learning.py`, `tests/learning/test_persona.py`
  - Depende de: LM1.3
  - Orçamento: ~45k
  - Pronto: CA-06 verde; intents novas reconhecidas pelo roteador local em teste; sem atalho global (KGlobalAccel).
  - Paralelo: LM1.6, LM3.3 (arquivos distintos: LM3.3 só mexe em `magi/learning/`)

- [ ] **LM1.5 Janela: layout e painéis secundários** — `hud/learning/window.py` (3 colunas + topo + rodapé, design §4), `condessa_panel.py` (retrato reusando `hud/wired/mascot.py`/`portrait.py`, rótulo de estado pela tabela spec §7, nível `B2 / CONVERSATION`), `system_panel.py` (MAGI SYSTEM recolhível, `TEXT_DIM`), lógica pura de layout em `hud/learning/layout.py` (larguras por resolução, coluna central ≤ ~110 caracteres). *(PRN-001, PRN-003, UI-001, UI-002, SYS-001, SYS-002, RNF-06)*
  - Lê: design §4, §7, spec §7, nota do LM0.3, `hud/wired/theme.py`, `hud/wired/kit.py` (assinaturas por grep), `hud/wired/mascot.py` (por grep `class \|def `)
  - Escreve: `hud/learning/__init__.py`, `hud/learning/__main__.py`, `hud/learning/window.py`, `hud/learning/layout.py`, `hud/learning/condessa_panel.py`, `hud/learning/system_panel.py`, `tests/learning/test_layout.py`, `tests/learning/test_state_label.py`
  - Depende de: LM0.3 (e P1)
  - Orçamento: ~55k
  - Pronto: CA-17 verde; parte de layout do CA-11 verde; `python -m hud.learning --demo` abre com dados fixos do exemplo do PDF.
  - Paralelo: LM1.3, LM3.2

- [ ] **LM1.6 Janela: conversa, entrada e cliente** — `conversation.py` (histórico selecionável, rótulos CONDESSA/YOU, mensagem "em fala" revelada com a lógica de `hud/speech_caption.py`, campo de texto, onda de áudio por `mouth`), `client.py` (socket, `lm_hello`, reconexão, `STATUS // CONNECTED/DISCONNECTED`), controles de sessão (start/end, mudo, falar resposta → `lm_cfg`). *(LM-001..LM-004, CTX-003)*
  - Lê: design §4–§5, spec §4, §6, §10, `hud/speech_caption.py` (docstring + API pública por grep `def `), `hud/hud_bridge.py` (só conexão/reconexão, por grep), contratos `lm_*` (LM1.2)
  - Escreve: `hud/learning/conversation.py`, `hud/learning/client.py`, `hud/learning/window.py` (só encaixe), `tests/learning/test_client.py`
  - Depende de: LM1.2, LM1.5
  - Orçamento: ~55k
  - Pronto: teste do cliente com servidor falso (ordem de `lm_msg`, reconexão); manual: com o núcleo rodando, uma frase por voz e uma por texto aparecem no histórico e a da Condessa revela em sincronia.
  - Paralelo: LM1.4, LM3.3

## Fase LM2 — Seleção contextual (PDF Phase 2)

- [ ] **LM2.1 Lógica pura de seleção e posição do menu** — normalizar para palavras inteiras, recortar à mensagem de início, disponibilidade por ação (spec §5, tabela), posição do menu/balão sem cobrir a seleção nem sair da janela. Sem Qt. *(SEL-001, SEL-002, VOC-002, P7)*
  - Lê: spec §5 (disponibilidade), §11, design §4 (menu e balão), contrato `Selection` (LM0.1)
  - Escreve: `hud/learning/selection.py`, `tests/learning/test_selection.py`, `tests/learning/test_layout.py` (só os casos de menu; se LM1.5 estiver aberta junto, usar `test_menu_layout.py`)
  - Depende de: LM0.1
  - Orçamento: ~25k
  - Pronto: CA-10 e a parte de menu do CA-11 verdes.
  - Paralelo: LM1.1, LM1.2, LM3.1

- [ ] **LM2.2 Menu flutuante e balão (com dados falsos)** — `selection_menu.py` (popup pequeno: `selected: "…"`, ✦ Improve, ? Explain, ⇄ Translate, ◇ Vocabulary; teclado ↑↓/Enter/Esc) e `bubble.py` (estados: carregando ≤ 100 ms, resultado por `kind`, erro com retry; "more ▸" do Vocabulary); fecha ao clicar fora/mudar seleção; destaque da seleção enquanto aberto. Resultados vindos de um provedor falso local. *(SEL-001..003, IMP-001, VOC-002, LM-007, RNF-02, RNF-03)*
  - Lê: design §4, spec §5 (schemas e balão), §11, API de `selection.py` (LM2.1), API de `conversation.py` (LM1.6, por grep `def `)
  - Escreve: `hud/learning/selection_menu.py`, `hud/learning/bubble.py`, `hud/learning/conversation.py` (só o sinal de seleção), `tests/learning/test_bubble_model.py` (lógica pura de formatação por kind)
  - Depende de: LM1.6, LM2.1
  - Orçamento: ~45k
  - Pronto: teste de formatação verde; manual com `--demo`: selecionar "I make" mostra o menu e o balão Improve do mockup.
  - Paralelo: LM4.1, LM4.3

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

- [ ] **LM3.4 Balão com resultados reais** — trocar o provedor falso do LM2.2 por `lm_action`/`lm_result` via `client.py`; correlação por `id`; "retry"; timeout de UI 12 s. *(SEL-001..003, IMP-*, EXP-001, TRA-001, VOC-*, LM-007)*
  - Lê: spec §5–§6, APIs de `bubble.py`, `client.py`, `selection_menu.py` (por grep `def `)
  - Escreve: `hud/learning/bubble.py`, `hud/learning/client.py` (só `lm_action`/`lm_result`), `tests/learning/test_client.py` (casos de ação)
  - Depende de: LM2.2, LM3.3
  - Orçamento: ~35k
  - Pronto: teste do cliente com servidor falso verde; manual *(gasta API)*: as 4 ações no exemplo do PDF respondem em ≤ 4 s.
  - Paralelo: LM4.2

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

- [ ] **LM4.3 Indicador e drawer de observações** — `observations.py`: `OBSERVATIONS [nn] ▾` recolhido por padrão; drawer na coluna direita com VOCABULARY / GRAMMAR / RECURRING; clique rola até a mensagem e destaca uma vez; contador atualiza sem animação piscante; botão `[ VIEW LEARNING PROFILE ]` desabilitado ("coming later"). Lógica de agrupamento pura e testada. *(OBS-001, OBS-002, PRN-003, PRN-004, UI-003)*
  - Lê: design §4, §11, spec §6 (`lm_obs`), §9 (itens 4–6), API de `conversation.py` (rolar/destacar, por grep), `condessa_panel.py` (encaixe)
  - Escreve: `hud/learning/observations.py`, `hud/learning/window.py` (só encaixe), `tests/learning/test_obs_view.py`
  - Depende de: LM1.6 (pode usar `lm_obs` falso antes do LM4.1)
  - Orçamento: ~40k
  - Pronto: teste de agrupamento/contagem verde; manual com `--demo`: `[03]` com repository/deploy/assistant, Past tense, Prepositions.
  - Paralelo: LM2.2, LM4.1, LM4.2

- [ ] **LM4.4 Spike opcional: Qwen local** *(só se o Pedro aprovar P2; gasta disco/GPU)* — medir Ollama ou llama.cpp com Qwen 7B–14B na GPU: latência do `observe` no exemplo do PDF, VRAM, efeito na latência da conversa e em jogo; implementar `OllamaModel` só se a medição passar. Não trocar o padrão da config sem o Pedro.
  - Lê: design §6 (Modelo), §16 P2, spec §3 (`LearningModel`), `model.py`
  - Escreve: nota em design §16; opcional `magi/learning/model.py` (`OllamaModel`) + teste
  - Depende de: LM3.1, decisão P2
  - Orçamento: ~30k
  - Pronto: tabela com ms, VRAM e qualidade em 5 frases de exemplo.
  - Paralelo: qualquer tarefa da Fase LM4

## Fechamento do MVP

- [ ] **LMF.1 Ponta a ponta e revisão visual** — roteiro manual: entrar no modo por voz, 3 trocas (voz e texto) com o exemplo do PDF, selecionar "I make" → Improve/Explain/Translate, "authentication" → Vocabulary, abrir/fechar observações, encerrar sessão; conferir `learning_*` no banco (só `SELECT`); captura 3440×1440 do estado padrão e do estado com balão para o Pedro aprovar (CA-19). Atualizar a classificação dos requisitos que mudaram.
  - Lê: requirements.md (Critérios de sucesso), spec §12
  - Escreve: `specs/learning-mode/requirements.md` (só classificações), capturas em `docs/img/learning-*.png` se o Pedro quiser versionar
  - Depende de: LM1.4, LM3.4, LM4.2, LM4.3
  - Orçamento: ~30k
  - Pronto: roteiro todo ok; CA-19 aprovado pelo Pedro.
  - Paralelo: —

## Paralelismo

| Onda | Tarefas que podem rodar juntas |
| --- | --- |
| 1 | LM0.1, LM0.2, LM0.3 (LM0.3 só com P1 decidida) |
| 2 | LM1.1, LM1.2, LM2.1, LM3.1 |
| 3 | LM1.3, LM1.5, LM3.2 |
| 4 | LM1.4, LM1.6, LM3.3 |
| 5 | LM2.2, LM4.1, LM4.3 |
| 6 | LM3.4, LM4.2 (LM4.4 opcional em qualquer onda após LM3.1) |
| 7 | LMF.1 |

Duas tarefas da mesma onda nunca escrevem o mesmo arquivo, exceto: `tests/learning/test_layout.py`
(LM2.1 usa `test_menu_layout.py` se rodar junto de LM1.5 — já estão em ondas diferentes no plano),
`hud/learning/window.py` (LM1.6 e LM4.3 só fazem "encaixe"; ondas 4 e 5) e `magi/learning/engine.py`
/ `wiring.py` (LM3.3 → LM4.1, sequenciais).

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

## Riscos

Ver design §15. Os que afetam a ordem das tarefas:

1. **P1 sem resposta trava toda a UI** (LM0.3, LM1.5, LM1.6, LM2.2, LM3.4, LM4.3). O núcleo
   (LM1.1–LM1.4, LM3.x, LM4.1–LM4.2) anda sem ela.
2. **LM0.2 pode mostrar que o `gamerhud` cai com tipo desconhecido** → LM1.2 implementa `lm_hello`
   obrigatoriamente (já é a proposta).
3. **LM4.2 pode reprovar o p95** → parar e propor worker em processo separado (nova tarefa).
4. **LM1.3 mexe no `TurnPipeline` em uso** → rodar `tests/core` antes e depois; gancho atrás de
   `[learning] enabled`.
5. **Custo das observações** maior que o previsto → `observe_daily_max` menor ou `observe = false`
   até haver modelo local (P2).
6. **STT corrige a gramática** (Corrector/`listen = auto`) → Improve usa `heard`; validar em LMF.1.

## Perguntas em aberto

Ver design §16 (P1–P9). Resumo do impacto: **P1** (UI PySide6 × React) trava a UI inteira;
**P2** (Qwen local × cloud) só LM4.4 e o padrão de `[tasks] learning_observe`; **P3** (nível) só o
valor exibido; **P4** (Postgres × JSONL, `public` × schema próprio) só o backend padrão de LM1.1;
**P5** (idioma das explicações) só prompts de LM3.2; **P6** (falar o balão) nada no MVP;
**P7** (Improve em mensagem da Condessa) só LM2.1; **P8** (como entrar) LM1.4; **P9**
(inatividade) só um valor de config.
