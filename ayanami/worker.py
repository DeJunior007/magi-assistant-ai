"""``ayanami worker <fila>`` e ``ayanami batimento <fila> --max S`` (dono: Y3.1; spec §4.1).

- :func:`rodar`: ``app.run_worker_async(queues=[fila], concurrency=n, shutdown_graceful_timeout=30,
  listen_notify=True, worker_middleware=[on_job_status(deps)], additional_context={"deps": deps})``
  + tarefa de fundo que grava ``workers_batimento`` a cada 30 s. Só o worker ``agendada`` registra
  as periódicas (os outros nem deferem crons).
- :func:`cli_batimento`: healthcheck do Compose — sai 0 se a fila tem batimento há no máximo
  ``--max`` segundos, 1 se não tem (ou está velho), 2 em erro de uso/banco.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import socket
import sys
from collections.abc import Sequence
from typing import Any

from ayanami import fila as filamod
from ayanami.db import Db, transacao
from ayanami.deps import Deps
from ayanami.tarefas import on_job_status

log = logging.getLogger("ayanami.worker")

BATIMENTO_S = 30
GRACEFUL_S = 30


def concorrencia(deps: Deps, fila: str) -> int:
    return int(getattr(deps.cfg.fila, f"{fila}_concorrencia"))


def gravar_batimento(db: Db, fila: str, host: str, agora: Any) -> None:
    with transacao(db) as conn:
        conn.execute(
            "INSERT INTO workers_batimento (fila, host, visto) VALUES (%s, %s, %s)"
            " ON CONFLICT (fila) DO UPDATE SET host = EXCLUDED.host, visto = EXCLUDED.visto",
            (fila, host, agora),
        )


async def bater(deps: Deps, fila: str, host: str) -> None:
    try:
        await asyncio.to_thread(gravar_batimento, deps.db, fila, host, deps.relogio.agora())
    except Exception as e:  # banco piscou: tenta no próximo batimento
        log.warning("batimento %s falhou (%s)", fila, type(e).__name__)


async def batendo(deps: Deps, fila: str, host: str, intervalo: float = BATIMENTO_S,
                  *, dormir_antes: bool = False) -> None:
    while True:
        if dormir_antes:
            await deps.relogio.dormir(intervalo)
        await bater(deps, fila, host)
        if not dormir_antes:
            await deps.relogio.dormir(intervalo)


async def rodar(app: Any, deps: Deps, fila: str, *, host: str | None = None, **opcoes: Any) -> None:
    """Roda o worker de ``fila`` até ser parado (``opcoes`` sobrepõe as do ``run_worker_async``)."""
    if fila not in filamod.FILAS:
        raise ValueError(f"fila desconhecida: {fila}")
    host = host or socket.gethostname()
    kw: dict[str, Any] = {
        "queues": [fila], "concurrency": concorrencia(deps, fila),
        "shutdown_graceful_timeout": GRACEFUL_S, "listen_notify": True, "name": f"{fila}@{host}",
        "worker_middleware": [on_job_status(deps)], "additional_context": {"deps": deps},
    }
    kw.update(opcoes)
    await bater(deps, fila, host)  # o healthcheck já vê o worker antes do 1º job
    bate = asyncio.create_task(batendo(deps, fila, host, dormir_antes=True), name=f"batimento-{fila}")
    try:
        await app.run_worker_async(**kw)
    finally:
        bate.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bate


def _deps_de_producao() -> Deps:
    from ayanami import config as cfgmod
    from ayanami.db import abrir_pool, dsn_padrao

    cfg = cfgmod.ler(cfgmod.CAMINHO_PADRAO)
    return Deps(db=abrir_pool(dsn_padrao(), nome="ayanami-worker"), cfg=cfg)


def _parser_fila(prog: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog)
    p.add_argument("fila", choices=filamod.FILAS)
    return p


def cli(args: Sequence[str]) -> int:
    ns = _parser_fila("ayanami worker").parse_args(list(args))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    deps = _deps_de_producao()
    app = filamod.app_de_producao(periodicas=ns.fila == "agendada")

    async def principal() -> None:
        async with app.open_async():
            await rodar(app, deps, ns.fila)

    try:
        asyncio.run(principal())
    except KeyboardInterrupt:  # pragma: no cover
        pass
    return 0


def ultimo_batimento(db: Db, fila: str) -> Any:
    with db.connection() as conn:
        r = conn.execute("SELECT visto FROM workers_batimento WHERE fila = %s", (fila,)).fetchone()
        if not conn.autocommit:
            conn.rollback()
    return r[0] if r else None


def checar_batimento(db: Db, fila: str, maximo_s: float, agora: Any) -> bool:
    visto = ultimo_batimento(db, fila)
    return visto is not None and (agora - visto).total_seconds() <= maximo_s


def cli_batimento(args: Sequence[str], *, db: Db | None = None, relogio: Any = None) -> int:
    p = _parser_fila("ayanami batimento")
    p.add_argument("--max", type=float, default=90.0, help="segundos sem batimento (padrão 90)")
    ns = p.parse_args(list(args))
    try:
        if db is None:
            import psycopg

            from ayanami.db import ConexaoUnica, dsn_padrao, recusar_magi

            dsn = dsn_padrao()
            recusar_magi(dsn)
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                return _veredito(ConexaoUnica(conn), ns.fila, ns.max, relogio)
        return _veredito(db, ns.fila, ns.max, relogio)
    except Exception as e:
        print(f"ayanami batimento: {type(e).__name__}", file=sys.stderr)
        return 2


def _veredito(db: Db, fila: str, maximo: float, relogio: Any) -> int:
    from ayanami.relogio import RelogioReal

    agora = (relogio or RelogioReal()).agora()
    if checar_batimento(db, fila, maximo, agora):
        return 0
    print(f"ayanami batimento: {fila} sem batimento há mais de {maximo:g} s", file=sys.stderr)
    return 1
