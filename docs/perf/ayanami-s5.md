# Spike S5 — `procrastinate` 3.10

Tarefa Y0.4 de `specs/ayanami-central/tasks.md`. Rodado no PC contra o contêiner descartável
`ayanami-pg-teste` (base própria `ayanami_s5_<hex>`, apagada no fim), `procrastinate==3.10.0`:

```sh
eval "$(deploy/ayanami/pg-teste.sh dsn)"
uv run --extra ayanami python spikes/ayanami_s5_procrastinate.py all
```

## Respostas (linha S5 da spec §17)

| Pergunta | Resultado | Evidência (saída do script, 2026-10-12) |
| --- | --- | --- |
| `retry_stalled_jobs` (nome) | **mudou para** `job_manager.get_stalled_jobs(seconds_since_heartbeat=…)` + `job_manager.retry_job(job)` | `retry_stalled_jobs existe: False` |
| `cancel_job_by_id_async(abort=True)`, parada ≤ 10 s | **confirmado** (≤ 5 s) | async: `aborted em 0.02 s`; síncrona checando a cada 5 s: `aborted em 4.00 s`; sem NOTIFY: `4.01 s` |
| cancelar na fila | **confirmado** | `cancelar na fila → True / cancelled` (agendado, nunca rodou) |
| `queueing_lock` + `AlreadyEnqueued` | **confirmado, só em `todo`** | 2º defer em `todo` → `AlreadyEnqueued`; com o 1º em `doing` → aceito; depois de `succeeded` → aceito |
| `on_job_status` | **mudou para** `worker_middleware` | `App.on_job_status existe: False`; middleware viu `succeeded`, `failed(RuntimeError)`, `aborted(CancelledError)`, `aborted(JobAborted)` |
| job de 30 min sobrevive a reinício | **confirmado** (com `fila.reanimar` e `retry`) | `kill -9` → fica `doing`; `get_stalled_jobs` acha em 2 s; `retry_job` → outro worker roda (`tentativas=1`); `SIGTERM` (graceful 2 s) → `todo` sozinho (`tentativas=2`), worker 3 pega em 0,2 s |
| LISTEN/NOTIFY → API | **confirmado** | `500/500` recebidos, latência tarefa→ouvinte p50 0,9 ms, p90 1,1 ms, máx 7,3 ms (8 em paralelo) |
| cron das `periodic` segue o `TZ` [DS9] | **não**: o cron é sempre UTC | `0 4 * * *` com `TZ=America/Sao_Paulo` → `04:00 UTC = 01:00 -03`; com `TZ=UTC` → igual |

## Notas para a Y3.1

- **Jobs presos** (`fila.reanimar`): `for j in await app.job_manager.get_stalled_jobs(
  seconds_since_heartbeat=300): await app.job_manager.retry_job(j)`. Usa o batimento da própria lib
  (`procrastinate_workers.last_heartbeat`, `update_heartbeat_interval=10` s); o `workers_batimento`
  da Ayanami fica só para o painel/saúde. O job retomado começa do zero (`attempts` +1).
- **Parada limpa**: `SIGTERM` com `shutdown_graceful_timeout=30` aborta os jobs em curso com motivo
  "shutdown"; com `retry` eles voltam a `todo` gastando uma tentativa, sem `retry` ficam `aborted`.
  Tarefas longas precisam ser retomáveis e ter `max_attempts` ≥ 2; no Compose, `stop_grace_period`
  ≥ 35 s nos workers (o padrão do Docker é 10 s, que mata antes do graceful).
- **Abort**: com `listen_notify=True` o pedido chega por NOTIFY (o esquema da lib tem gatilho
  `procrastinate_notify_queue_abort_job_v1`); sem NOTIFY, polling de `abort_job_polling_interval=5`
  s. Tarefa async recebe `CancelledError`; a síncrona tem de checar `context.should_abort()` e
  levantar `procrastinate.exceptions.JobAborted` (se só retornar, o job vira `succeeded`).
- **Estado em `tarefas`**: `worker_middleware=[f]` com `async def f(call_next, context, worker)` em
  `run_worker_async`; envolve jobs async e síncronos no loop. Um `failed` com tentativa sobrando volta
  a `todo` (o middleware vê a exceção, não o estado final: consultar `get_job_status_async` ou o
  `retry` da tarefa). O cancelamento em `todo` não passa pelo worker: `cancelar_tarefa` grava.
- **Idempotência**: o `queueing_lock` não cobre o job em `doing`; quem segura é o índice
  `tarefas_chave_viva` da tabela `tarefas`.
- **Crons**: o `PeriodicDeferrer` passa `time.time()` (float) ao `croniter`, que o lê como UTC. Os
  crons da §4.2 foram convertidos para UTC (local + 3 h; São Paulo sem horário de verão desde 2019).
- Avisos da lib: o `App` no `__main__` gera "App is instantiated in the main Python module" (só no
  script); na Ayanami o `app` mora em `ayanami/fila.py`.
