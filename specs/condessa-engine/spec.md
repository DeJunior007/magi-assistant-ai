# Spec — Condessa Engine

Comportamento, contratos/schemas, casos de borda e critérios de aceite. Implementa
[requirements.md](requirements.md) segundo o [design.md](design.md). Seções citadas por `spec §`.
Todo valor marcado *(config)* fica em `[engine]` do `~/.config/magi/config.toml`, com o padrão dado.

## 1. IDs

| Objeto | Formato | Exemplo |
| --- | --- | --- |
| Intenção | `INT-` + 4 dígitos, sequencial global | `INT-0007` |
| Requisito (PRD da intenção) | `R` + n | `R2` |
| Critério de aceite | `R2.1`, `S3.2` (pai + n) | |
| Componente (design) | `C` + n | `C1` |
| Item de spec | `S` + n | `S3` |
| Task | `T` + 3 dígitos; divisões ganham letra | `T003`, `T003a` |
| Regra do Jev | `J-S`nn (especificação), `J-I`nn (implementação), `J-R`nn (revisão) | `J-I03` |

Slug do arquivo: até 40 caracteres, minúsculas, `-`; nome `INT-0007-sistema-de-plugins.md`.

## 2. Arquivo de projeto

`engine/validation/projects/<nome>.toml` (R3):

```toml
name = "condessa"                 # usado na voz: "no projeto condessa"
aliases = ["magi", "a condessa"]  # opcional
path = "~/Documentos/magi-assistant-ai"
kind = "self"                     # "self" | "pessoal"
main_branch = "main"
max_diff_lines = 400              # soma de + e - por task (P6)
max_diff_files = 10
forbidden = ["deploy/**", "hud/system/**"]   # somados à lista fixa
allowed_bash = ["uv run pytest:*", "uv run ruff:*"]  # entra no --allowedTools do implementador

[gates]                           # argv, sem shell; ordem = ordem de execução
lint  = ["uv", "run", "ruff", "check", "."]
test  = ["uv", "run", "pytest", "-q", "-x"]
build = []                        # vazio = sem gate de build
timeout_s = 600

[services]                        # só kind = "self": caminho → serviços a reiniciar no merge
"magi/core/**" = ["magi-core"]
"magi/satellite/**" = ["magi-satellite"]
"engine/**" = ["magi-engine"]
```

Validação (`projects.load`): `name`, `path` (existe e é repositório git), `kind`, `main_branch` e ao
menos um gate não vazio entre `lint` e `test` são obrigatórios. Só pode haver um `kind = "self"`.

**Recusa da empresa (R1.4, R3.4)** — checada **antes** de qualquer outra leitura do repositório,
lendo só `.git/config` como texto:
- caminho resolvido contém `sume` (sem diferenciar maiúsculas) → recusa;
- algum `url =` de remoto contém `gitlab` ou `sume` → recusa.
Erro: `EmpresaRecusada(projeto, motivo)`; sem exceção configurável.

**Lista fixa de caminhos proibidos** (R10.3), comparada no caminho relativo ao repositório e no
absoluto: `.git/**`, `**/.env*`, `**/*secret*`, `**/*.key`, `**/*.pem`, `**/id_rsa*`,
`**/*.service`, `**/*.timer`, `**/systemd/**`, `**/Dockerfile*`, `**/docker-compose*.y*ml`,
`**/compose*.y*ml`, e qualquer caminho absoluto fora da worktree (inclui `~/.config/**`).
Para origem `condessa` somam-se `engine/**`, `persona/**` (R2.6).

## 3. Intenção e tasks (estado)

`intents/INT-0007.json` (escrita atômica: `.tmp` + `replace`):

```json
{
  "id": "INT-0007", "project": "condessa", "kind": "feature",
  "origin": "pedro", "via": "voz",
  "text": "quero um sistema de plugins",
  "state": "IMPLEMENT", "resume_to": null, "reason": "",
  "created_at": "2026-10-07T21:00:00-03:00", "updated_at": "…",
  "branch": "engine/INT-0007", "base_sha": "abc123",
  "artifacts": {"prd": "engine/sdd/prd/INT-0007-sistema-de-plugins.md", "design": "…", "spec": "…", "tasks": "…"},
  "phase_attempts": {"PRD": 1, "DESIGN": 2},
  "tasks": {
    "T001": {"state": "PASS", "attempts": 1, "signatures": ["…"], "tokens": {"fresh": 41000, "cache_read": 220000, "peak": 63000}},
    "T002": {"state": "RUNNING", "attempts": 2, "signatures": ["9f2e…"], "tokens": {"fresh": 0, "cache_read": 0, "peak": 0}}
  },
  "tokens": {"fresh": 120000, "cache_read": 900000},
  "review": null, "merge": null
}
```

- `kind`: `feature` | `conserto`. `origin`: `pedro` | `condessa`. `via`: `voz` | `hud` | `cli` | `autofix` | `alerta`.
- `state` da intenção: `IDEA, PRD, DESIGN, SPEC, TASK_BREAKDOWN, READY, IMPLEMENT, TEST, REVIEW, HUMAN_OK, MERGE, DONE, HUMAN, PAUSED, DISCARDED`.
- `state` da task: `PENDING, RUNNING, CHECKING, PASS, RETRY, SPLIT, HUMAN, DISCARDED`.
- `resume_to`: estado de volta para HUMAN e PAUSED. `peak` = maior ocupação vista.

**Transições válidas** (qualquer outra levanta `TransicaoInvalida` e não grava):

| De | Para | Condição de entrada |
| --- | --- | --- |
| IDEA | PRD | projeto válido e não recusado |
| PRD / DESIGN / SPEC / TASK_BREAKDOWN | próxima fase | Jev PASS no artefato da fase |
| TASK_BREAKDOWN | READY | Jev PASS: tasks ≤ 128k, cobertura total, sem ciclo |
| READY | IMPLEMENT | existe task PENDING com dependências em PASS; sem PAUSED |
| IMPLEMENT | TEST | sessão da task terminou (qualquer motivo) |
| TEST | IMPLEMENT | veredito da task + ainda há task não PASS |
| TEST | REVIEW | todas as tasks PASS (SPLIT conta pelas filhas) |
| REVIEW | IMPLEMENT | J-R RETRY: cria task de correção `Tnnn` com os achados |
| REVIEW | HUMAN_OK | J-R PASS |
| HUMAN_OK | MERGE | aprovação + "confirma" em 8 s |
| MERGE | DONE / HUMAN_OK / HUMAN | §10 |
| qualquer fase ≤ REVIEW | HUMAN | veredito HUMAN |
| HUMAN | `resume_to` | "continua" (zera as assinaturas da fase/task) |
| qualquer não terminal | PAUSED | cota, `pause`, erro de infraestrutura |
| PAUSED | `resume_to` | `resume` ou fim da janela de cota |
| qualquer não terminal | DISCARDED | "descarta" |

## 4. Sessões do Claude Code

Montadas por `agents/*.py`; o prompt vai por stdin; cwd = a worktree. Comum a todos:

```
claude -p --model <modelo> --output-format stream-json --verbose
       --max-turns <n> --permission-mode <modo>
       --allowedTools "<lista>" --disallowedTools "<lista_negada>"
```

| Papel | `--permission-mode` | `--allowedTools` | `--max-turns` | Tempo |
| --- | --- | --- | --- | --- |
| escritor de spec | `acceptEdits` | `Read,Grep,Glob,Edit,Write` | 25 | 15 min |
| implementador | `acceptEdits` | `Read,Grep,Glob,Edit,Write,Bash(git add:*),Bash(git commit:*),Bash(git diff:*),Bash(git status:*)` + `allowed_bash` do projeto | 60 | 30 min |
| revisor | `plan` | `Read,Grep,Glob,Bash(git diff:*),Bash(git log:*)` | 20 | 10 min |

`lista_negada` sempre: `Bash(git push:*),Bash(git remote:*),Bash(systemctl:*),Bash(docker:*),Bash(curl:*),Bash(wget:*),Bash(ssh:*),WebFetch,WebSearch`.

Ambiente da sessão: o do serviço com `PATH` incluindo `~/.local/bin` (como `autofix.run_cmd`), sem
variáveis cujo nome contenha `KEY`, `TOKEN`, `SECRET` ou `PASSWORD`; `MAGI_ENGINE=1`. Processo em
grupo próprio (`start_new_session=True`) para poder matar tudo junto.

Resultado da sessão (`SessionResult`): `status` ∈ `ok | error | timeout | over_budget | quota | interrupted`,
`exit_code`, `peak`, `fresh`, `cache_read`, `final_text` (último `result`), `stream_path`.
- `over_budget`: ocupação > `budget_total` *(config, 128000)* ou evento de compactação.
- `quota`: texto de limite de uso detectado (padrão exato definido no S-E1).
- `interrupted`: o Engine reiniciou com a sessão em curso.

## 5. Artefatos SDD

Markdown com cabeçalho YAML entre `---`. O corpo é livre (lido por humanos e pelo pacote de
contexto); **o Jev lê só o cabeçalho**. Campos comuns: `intent`, `project`, `kind` (`prd`|`design`|
`spec`|`tasks`), `version` (incrementa a cada RETRY).

**Critério verificável** (`verify`), um destes:

| Tipo | Forma | Verificado como |
| --- | --- | --- |
| `test` | `test: tests/x/test_y.py::test_z` | pytest do nó (ou o gate `test` com o nó) sai 0 |
| `cmd` | `cmd: ["uv","run","python","-m","x","--check"]` | argv sai 0 |
| `file` | `file: {path: "x.py", contains: "def plugin_load"}` | arquivo existe e contém o texto |
| `metric` | `metric: {cmd: [...], op: "<=", value: 50}` | último número da saída compara |

Ausente, vazio ou `manual` → não verificável.

**PRD:**
```yaml
intent: INT-0007
kind: prd
sections: [problema, objetivo, requisitos, criterios_de_sucesso]
objective: "Carregar plugins de pasta sem reiniciar"
requirements:
  - id: R1
    text: "O sistema DEVE carregar plugins de ~/.local/share/magi/plugins"
    criteria:
      - id: R1.1
        text: "plugin válido aparece na lista"
        verify: {test: "tests/plugins/test_load.py::test_lista"}
```

**Design:** `components: [{id: C1, name, files: [..], requirements: [R1], interfaces: [..]}]`,
`decisions: [{id: D1, text, why}]`.

**Spec:** `items: [{id: S1, components: [C1], contracts: [..], edge_cases: [..], criteria: [{id: S1.1, text, verify}]}]`.

**Tasks:**
```yaml
tasks:
  - id: T001
    title: "Leitor de plugins"
    spec: [S1]
    reads: [magi/common/config.py]
    writes: [magi/plugins/loader.py, tests/plugins/test_load.py]
    depends: []
    criteria:
      - {id: T001.1, verify: {test: "tests/plugins/test_load.py"}}
    estimate: {code: 9000, tests: 3000}   # calculado pelo harness, não pelo agente
```

O harness **recalcula** `estimate` pelo tamanho real dos arquivos `reads`/`writes` existentes
(arquivo novo = 0) antes de passar ao Jev; o valor do agente é ignorado.

Template de `conserto`: PRD com 1 requisito ("<serviço> volta a funcionar") e critério verificável
obrigatório (teste que reproduz o erro ou `cmd` de checagem); Design com 1 componente e decisão
"sem mudança de arquitetura".

## 6. Jev

Entrada: `Evidence(fase, intenção, task?, artefatos lidos, diff, gates, sessão, critérios, histórico)`.
Saída:

```json
{"verdict": "RETRY", "rules_failed": [{"rule": "J-I02", "msg": "arquivo fora do declarado: magi/core/turn.py", "evidence": "…"}],
 "signature": "9f2e…", "attempt": 2, "at": "…"}
```

**Ordem de decisão:** (1) alguma regra marcada *HUMAN direto* falhou → HUMAN; (2) nenhuma falha →
PASS; (3) a assinatura atual já está em `signatures` da task/fase → HUMAN (loop, R10.6); (4)
`attempts` ≥ 4 → HUMAN (R10.7: 3 RETRY); (5) senão RETRY. Assinatura = sha1 das regras falhas
ordenadas + assinaturas de gate (§10 do design).

### Regras de especificação (J-S)

| Regra | Fase | Falha quando | Efeito |
| --- | --- | --- | --- |
| J-S01 | todas | cabeçalho ausente, YAML inválido ou campo obrigatório faltando | RETRY |
| J-S02 | todas | diff da sessão mexe em algo além do arquivo do artefato | HUMAN direto |
| J-S03 | PRD | falta seção, 0 requisitos, ou requisito sem critério | RETRY |
| J-S04 | PRD/SPEC/TASKS | critério sem `verify` válido (§5) | RETRY |
| J-S05 | DESIGN | requisito do PRD não coberto, ou componente cita R inexistente | RETRY |
| J-S06 | SPEC | item cita C inexistente, ou requisito sem item que o cubra (via componentes) | RETRY |
| J-S07 | TASKS | task sem `spec`, cita S inexistente, ou S sem task | RETRY |
| J-S08 | TASKS | `writes` vazio, ou caminho proibido em `writes`/`reads` | RETRY (proibido em `writes` de origem `condessa`: HUMAN direto) |
| J-S09 | TASKS | ciclo em `depends` ou dependência inexistente | RETRY |
| J-S10 | TASKS | estimativa do pacote > `budget_total − reserva` ou bloco código > 45k | RETRY |
| J-S11 | TASKS | arquivo em `writes` de duas tasks sem dependência entre elas | RETRY |
| J-S12 | todas | IDs duplicados ou fora do formato §1 | RETRY |

### Regras de implementação (J-I)

| Regra | Falha quando | Efeito |
| --- | --- | --- |
| J-I01 | algum gate do projeto com código ≠ 0 | RETRY |
| J-I02 | arquivo do diff fora de `writes` da task | RETRY |
| J-I03 | arquivo do diff em caminho proibido | HUMAN direto |
| J-I04 | linhas (+/−) > `max_diff_lines` ou arquivos > `max_diff_files` | RETRY |
| J-I05 | diff em `engine/decisions/**` ou `engine/validation/**` | HUMAN direto (mesmo se declarado) |
| J-I06 | critério da task falhou (§5) | RETRY |
| J-I07 | diff vazio ou nenhum commit | RETRY |
| J-I08 | sessão `over_budget` | RETRY com pedido de divisão (task → SPLIT, escritor gera `T003a/b` e passa por J-S07..J-S11); se a task já é filha de divisão → HUMAN |
| J-I09 | sessão `error`, `timeout` ou `interrupted` | RETRY |
| J-I10 | commit sem os trailers (§7) depois do conserto automático | RETRY |
| J-I11 | sessão `quota` | não é veredito: intenção → PAUSED, tentativa não conta |

### Regras de revisão (J-R)

O revisor devolve no `result` final só este JSON:

```json
{"findings": [{"severity": "bloqueante", "spec": "S2", "file": "magi/plugins/loader.py", "line": 40, "text": "não trata plugin sem nome"}],
 "summary": "1 frase"}
```

| Regra | Falha quando | Efeito |
| --- | --- | --- |
| J-R01 | JSON inválido | RETRY da revisão (máx. 2, depois HUMAN) |
| J-R02 | gates vermelhos no branch da intenção | RETRY (task de correção) |
| J-R03 | achado `bloqueante` | RETRY: cria `Tnnn` "correção da revisão" com os achados, `writes` = arquivos citados |
| J-R04 | 3ª rodada de revisão com bloqueante | HUMAN |

Achados `sugestao` vão para o resumo do HUMAN_OK, sem bloquear.

## 7. Commits e rastreabilidade

Último commit de cada task (o agente é instruído; o harness confere e completa):

```
<resumo em português>

Engine-Intent: INT-0007
Engine-Task: T003
Engine-Spec: S2, S3
```

`magi-engine why <arquivo>:<linha> [--project p]`:
1. `git blame -L n,n --porcelain` → commit; 2. `git log -1 --format=%B` → trailers; se não houver,
procura o primeiro commit com trailers na linha do merge (`git log --ancestry-path`);
3. lê o artefato de tasks → `spec`; spec → `components`; design → `requirements`; PRD → `objective`.

Saída (texto):
```
magi/plugins/loader.py:40  ← abc123 "Leitor de plugins"
  INT-0007 "quero um sistema de plugins" (DONE em 2026-10-09)
  T001 Leitor de plugins → S1 Carregar pasta → C1 Loader → R1 "O sistema DEVE carregar…"
  objetivo: Carregar plugins de pasta sem reiniciar
```
Sem trailer: `não veio do Engine (commit abc123, autor X)`.

## 8. `status.json` (HUD e console)

```json
{"at": "…", "paused": null, "busy": false,
 "intents": [{"id": "INT-0007", "project": "condessa", "kind": "feature", "origin": "pedro",
              "state": "IMPLEMENT", "title": "sistema de plugins",
              "task": {"id": "T002", "attempt": 2, "peak": 63000, "fresh": 21000},
              "done": 1, "total": 4, "last_verdict": {"rule": "J-I01", "verdict": "RETRY"},
              "waiting_ok": false, "tokens_fresh": 120000}],
 "waiting_ok": ["INT-0005"], "human": ["INT-0006"],
 "line": "INT-0007 · IMPLEMENT T002 (2ª) · 63k/128k"}
```

`line` substitui a linha do autoconserto no painel (`ClaudeView.autofix`). Só intenções não terminais
+ as que chegaram a DONE/DISCARDED nas últimas 24 h.

## 9. `events.jsonl`

Uma linha por evento: `{"at", "intent", "task"?, "type", ...}`. Tipos: `created`, `refused`,
`transition` (`from`, `to`, `reason`), `session_start` (`role`, `argv` sem o prompt), `session_end`
(`status`, `peak`, `fresh`), `budget_warn` (`peak`), `gates` (`results`), `verdict` (o JSON do §6),
`say` (texto), `merge` (`sha`, `services`), `rollback`, `console` (`opened|failed`). Gira ao passar de
10 MB (`events.1.jsonl`, guarda 3).

## 10. Merge (R12)

Comum: aprovação → pergunta "Faço o merge do INT-0007 no <projeto>? Diz confirma." → "confirma" em
8 s. Depois:
1. Repositório de destino (worktree principal do projeto) com `git status --porcelain
   --untracked-files=no` vazio, senão fala "o <projeto> tem mudança sem commit" e fica em HUMAN_OK.
2. Ramo atual = `main_branch`, senão idem ("tá em outro branch").
3. `git merge --no-ff --no-edit engine/INT-NNNN`; conflito → `git merge --abort`, HUMAN_OK com motivo.

**Pessoal:** fim; DONE; fala "Mesclei no <projeto>. Não fiz push." Nenhum `git push`.

**Próprio:** serviços = união dos valores de `[services]` cujos padrões casam com os arquivos do
merge (nenhum → só DONE). `systemd-run --user --unit magi-engine-guard-<INT> --collect <python> -m
magi.maintenance.autofix guard --repo R --before <sha> --state <intents/INT.json> --services …`.
O vigia grava `applied`/`reverted`; o Engine lê: `applied` → DONE; `reverted` → HUMAN com motivo
"serviço não subiu; desfiz com revert". Se `magi-engine` está entre os serviços, o Engine grava
`MERGE` antes e, ao subir, lê o resultado do vigia para fechar.

## 11. Socket e CLI

Socket `$XDG_RUNTIME_DIR/magi-engine.sock`, uma linha JSON por pedido e uma por resposta:
`{"cmd": "open", "text", "project"?, "origin", "via"}` · `status` · `pending` · `approve` (`intent`?)
· `confirm` · `discard` (`intent`?) · `continue` (`intent`?) · `pause` · `resume` · `why` (`target`).
Resposta `{"ok": bool, "say": "texto curto", "data": {...}}`. Sem `intent`: a única candidata; mais
de uma → `ok=false`, `say` lista os IDs.
Do Engine para o `magi-core`: `{"cmd": "say", "text", "level": "info|warn"}` em
`$XDG_RUNTIME_DIR/magi-core-engine.sock` (ou o canal de cards existente, decidido na task E3.2).

CLI `magi-engine <subcomando>` = os mesmos comandos + `console` (abre o Konsole) e `serve` (serviço).

## 12. Voz (R15)

| Intenção | Exemplos | Ação |
| --- | --- | --- |
| `engine.open` | "Condessa, quero …", "quero no projeto X …" | `open`; fala "Anotei como INT-0007 no X." |
| `engine.approve` | "aprova o merge", "pode mesclar", "aplica o conserto" | `approve` → confirmação falada |
| `engine.discard` | "descarta", "descarta a proposta", "descarta o conserto" | `discard` |
| `engine.status` | "como tá o engine?", "como tá o conserto?" | fala `line` |
| `engine.pending` | "o que tá esperando?" | lista HUMAN_OK e HUMAN em até 2 frases |
| `engine.continue` | "continua", "tenta de novo" | `continue` da intenção em HUMAN |

"quero …" sem "Condessa, …" no começo do turno não abre intenção (evita falso disparo em conversa):
a frase precisa começar com "quero" logo após a ativação.

Avisos: entrar em HUMAN_OK → "O INT-0007 tá pronto: <resumo>. <n> arquivos, <k> mil tokens. Quer
mesclar?"; HUMAN → "Travei no INT-0007: <regra em português>."; PAUSED por cota → "Bati o limite
do Claude Code; volto às <hora>." Uma vez por transição; com jogo aberto, guardado para o próximo turno.

## 13. Propostas da Condessa (R2)

- **Erro repetido:** a mesma linha de erro normalizada (assinatura do §10 do design) em `journalctl
  --user -p err` dos serviços dela ≥ 5 vezes em 24 h, e nenhuma intenção aberta com essa
  assinatura. Texto da intenção = resumo gerado pelo Python + linhas sanitizadas (bloco de dados).
- **Pedido recorrente:** o agente respondeu "não sei fazer / não tenho ferramenta" (marcador já
  emitido pelo agente, a definir na task E3.6) para pedidos parecidos (similaridade ≥ 85 com
  `rapidfuzz`) ≥ 3 vezes em 7 dias.
- Limites: 1 aberta por vez, 2 por semana (R2.4) *(config)*; nunca com `project` ≠ `self`
  (checado no `open`: `origin=condessa` + projeto ≠ self → recusa).

## 14. Console

Comando aprovado no S-E2 (candidato no design §13). Abre quando a 1ª intenção sai de IDEA e não há
PID vivo em `console.pid`. A visão mostra, a cada 1 s: cabeçalho (pausado? jogo aberto? janela de
5 h com fim e tokens), uma linha por intenção (ID, projeto, estado, `done/total`), a task rodando
com barra de ocupação (verde < 70%, amarelo < 85%, vermelho ≥ 85%) e as últimas 15 linhas de
eventos legíveis. Tecla `q` fecha só a janela.

## 15. Casos de borda

| # | Caso | Comportamento |
| --- | --- | --- |
| E1 | Intenção para projeto sem arquivo | recusa (R1.3), evento `refused`, nada criado |
| E2 | Projeto pessoal cujo remoto é GitLab | recusa antes de ler qualquer arquivo além de `.git/config` |
| E3 | Duas intenções abertas no mesmo projeto | permitido; branches separados; o 2º merge pode conflitar (HUMAN_OK) |
| E4 | Pedro aprova com repositório sujo | fica em HUMAN_OK, fala o motivo, aprovação pode ser repetida |
| E5 | "aprova o merge" com 2 intenções em HUMAN_OK | pergunta qual (lista IDs); não faz nada |
| E6 | Sessão compacta o contexto | `over_budget` (J-I08) |
| E7 | Task dividida estoura de novo | HUMAN |
| E8 | Agente cria arquivo não declarado (ex.: `__init__.py`) | J-I02 RETRY com o nome; o escritor de tasks é orientado a declarar `__init__.py` |
| E9 | Gate com saída enorme | cauda de 40 linhas no veredito; saída completa em `runs/.../gates.json` |
| E10 | Gate trava | tempo limite → código 124, conta como gate vermelho |
| E11 | Engine reinicia durante MERGE do próprio projeto | lê o resultado do vigia em `intents/INT.json` e fecha (§10) |
| E12 | Jogo abre no meio de uma task | a sessão termina; nenhuma nova até fechar |
| E13 | Limite da assinatura | PAUSED até `window_end`; tentativa não conta |
| E14 | Intenção de origem `condessa` gera task que escreve `engine/**` | J-S08 HUMAN direto |
| E15 | Artefato com IDs duplicados | J-S12 RETRY |
| E16 | Worktree já existe (sobra de queda) | `git worktree remove --force` e recria; branch da task recriado da base |
| E17 | Pedro mexe no branch da intenção à mão | permitido; Jev usa o diff da task (base = ponta do branch da intenção no início da task) |
| E18 | Revisor devolve texto fora do JSON | J-R01 |
| E19 | Konsole ausente ou sem display | evento `console failed`; segue |
| E20 | `claude` não logado | PAUSED "Claude Code sem login"; aviso uma vez |
| E21 | "descarta" durante sessão rodando | mata o grupo, DISCARDED, worktrees apagadas, branches mantidos |
| E22 | Conserto (autofix) com intenção `conserto` já aberta | "Já tô mexendo nisso" (como `SAY_BUSY`) |

## 16. Critérios de aceite

Cada critério tem a verificação entre colchetes (teste ou comando). `tests/engine/` é a pasta.

| ID | Requisito | Critério | Verifica |
| --- | --- | --- | --- |
| CA-01 | R1.1–R1.2 | `open` cria INT em IDEA com projeto padrão `self` | [test `test_service.py::test_open_default_self`] |
| CA-02 | R1.3, R3.3 | projeto sem arquivo ou inválido é recusado com mensagem | [test `test_projects.py::test_recusa_sem_arquivo`, `::test_recusa_invalido`] |
| CA-03 | R1.4, R3.4, RNF-06 | caminho com "sume" e remoto GitLab recusados sem ler além de `.git/config` | [test `test_projects.py::test_empresa`] |
| CA-04 | R2.3–R2.4, R2.6 | `origin=condessa` para projeto pessoal recusado; 3ª proposta na semana recusada | [test `test_proposals.py`] |
| CA-05 | R4.3–R4.4, R6.1–R6.4 | cada regra J-S tem um artefato de exemplo que falha só nela | [test `test_rules_sdd.py`] |
| CA-06 | R5.1–R5.3 | toda transição fora da tabela §3 levanta erro e não grava; válidas geram evento | [test `test_machine.py`] |
| CA-07 | R5.4, RNF-08 | reinício com task RUNNING → `interrupted` → RETRY; worktree órfã removida | [test `test_orchestrator.py::test_retoma`] |
| CA-08 | R6.5, R10.6–R10.7 | mesma assinatura 2× → HUMAN; 4ª tentativa → HUMAN | [test `test_jev.py::test_loop`, `::test_limite`] |
| CA-09 | R7.1–R7.4 | pacote respeita limites por bloco, corta com marcador, código > 45k recusado | [test `test_builder.py`] |
| CA-10 | R8.1–R8.3 | argv de cada papel igual ao §4, com a lista negada | [test `test_agents.py`] |
| CA-11 | R8.5–R8.6 | com `busy()` verdadeiro nenhuma sessão abre; `quota` → PAUSED sem contar tentativa | [test `test_orchestrator.py::test_jogo`, `::test_cota`] |
| CA-12 | R9.1–R9.2, RNF-01 | `claude` falso que passa de 128k é morto em ≤ 11 s e dá `over_budget` | [test `test_runner.py::test_estouro`] |
| CA-13 | R10.1–R10.5, R10.8 | cada regra J-I tem caso que falha só nela | [test `test_rules_impl.py`] |
| CA-14 | R10.10, RNF-04 | `decide` com a mesma entrada 100× dá o mesmo veredito, < 1 s | [test `test_jev.py::test_deterministico`] |
| CA-15 | R11.1–R11.2 | achado bloqueante vira task de correção; sugestão não bloqueia | [test `test_rules_review.py`] |
| CA-16 | R12.3, R12.7 | merge pessoal em repo temporário: `--no-ff`, nenhum push | [test `test_merge.py::test_pessoal`] |
| CA-17 | R12.4 | merge próprio com `systemctl` falso que falha → revert e HUMAN | [test `test_merge.py::test_rollback`] |
| CA-18 | R12.5 | repo sujo ou conflito → HUMAN_OK, nada mesclado | [test `test_merge.py::test_sujo`, `::test_conflito`] |
| CA-19 | R13.1–R13.3 | `why` em repo temporário mostra a cadeia até o objetivo; sem trailer avisa | [test `test_why.py`] |
| CA-20 | R14.1–R14.4, RNF-07 | `launch` chama exatamente o argv do SE2; nenhuma chamada a `qdbus`/`gdbus` | [test `test_console.py`] |
| CA-21 | R15.1 | `ClaudeStats` com `status.json` de exemplo preenche `engine` e `line` | [test `tests/hud/test_wired_data.py::test_engine`] |
| CA-22 | R15.3 | frases da §12 resolvem para as intenções certas no roteador | [test `tests/core/test_router.py::test_engine`] |
| CA-23 | R16.1–R16.3 | "prepara um conserto" abre INT `conserto`; "aplica" chama `approve` | [test `tests/maintenance/test_autofix.py::test_engine`] |
| CA-24 | R17.1–R17.2 | bloco de decisões traz só o mesmo projeto, ≤ 5k, mais recentes primeiro | [test `test_ledger.py`] |
| CA-25 | Sucesso 1 | projeto de brinquedo + `claude` falso vai de IDEA a DONE com 1 aprovação | [test `test_e2e.py`] |
