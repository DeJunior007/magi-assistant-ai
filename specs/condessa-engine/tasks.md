# Tarefas — Condessa Engine

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **uma sessão de agente** com janela de até 128k tokens. Como o Engine ainda não
existe, estas tarefas são conduzidas pelo Pedro com o Claude Code, como as do
`specs/magi-assistant/tasks.md` (o Engine não se constrói sozinho).

## Regras para o agente

1. **Leia só o pacote de contexto da tarefa** (campo *Lê*). Seções do design são citadas por `§`,
   do spec por `spec §`, requisitos por `R`.
2. **Orçamento planejado ≤ 60k tokens** por tarefa; o resto da janela de 128k é margem.
3. **Contratos primeiro:** módulos de outras tarefas são usados pelo que está em
   `engine/contracts.py` (tarefa E0.1), sem ler o código deles.
4. **Arquivos grandes por trecho:** `grep -n` e leitura por intervalo. Nunca leia
   `hud/gamerhud.py` nem `magi/maintenance/autofix.py` inteiros; as tarefas dizem o que abrir.
5. **Saída de testes curta:** `uv run pytest -q -x tests/engine/<arquivo>`.
6. **Se o pacote não bastar:** pare e anote o que faltou; não saia lendo o repositório.
7. **Uma tarefa = um commit**, com o ID da tarefa na mensagem.
8. **Nada de sessão ao vivo:** testes nunca abrem Konsole, nunca chamam `claude` de verdade (só o
   falso), nunca usam o repositório real para git (só `tmp_path`), nunca chamam `systemctl` real.
   O KGlobalAccel roda dentro do KWin: qualquer `qdbus`/`gdbus` para ele derruba a sessão KDE.
9. **Nunca** apontar teste ou exemplo para repositório da empresa (Sume / GitLab).

Estimativa: 1k tokens ≈ 3,5 KB de texto em português ou 4 KB de código. Tamanhos: `design.md` ~6k,
`spec.md` ~8k, `requirements.md` ~5k; uma seção 0,3–1,5k.

Formato de cada tarefa:
**Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** (critério verificável) ·
**Paralelo** (com quais pode rodar ao mesmo tempo).

---

## Fase E0 — Base e spikes

- [ ] **E0.1 Pacote e contratos** — pacote `engine/` no `pyproject.toml` (com o script `magi-engine`); `engine/contracts.py` com enums de estado (intenção e task), `Verdict`, `RuleFailure`, `Evidence`, `SessionResult`, `GateResult`, `Intent`, `Task`, `Event`, serialização JSON ida e volta; `engine/tools/tokens.py`. *(R5.1, spec §1, §3, §4, §6)*
  - Lê: design §2–§3, spec §1, §3, §4 (fim), §6 (JSON), `pyproject.toml`
  - Escreve: `pyproject.toml`, `engine/__init__.py`, `engine/contracts.py`, `engine/tools/tokens.py`, `tests/engine/test_contracts.py`
  - Depende de: —
  - Orçamento: ~35k
  - Pronto: `uv run pytest -q tests/engine/test_contracts.py` e `uv run ruff check engine` verdes; docstring de cada contrato cita o R.
  - Paralelo: —

- [ ] **E0.2 Spike S-E1: Claude Code headless** — rodar `claude -p` curto com `--output-format stream-json --verbose`: confirmar `usage` por resposta, `--session-id`, como aparece compactação e o aviso de limite de uso; matar o grupo de processo no meio. Gravar 3 fluxos de exemplo (normal, estouro simulado, erro). **Gasta um pouco da assinatura.**
  - Lê: design §6, §8, §18, spec §4, `magi/maintenance/autofix.py` (só `run_cmd` e `_claude`), `magi/maintenance/claude_usage.py` (docstring)
  - Escreve: `spikes/se1_claude.py`, `docs/spikes/SE1.md`, `tests/engine/fixtures/stream/*.jsonl`
  - Depende de: —
  - Orçamento: ~30k
  - Pronto: `SE1.md` diz o campo exato da ocupação, o padrão do texto de cota e se `--session-id` existe; fixtures gravadas.
  - Paralelo: E0.1, E0.3

- [ ] **E0.3 Spike S-E2: Konsole** — de dentro de um `systemd-run --user` (simula o serviço), abrir o Konsole com `konsole --separate … -e` e com `konsole --new-tab … -e`; conferir variáveis de display necessárias; **sem nenhum D-Bus**. **Precisa do Pedro** olhando a tela.
  - Lê: design §13, spec §14, `docs/spikes/S2.md` (só o resumo do incidente do KGlobalAccel)
  - Escreve: `spikes/se2_konsole.sh`, `docs/spikes/SE2.md`
  - Depende de: —
  - Orçamento: ~15k
  - Pronto: `SE2.md` com o argv aprovado e as variáveis de ambiente exigidas; sessão KDE intacta.
  - Paralelo: E0.1, E0.2

## Fase E1 — Núcleo determinístico

- [ ] **E1.1 Projetos e recusa da empresa** — `projects.load/resolve` (TOML, validação, apelidos), recusa Sume/GitLab lendo só `.git/config`, lista fixa de caminhos proibidos e `is_forbidden(path, project, origin)`; `projects/condessa.toml`. *(R1.3–R1.4, R3, R10.3)*
  - Lê: `engine/contracts.py`, spec §2
  - Escreve: `engine/validation/projects.py`, `engine/validation/projects/condessa.toml`, `tests/engine/test_projects.py`
  - Depende de: E0.1
  - Orçamento: ~35k
  - Pronto: CA-02, CA-03 verdes.
  - Paralelo: E1.2, E1.4, E0.2, E0.3

- [ ] **E1.2 Estado e eventos** — `Store`: `intents/*.json` atômico, contador de IDs, `events.jsonl` com giro, `status.json` (spec §8) recalculado a cada mudança, `ledger/<projeto>.jsonl` com consulta por arquivos (R17). *(R5.3, R9.3, R17, spec §3, §8, §9)*
  - Lê: `engine/contracts.py`, design §12, spec §3, §8, §9
  - Escreve: `engine/harness/store.py`, `engine/memory/ledger.py`, `tests/engine/test_store.py`, `tests/engine/test_ledger.py`
  - Depende de: E0.1
  - Orçamento: ~40k
  - Pronto: CA-24 verde; escrita interrompida (exceção no meio) não corrompe o JSON.
  - Paralelo: E1.1, E1.4

- [ ] **E1.3 Máquina de estados** — tabela de transições do spec §3, `transition()` que valida e grava evento, `resume_to`, PAUSED e DISCARDED. *(R5.1–R5.4)*
  - Lê: `engine/contracts.py`, API do `store.py`, design §4, spec §3
  - Escreve: `engine/harness/machine.py`, `tests/engine/test_machine.py`
  - Depende de: E1.2
  - Orçamento: ~30k
  - Pronto: CA-06 verde.
  - Paralelo: E1.5, E1.6, E1.7

- [ ] **E1.4 Artefatos SDD** — leitura do cabeçalho YAML, validação estrutural, `verify` (spec §5), grafo de referências R→C→S→T, templates de cada artefato (inclui os de `conserto`) e as pastas `engine/sdd/{prd,design,specs,tasks}/`. *(R4)*
  - Lê: `engine/contracts.py`, spec §1, §5
  - Escreve: `engine/sdd/schema.py`, `engine/sdd/templates/*.md`, `engine/sdd/{prd,design,specs,tasks}/.gitkeep`, `tests/engine/test_schema.py`, `tests/engine/fixtures/sdd/*.md`
  - Depende de: E0.1
  - Orçamento: ~45k
  - Pronto: fixtures válidas carregam; cada fixture inválida dá o erro esperado.
  - Paralelo: E1.1, E1.2

- [ ] **E1.5 Jev — regras de especificação** — `decide()` com a ordem do spec §6, assinatura, limites de loop/tentativa, e as regras J-S01..J-S12. *(R6, R10.6–R10.7, R10.10)*
  - Lê: `engine/contracts.py`, API do `schema.py`, API de `projects.is_forbidden`, design §11, spec §6 (topo e J-S)
  - Escreve: `engine/decisions/jev.py`, `engine/decisions/rules_sdd.py`, `tests/engine/test_jev.py`, `tests/engine/test_rules_sdd.py`
  - Depende de: E1.1, E1.4
  - Orçamento: ~50k
  - Pronto: CA-05, CA-08, CA-14 verdes.
  - Paralelo: E1.3, E1.6, E1.7

- [ ] **E1.6 Jev — regras de implementação e revisão** — J-I01..J-I11 e J-R01..J-R04 sobre `Evidence` (diff numstat, gates, sessão, critérios, achados do revisor). *(R10, R11.2)*
  - Lê: `engine/contracts.py`, API de `jev.py` (assinatura de `decide`), API de `projects.is_forbidden`, spec §6 (J-I, J-R)
  - Escreve: `engine/decisions/rules_impl.py`, `tests/engine/test_rules_impl.py`, `tests/engine/test_rules_review.py`
  - Depende de: E1.5 (só a interface de regra; pode começar com o protocolo de E0.1)
  - Orçamento: ~45k
  - Pronto: CA-13, CA-15 verdes.
  - Paralelo: E1.3, E1.7

- [ ] **E1.7 Pacote de contexto** — `build(task, intent, project)` com os blocos e limites de design §7, recorte dos artefatos pelos IDs referenciados, corte com marcador, recusa de código > 45k, gravação de `context.md` e da estimativa; mesma função de estimativa usada por J-S10. *(R7)*
  - Lê: `engine/contracts.py`, API do `schema.py` e do `ledger.py`, design §7, spec §5 (Tasks)
  - Escreve: `engine/context/builder.py`, `tests/engine/test_builder.py`
  - Depende de: E1.2, E1.4
  - Orçamento: ~45k
  - Pronto: CA-09 verde.
  - Paralelo: E1.3, E1.5, E1.6

## Fase E2 — Execução

- [ ] **E2.1 Runner e monitor de tokens** — subprocesso em grupo próprio, ambiente limpo (spec §4), leitura do `stream-json`, ocupação, aviso a 85%, estouro/compactação → SIGTERM/SIGKILL, detecção de cota, `SessionResult`; `claude` falso para testes a partir das fixtures do S-E1. *(R8.6, R9)*
  - Lê: `engine/contracts.py`, `docs/spikes/SE1.md`, design §8, spec §4
  - Escreve: `engine/harness/runner.py`, `tests/engine/fake_claude.py`, `tests/engine/test_runner.py`
  - Depende de: E0.1, E0.2
  - Orçamento: ~45k
  - Pronto: CA-12 verde; fluxo de cota dá `quota`.
  - Paralelo: E2.2, E2.5, E3.3, E3.4

- [ ] **E2.2 Git: worktrees, diff, trailers e why** — criar/remover worktree e branch da intenção e da task, diff `--numstat`/`--name-status` contra a base, merge interno task → intenção, conferência e conserto de trailers, `why`. *(R8.1, R13)*
  - Lê: `engine/contracts.py`, design §9, spec §7, `magi/maintenance/autofix.py` (só `_fix` e `_drop_worktree`)
  - Escreve: `engine/harness/gitops.py`, `tests/engine/test_gitops.py`, `tests/engine/test_why.py`
  - Depende de: E0.1
  - Orçamento: ~50k
  - Pronto: CA-19 verde; tudo em repositório `tmp_path`.
  - Paralelo: E2.1, E2.5, E1.x

- [ ] **E2.3 Gates do projeto** — rodar os gates (argv, tempo limite, código 124), cauda sanitizada, assinatura de falha normalizada, execução dos critérios `verify` (spec §5). *(R10.1, R10.5)*
  - Lê: `engine/contracts.py`, API de `projects.py`, design §10, spec §5 (verificável), `magi/maintenance/autofix.py` (só `sanitize`)
  - Escreve: `engine/validation/gates.py`, `tests/engine/test_gates.py`
  - Depende de: E1.1
  - Orçamento: ~35k
  - Pronto: gate falso que trava dá 124; mesma falha com números de linha diferentes dá a mesma assinatura.
  - Paralelo: E2.1, E2.2

- [ ] **E2.4 Agentes: escritor de spec e divisão de task** — prompts de PRD/Design/Spec/Tasks/divisão (texto da intenção em bloco de dados), argv do papel (spec §4), entrada do "o que corrigir" do Jev no RETRY. *(R4.1, R8.3, R10.8)*
  - Lê: `engine/contracts.py`, `engine/sdd/templates/*.md`, API do `builder.py` e do `runner.py`, design §6, spec §4, §5
  - Escreve: `engine/agents/spec_writer.py`, `tests/engine/test_agents.py` (parte do escritor)
  - Depende de: E1.4, E1.7, E2.1
  - Orçamento: ~40k
  - Pronto: CA-10 (escritor) verde; prompt nunca põe o texto da intenção fora do bloco de dados.
  - Paralelo: E2.5

- [ ] **E2.5 Agentes: implementador e revisor** — prompts e argv do implementador (com `allowed_bash` do projeto e lista negada) e do revisor (`plan`, JSON de achados). *(R8.2–R8.3, R11.1)*
  - Lê: `engine/contracts.py`, API do `builder.py` e do `runner.py`, design §6, spec §4, §6 (J-R, JSON do revisor), §7
  - Escreve: `engine/agents/implementer.py`, `engine/agents/reviewer.py`, `tests/engine/test_agents.py` (parte deles)
  - Depende de: E1.7, E2.1
  - Orçamento: ~35k
  - Pronto: CA-10 verde para os três papéis.
  - Paralelo: E2.4

- [ ] **E2.6 Orquestrador** — loop do design §5: próxima ação por intenção, `busy()`, `max_parallel`, `max_sessions_per_window`, PAUSED por cota com retomada no fim da janela (`claude_usage.current_window`), retomada após reinício (sessões `interrupted`, worktrees órfãs), SPLIT, task de correção da revisão. *(R5.2, R5.4, R8.4–R8.6, R11)*
  - Lê: APIs de `machine.py`, `store.py`, `jev.py`, `builder.py`, `runner.py`, `gitops.py`, `gates.py`, `agents/*`; design §4–§5, §16; spec §3 (tabela)
  - Escreve: `engine/harness/orchestrator.py`, `tests/engine/test_orchestrator.py`
  - Depende de: E1.3, E1.5, E1.6, E2.2, E2.3, E2.4, E2.5
  - Orçamento: ~60k
  - Pronto: CA-07, CA-11 verdes.
  - Paralelo: E3.3, E3.4

## Fase E3 — Merge, serviço e superfícies

- [ ] **E3.1 Merge** — fluxo do spec §10: checagens de repo limpo e ramo, `--no-ff`, aborto em conflito; pessoal sem push; próprio com serviços por `[services]` e o vigia `autofix.guard` por `systemd-run`, leitura do resultado do vigia ao subir. *(R12)*
  - Lê: API de `gitops.py`, `projects.py`, `machine.py`; spec §10; `magi/maintenance/autofix.py` (só `apply` e `guard`)
  - Escreve: `engine/harness/merge.py`, `tests/engine/test_merge.py`
  - Depende de: E2.2, E1.3
  - Orçamento: ~45k
  - Pronto: CA-16, CA-17, CA-18 verdes.
  - Paralelo: E2.6, E3.3, E3.4

- [ ] **E3.2 Serviço e CLI** — `magi-engine serve` (socket, comandos do spec §11, avisos `say` ao `magi-core` com "uma vez por transição"), CLI com os subcomandos, unidade `magi-engine.service` ao lado das outras no instalador. *(R1.1–R1.2, R12.2, R12.6, R15.4)*
  - Lê: APIs de `orchestrator.py`, `merge.py`, `store.py`, `gitops.why`; spec §11–§12 (avisos); `hud/install.sh` (só a parte de unidades), uma unidade existente de `hud/system/`
  - Escreve: `engine/harness/service.py`, `engine/harness/cli.py`, unidade `magi-engine.service` (no mesmo lugar das outras), `tests/engine/test_service.py`
  - Depende de: E2.6, E3.1
  - Orçamento: ~50k
  - Pronto: CA-01 verde; `magi-engine status` responde com o serviço rodando em teste (socket em `tmp_path`).
  - Paralelo: —
  - Observação: tocar na unidade systemd é caminho proibido para o Engine, mas esta tarefa é feita pelo Pedro com o Claude Code, fora do Engine.

- [ ] **E3.3 Console no Konsole** — `console/view.py` (spec §14, só leitura de `status.json`/`events.jsonl`) e `console/launch.py` com o argv do `SE2.md`, PID único, `MAGI_ENGINE_NO_CONSOLE`. *(R14)*
  - Lê: `docs/spikes/SE2.md`, spec §8, §9, §14, design §13
  - Escreve: `engine/console/view.py`, `engine/console/launch.py`, `engine/console/__main__.py`, `tests/engine/test_console.py`
  - Depende de: E0.3, E1.2
  - Orçamento: ~35k
  - Pronto: CA-20 verde; teste garante que nenhum `qdbus`/`gdbus` aparece no código do pacote (`grep`).
  - Paralelo: E2.x, E3.1, E3.4

- [ ] **E3.4 HUD: painel Claude Code com o Engine** — `ClaudeView.engine` lido do `status.json`; painel com até 3 intenções, task e ocupação, destaque "aguardando seu ok"; a linha do autoconserto passa a vir do Engine. *(R15.1–R15.2)*
  - Lê: spec §8; `hud/wired/data.py` (seção "Claude Code (painel)"); `hud/wired/main_screen.py` (só o bloco do painel Claude Code, via `grep -n CLAUDE`)
  - Escreve: `hud/wired/data.py`, `hud/wired/main_screen.py`, `tests/hud/test_wired_data.py`
  - Depende de: E1.2 (só o formato do `status.json`)
  - Orçamento: ~45k
  - Pronto: CA-21 verde; PNG do painel com `status.json` de exemplo via `hud/tools/wired_demo.py`.
  - Paralelo: E2.x, E3.1, E3.3

- [ ] **E3.5 Voz** — intenções `engine.*` no `magi/core/intents.yaml` (frases do spec §12), ação `magi/core/actions/engine.py` falando com o socket, confirmação falada do merge usando a de ações perigosas, avisos do Engine virando fala. *(R15.3–R15.4, R12.2)*
  - Lê: spec §11–§12; `magi/core/intents.yaml` (bloco `system.autofix_*`); a ação do autoconserto em `magi/maintenance/autofix.py` (só a classe de ação no fim); como o núcleo faz confirmação (`grep -n confirm magi/core/turn.py`)
  - Escreve: `magi/core/intents.yaml`, `magi/core/actions/engine.py`, registro da ação, `tests/core/test_engine_action.py`, `tests/core/test_router.py`
  - Depende de: E3.2
  - Orçamento: ~50k
  - Pronto: CA-22 verde; "aprova o merge" sem "confirma" não chama `confirm`.
  - Paralelo: E3.6, E3.8

- [ ] **E3.6 Propostas da Condessa** — detector de erro repetido (journal dos serviços dela, assinatura, ≥ 5 em 24 h) ligado ao `AlertMonitor`, e de pedido recorrente que ela não sabe fazer (marcador do agente + `rapidfuzz`), limites do R2.4, sempre `project=self`. *(R2)*
  - Lê: spec §13; `magi/core/proactive/alerts.py` (só `AlertMonitor`); API de `gates.signature`; cliente do socket de E3.5
  - Escreve: `engine/harness/proposals.py`, ganchos em `magi/core/proactive/alerts.py` e no agente (marcador), `tests/engine/test_proposals.py`
  - Depende de: E3.2, E2.3
  - Orçamento: ~50k
  - Pronto: CA-04 verde.
  - Paralelo: E3.5, E3.7

- [ ] **E3.7 Autoconserto vira caso do Engine** — `start_fix` abre intenção `conserto`; `apply`/`discard`/`status` viram approve/discard/status; limite de 3 por dia vira limite das intenções `conserto`; diagnóstico (nível 0) intacto; `docs/design/AUTOCONSERTO.md` atualizado. *(R16)*
  - Lê: `magi/maintenance/autofix.py` (só `start_fix`, `_fix`, `apply`, `discard`, `status`, `_runs_left`); spec §5 (template de conserto), §11; `docs/design/AUTOCONSERTO.md`
  - Escreve: `magi/maintenance/autofix.py`, `docs/design/AUTOCONSERTO.md`, `tests/maintenance/test_autofix.py`
  - Depende de: E3.2, E3.5
  - Orçamento: ~50k
  - Pronto: CA-23 verde; testes antigos do autoconserto continuam verdes (ajustados só no que mudou de propósito).
  - Paralelo: E3.6

- [ ] **E3.8 `why` na CLI e na voz** — `magi-engine why` formatado (spec §7) e, opcional, "por que esse arquivo existe?" falando só o resumo. *(R13.2)*
  - Lê: API de `gitops.why`, spec §7, §11
  - Escreve: `engine/harness/cli.py` (subcomando), `tests/engine/test_why.py`
  - Depende de: E2.2, E3.2
  - Orçamento: ~20k
  - Pronto: CA-19 verde pela CLI.
  - Paralelo: E3.5, E3.6

## Fase E4 — Encerramento

- [ ] **E4.1 Ponta a ponta com projeto de brinquedo** — repositório temporário com `projects/brinquedo.toml` de teste, `claude` falso que escreve artefatos válidos e implementa 2 tasks; IDEA → DONE com uma aprovação; variante com estouro → SPLIT; variante com loop → HUMAN.
  - Lê: APIs públicas do Engine (`service`, `cli`), spec §15, §16
  - Escreve: `tests/engine/test_e2e.py`, `tests/engine/fixtures/e2e/`
  - Depende de: E3.1, E3.2
  - Orçamento: ~50k
  - Pronto: CA-25 verde.
  - Paralelo: E3.5–E3.8

- [ ] **E4.2 Primeira intenção real** — uma intenção pequena na própria Condessa (sugestão: uma frase nova no `phrases.yaml` com teste), com o console aberto e o painel mostrando. **Precisa do Pedro** (voz, acompanhar e aprovar).
  - Lê: `docs/GUIA.md` (seção nova do E4.3, se já existir)
  - Escreve: `docs/perf/engine.md` (tokens por fase, tempo, vereditos)
  - Depende de: E4.1, E3.3, E3.4, E3.5
  - Orçamento: ~20k (fora o que o Engine gasta)
  - Pronto: critérios de sucesso 1–4 do `requirements.md` conferidos e registrados.
  - Paralelo: —

- [ ] **E4.3 Documentação** — README (mapa: `engine/`), `docs/GUIA.md` (como abrir intenção, aprovar, console, onde ficam os dados, como declarar um projeto pessoal), `docs/PROXIMOS-PASSOS.md` (perguntas em aberto que sobrarem). Só documentação.
  - Lê: `tasks.md`, design §1, §3, §12, spec §2, §11–§12, `README.md`
  - Escreve: `README.md`, `docs/GUIA.md`, `docs/PROXIMOS-PASSOS.md`
  - Depende de: E3.2, E3.5
  - Orçamento: ~40k
  - Pronto: comandos e caminhos conferidos no código; testes verdes.
  - Paralelo: E4.1

---

## Paralelismo

| Onda | Tarefas que podem rodar juntas |
| --- | --- |
| 1 | E0.1, E0.2, E0.3 |
| 2 | E1.1, E1.2, E1.4 (após E0.1) |
| 3 | E1.3, E1.5, E1.7, E2.2, E2.3, E2.1 (precisa de E0.2), E3.3 (precisa de E0.3), E3.4 |
| 4 | E1.6, E2.4, E2.5, E3.1 |
| 5 | E2.6 |
| 6 | E3.2 |
| 7 | E3.5, E3.6, E3.8, E4.1, E4.3 |
| 8 | E3.7 |
| 9 | E4.2 |

Duas tarefas da mesma onda nunca escrevem o mesmo arquivo, exceto `tests/engine/test_agents.py`
(E2.4 e E2.5: dividir em `test_agents_spec.py` e `test_agents_impl.py` se rodarem juntas) e
`engine/harness/cli.py` / `tests/engine/test_why.py` (E3.8 depois de E3.2, não juntas).

## Riscos

Ver design §19. Os que afetam a ordem das tarefas:

1. **S-E1 pode mostrar que o `stream-json` não traz `usage` por resposta** → E2.1 usa o fallback
   pelo registro da sessão (`--session-id` + leitor de `claude_usage.py`); +10k no orçamento de E2.1.
2. **S-E2 pode não achar forma segura de abrir o Konsole a partir do serviço** → E3.3 entrega só
   `magi-engine console` (Pedro abre na mão) e R14.1 fica para depois.
3. **E2.6 é a maior tarefa (~60k)**; se o pacote não couber, dividir em "loop e fila" e "pausas e
   retomada".
4. **E3.7 mexe num fluxo que está em uso** (autoconserto): rodar os testes antigos antes e depois.

## Perguntas em aberto

Respondidas em design §20 (2026-10-07): P2 vira a task E2.7 (hook `PreToolUse`), P5 = 3 sessões por janela na autoimplementação e pergunta antes com o VS Code aberto, P9 = propostas seguem sozinhas. Histórico: **P3** (onde ficam os artefatos de projetos pessoais)
afeta E2.2 e E3.1; **P6** (limite de diff) afeta só o valor padrão em E1.1; **P9** (proposta entra
sozinha?) afeta E3.6; **P2** (hook `PreToolUse`) seria uma tarefa nova depois de E2.5.
