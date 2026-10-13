"""Spike S5 — ``procrastinate`` 3.10 (tarefa Y0.4 de ``specs/ayanami-central``).

Roda no PC contra o contêiner descartável ``ayanami-pg-teste`` (``AYANAMI_TEST_DSN``, porta 54340).
Cria uma base própria ``ayanami_s5_<hex>``, aplica o esquema da lib e a apaga no fim. Responde às
perguntas da linha S5 da spec §17:

  api        nomes da 3.10: ``retry_stalled_jobs``? ``on_job_status``? assinaturas usadas
  abort      ``cancel_job_by_id_async`` na fila e com ``abort=True`` (async e síncrona), com e
             sem LISTEN/NOTIFY; tempo do pedido ao estado ``aborted``
  lock       ``queueing_lock`` + ``AlreadyEnqueued`` (em ``todo``, em ``doing`` e depois de pronto)
  status     ganchos de estado: ``worker_middleware`` vendo ok/falha/abort
  reinicio   job longo (30 min) num worker em processo filho; ``kill -9``; o job fica em
             ``doing``; outro worker sobe; ``get_stalled_jobs`` + ``retry_job`` → roda de novo;
             depois ``SIGTERM`` com ``shutdown_graceful_timeout``
  notify     LISTEN ``ayanami_eventos`` com ``pg_notify`` saindo das tarefas (perda e latência)
  cron       próximo disparo de ``0 4 * * *`` pelo código das ``periodic`` com ``TZ`` diferente
  all        tudo acima (padrão)

Uso:  eval "$(deploy/ayanami/pg-teste.sh dsn)"
      uv run --extra ayanami python spikes/ayanami_s5_procrastinate.py all
Nada fora do ``ayanami-pg-teste``; recusa a porta 54329 e a base ``magi``.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import secrets
import signal
import statistics
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import procrastinate
import psycopg
from procrastinate import exceptions, jobs, testing
from procrastinate import worker as pworker
from procrastinate.manager import JobManager
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from ayanami.db import recusar_magi  # noqa: E402

CANAL = "ayanami_eventos"
EVENTOS: list[tuple[str, int, str, float]] = []  # (gancho, job_id, desfecho, t)


def log(chave: str, valor: Any) -> None:
    print(f"[S5] {chave}: {valor}", flush=True)


# ---------------------------------------------------------------- app e tarefas


async def gancho_status(call_next: Callable[[], Awaitable[Any]], context: Any, worker: Any) -> Any:
    """Worker middleware: o substituto do ``on_job_status`` (que não existe na 3.10)."""
    jid = context.job.id
    EVENTOS.append(("inicio", jid, "doing", time.monotonic()))
    try:
        r = await call_next()
    except exceptions.JobAborted:
        EVENTOS.append(("fim", jid, "aborted(JobAborted)", time.monotonic()))
        raise
    except asyncio.CancelledError:
        EVENTOS.append(("fim", jid, "aborted(CancelledError)", time.monotonic()))
        raise
    except Exception as e:
        EVENTOS.append(("fim", jid, f"failed({type(e).__name__})", time.monotonic()))
        raise
    EVENTOS.append(("fim", jid, "succeeded", time.monotonic()))
    return r


def montar_app(dsn: str) -> procrastinate.App:
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=dsn))

    @app.task(name="s5.dorme_async", queue="rapida", pass_context=True)
    async def dorme_async(context: procrastinate.JobContext, segundos: float) -> None:
        await asyncio.sleep(segundos)

    @app.task(name="s5.dorme_sync", queue="rapida", pass_context=True)
    def dorme_sync(context: procrastinate.JobContext, segundos: float, checar_s: float) -> None:
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            if context.should_abort():
                raise exceptions.JobAborted()
            time.sleep(checar_s)

    @app.task(name="s5.rapida", queue="rapida")
    async def rapida(n: int) -> int:
        return n

    @app.task(name="s5.falha", queue="rapida")
    async def falha() -> None:
        raise RuntimeError("falha de propósito")

    @app.task(name="s5.notifica", queue="rapida")
    async def notifica(n: int) -> None:
        payload = f"{n}:{time.time():.6f}"
        await app.connector.execute_query_async("SELECT pg_notify(%(c)s, %(p)s)", c=CANAL, p=payload)

    @app.task(
        name="s5.longa",
        queue="lenta",
        retry=procrastinate.RetryStrategy(max_attempts=3, wait=0),
    )
    async def longa(segundos: float) -> None:
        await asyncio.sleep(segundos)

    return app


class Worker:
    """Worker em processo (tarefa asyncio), parado por ``cancel()``."""

    def __init__(self, app: procrastinate.App, **opcoes: Any) -> None:
        o: dict[str, Any] = {
            "queues": ["rapida"],
            "concurrency": 8,
            "install_signal_handlers": False,
            "shutdown_graceful_timeout": 2,
            "worker_middleware": [gancho_status],
        }
        o.update(opcoes)
        self._t = asyncio.create_task(app.run_worker_async(**o))

    async def parar(self) -> None:
        self._t.cancel()
        try:
            await self._t
        except asyncio.CancelledError:
            pass


async def esperar_status(app: procrastinate.App, jid: int, alvo: set[str], prazo: float) -> tuple[str, float]:
    t0 = time.monotonic()
    st = ""
    while time.monotonic() - t0 < prazo:
        st = (await app.job_manager.get_job_status_async(jid)).value
        if st in alvo:
            return st, time.monotonic() - t0
        await asyncio.sleep(0.02)
    return st, time.monotonic() - t0


# ---------------------------------------------------------------- perguntas


async def p_api(app: procrastinate.App) -> None:
    jm = JobManager
    log("versao", procrastinate.__version__)
    log("JobManager.retry_stalled_jobs existe", hasattr(jm, "retry_stalled_jobs"))
    log("App.on_job_status existe", hasattr(procrastinate.App, "on_job_status"))
    for nome in ("get_stalled_jobs", "retry_job", "cancel_job_by_id_async", "prune_stalled_workers"):
        log(f"JobManager.{nome}", inspect.signature(getattr(jm, nome)))
    w = inspect.signature(pworker.Worker.__init__)
    opcoes = ("abort_job_polling_interval", "update_heartbeat_interval", "stalled_worker_timeout",
              "shutdown_graceful_timeout", "listen_notify", "worker_middleware", "task_middleware")
    log("Worker opções", {k: w.parameters[k].default for k in opcoes})
    log("Status", [s.value for s in jobs.Status])


async def p_abort(app: procrastinate.App) -> None:
    for notify in (True, False):
        w = Worker(app, listen_notify=notify)
        await asyncio.sleep(0.5)
        # na fila: agenda para daqui a 1 h, cancela, confere que nunca roda
        jid = await app.configure_task("s5.rapida", schedule_in={"hours": 1}).defer_async(n=1)
        ok = await app.job_manager.cancel_job_by_id_async(jid)
        st, _ = await esperar_status(app, jid, {"cancelled"}, 2)
        log(f"[notify={notify}] cancelar na fila → retorno/estado", f"{ok} / {st}")

        for tarefa, kw in (("s5.dorme_async", {"segundos": 1800}),
                           ("s5.dorme_sync", {"segundos": 1800, "checar_s": 5.0})):
            jid = await app.configure_task(tarefa).defer_async(**kw)
            await esperar_status(app, jid, {"doing"}, 10)
            await asyncio.sleep(1.0)
            t0 = time.monotonic()
            ok = await app.job_manager.cancel_job_by_id_async(jid, abort=True)
            st, dt = await esperar_status(app, jid, {"aborted", "succeeded", "failed"}, 20)
            fim = [e for e in EVENTOS if e[1] == jid and e[0] == "fim"]
            gancho = f"{fim[-1][2]} em {fim[-1][3] - t0:.2f} s" if fim else "nada"
            log(f"[notify={notify}] abort {tarefa}",
                f"retorno={ok} estado={st} em {dt:.2f} s; middleware={gancho}")
        await w.parar()


async def p_lock(app: procrastinate.App) -> None:
    chave = "tarefa:abc"
    j1 = await app.configure_task("s5.dorme_async", queueing_lock=chave).defer_async(segundos=1.5)
    try:
        await app.configure_task("s5.dorme_async", queueing_lock=chave).defer_async(segundos=1.5)
        log("2º defer com o job em todo", "aceito (!)")
    except exceptions.AlreadyEnqueued as e:
        log("2º defer com o job em todo", f"AlreadyEnqueued ({e})")
    w = Worker(app)
    await esperar_status(app, j1, {"doing"}, 10)
    try:
        j2 = await app.configure_task("s5.dorme_async", queueing_lock=chave).defer_async(segundos=0.1)
        log("defer com o 1º em doing", f"aceito: job {j2} (o lock só vale em todo)")
    except exceptions.AlreadyEnqueued:
        j2 = None
        log("defer com o 1º em doing", "AlreadyEnqueued")
    st, _ = await esperar_status(app, j1, {"succeeded"}, 10)
    if j2:
        await esperar_status(app, j2, {"succeeded"}, 10)
    j3 = await app.configure_task("s5.dorme_async", queueing_lock=chave).defer_async(segundos=0.1)
    log("defer depois de succeeded", f"aceito: job {j3}")
    await esperar_status(app, j3, {"succeeded"}, 10)
    await w.parar()


async def p_status(app: procrastinate.App) -> None:
    EVENTOS.clear()
    w = Worker(app)
    j_ok = await app.configure_task("s5.rapida").defer_async(n=7)
    j_err = await app.configure_task("s5.falha").defer_async()
    await esperar_status(app, j_ok, {"succeeded"}, 10)
    await esperar_status(app, j_err, {"failed"}, 10)
    await asyncio.sleep(0.2)
    await w.parar()
    vistos = {jid: [d for g, j, d, _ in EVENTOS if j == jid] for jid in (j_ok, j_err)}
    log("middleware ok/falha", vistos)


async def p_notify(app: procrastinate.App, dsn: str, n: int) -> None:
    ouvinte = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    await ouvinte.execute(sql.SQL("LISTEN {}").format(sql.Identifier(CANAL)))
    recebidos: list[float] = []

    async def ouvir() -> None:
        async for m in ouvinte.notifies():
            _, t = m.payload.split(":")
            recebidos.append(time.time() - float(t))

    t_ouvir = asyncio.create_task(ouvir())
    w = Worker(app)
    t0 = time.monotonic()
    for i in range(n):
        await app.configure_task("s5.notifica").defer_async(n=i)
    while len(recebidos) < n and time.monotonic() - t0 < 30:
        await asyncio.sleep(0.05)
    dur = time.monotonic() - t0
    await w.parar()
    t_ouvir.cancel()
    await ouvinte.close()
    ms = sorted(x * 1000 for x in recebidos)
    p90 = ms[int(len(ms) * 0.9) - 1] if ms else float("nan")
    log("NOTIFY recebidos", f"{len(recebidos)}/{n} em {dur:.2f} s (8 em paralelo)")
    if ms:
        log("NOTIFY latência tarefa→ouvinte ms",
            f"p50={statistics.median(ms):.1f} p90={p90:.1f} máx={ms[-1]:.1f}")


def _cron_filho() -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())

    @app.periodic(cron="0 4 * * *", periodic_id="teste")
    @app.task(name="s5.cron")
    async def cron(timestamp: int) -> None: ...

    pt = next(iter(app.periodic_registry.periodic_tasks.values()))
    at = datetime(2026, 10, 12, 12, 0, tzinfo=UTC).timestamp()
    nxt = pt.croniter.get_next(ret_type=float, start_time=at)
    utc = datetime.fromtimestamp(nxt, UTC)
    local = datetime.fromtimestamp(nxt).astimezone()
    print(f"{utc:%Y-%m-%d %H:%M} UTC = {local:%Y-%m-%d %H:%M %Z}")


async def p_cron() -> None:
    for tz in ("America/Sao_Paulo", "UTC"):
        env = {**os.environ, "TZ": tz}
        r = subprocess.run([sys.executable, __file__, "_cron"], env=env, capture_output=True, text=True,
                           check=True)
        log(f"periodic '0 4 * * *' depois de 2026-10-12 12:00 UTC com TZ={tz}", r.stdout.strip())


def _filho(dsn: str, rotulo: str) -> subprocess.Popen[str]:
    env = {**os.environ, "S5_DSN": dsn}
    return subprocess.Popen([sys.executable, __file__, "_worker", rotulo], env=env, text=True)


async def _worker_filho() -> None:
    app = montar_app(os.environ["S5_DSN"])
    async with app.open_async():
        await app.run_worker_async(
            queues=["lenta"], concurrency=1, update_heartbeat_interval=1, stalled_worker_timeout=3,
            shutdown_graceful_timeout=2, listen_notify=True,
        )


async def p_reinicio(app: procrastinate.App, dsn: str) -> None:
    jid = await app.configure_task("s5.longa").defer_async(segundos=1800)
    f1 = _filho(dsn, "w1")
    st, dt = await esperar_status(app, jid, {"doing"}, 30)
    j = next(iter(await app.job_manager.list_jobs_async(id=jid)))
    log("job de 30 min no worker 1", f"{st} em {dt:.1f} s (worker_id={j.worker_id}, tentativas={j.attempts})")
    await asyncio.sleep(2)
    f1.send_signal(signal.SIGKILL)
    f1.wait()
    await asyncio.sleep(1)
    j = next(iter(await app.job_manager.list_jobs_async(id=jid)))
    log("depois do kill -9 do worker 1", f"estado={j.status} worker_id={j.worker_id}")

    f2 = _filho(dsn, "w2")
    t0 = time.monotonic()
    presos: list[jobs.Job] = []
    while time.monotonic() - t0 < 30:
        presos = [x for x in await app.job_manager.get_stalled_jobs(queue="lenta", seconds_since_heartbeat=3)
                  if x.id == jid]
        if presos:
            break
        await asyncio.sleep(0.2)
    log("get_stalled_jobs(seconds_since_heartbeat=3) achou",
        f"{bool(presos)} em {time.monotonic() - t0:.1f} s")
    if presos:
        await app.job_manager.retry_job(presos[0])
    st, dt = await esperar_status(app, jid, {"doing"}, 30)
    await asyncio.sleep(0.5)
    j = next(iter(await app.job_manager.list_jobs_async(id=jid)))
    log("depois do retry_job", f"{st} em {dt:.1f} s no worker_id={j.worker_id}, tentativas={j.attempts}")

    await asyncio.sleep(1)
    f2.send_signal(signal.SIGTERM)
    t0 = time.monotonic()
    rc = await asyncio.to_thread(f2.wait, 20)
    j = next(iter(await app.job_manager.list_jobs_async(id=jid)))
    log("SIGTERM no worker 2 (graceful 2 s)",
        f"saiu rc={rc} em {time.monotonic() - t0:.1f} s; job estado={j.status} tentativas={j.attempts}")

    f3 = _filho(dsn, "w3")
    st, dt = await esperar_status(app, jid, {"doing"}, 15)
    log("worker 3 pega o job de volta sozinho", f"{st} em {dt:.1f} s")
    await app.job_manager.cancel_job_by_id_async(jid, abort=True)
    await esperar_status(app, jid, {"aborted", "failed", "todo"}, 15)
    f3.send_signal(signal.SIGTERM)
    await asyncio.to_thread(f3.wait, 20)


# ---------------------------------------------------------------- base descartável


def dsn_teste() -> str:
    dsn = os.environ.get("AYANAMI_TEST_DSN", "")
    if not dsn:
        sys.exit('defina AYANAMI_TEST_DSN: eval "$(deploy/ayanami/pg-teste.sh dsn)"')
    recusar_magi(dsn)
    return dsn


async def main_async(args: argparse.Namespace) -> None:
    admin_dsn = dsn_teste()
    nome = f"ayanami_s5_{secrets.token_hex(4)}"
    partes = conninfo_to_dict(admin_dsn)
    dsn = make_conninfo(**{**partes, "dbname": nome})
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    try:
        app = montar_app(dsn)
        async with app.open_async():
            await app.schema_manager.apply_schema_async()
            q = args.pergunta
            if q in ("api", "all"):
                await p_api(app)
            if q in ("lock", "all"):
                await p_lock(app)
            if q in ("status", "all"):
                await p_status(app)
            if q in ("abort", "all"):
                await p_abort(app)
            if q in ("notify", "all"):
                await p_notify(app, dsn, args.n)
            if q in ("reinicio", "all"):
                await p_reinicio(app, dsn)
            if q in ("cron", "all"):
                await p_cron()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))


def main() -> None:
    logging.getLogger("procrastinate").setLevel(logging.CRITICAL)
    if len(sys.argv) >= 2 and sys.argv[1] == "_cron":
        _cron_filho()
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "_worker":
        asyncio.run(_worker_filho())
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pergunta", nargs="?", default="all",
                    choices=["api", "abort", "lock", "status", "reinicio", "notify", "cron", "all"])
    ap.add_argument("--n", type=int, default=500, help="NOTIFYs no teste de perda (padrão 500)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
