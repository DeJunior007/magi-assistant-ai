"""Manutenção da fila e do banco (dono: Y3.1; spec §3 "Retenção", §4.1, §4.2, S5).

- ``limpeza.diaria`` (:func:`limpeza_diaria`): apaga pelo relógio injetado o que passou dos prazos
  da §3 — ``auditoria`` > 90 dias, ``eventos`` > 30 dias, ``nuvem_turnos`` sincronizados > 30
  dias, ``confirmacoes`` > 7 dias (pela ``expira``), jobs ``succeeded``/``cancelled`` do
  ``procrastinate`` > 30 dias (pelo último evento do job), ``pareamentos`` expirados > 1 dia — e os
  arquivos de ``<dados>/entrada/`` com mais de 2 dias.
- ``fila.reanimar`` (:func:`reanimar`): a 3.10 não tem ``retry_stalled_jobs`` (S5); jobs em
  ``doing`` de worker sem batimento há > 300 s voltam a ``todo`` por ``get_stalled_jobs`` +
  ``retry_job`` e a tarefa ligada volta a ``na_fila``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from procrastinate import JobContext

from ayanami.db import Db, transacao
from ayanami.deps import Deps

log = logging.getLogger("ayanami.manutencao")

SEM_BATIMENTO_S = 300
ENTRADA_DIAS = 2

# (nome no resultado, SQL com %(limite)s, dias)
RETENCAO: tuple[tuple[str, str, int], ...] = (
    ("auditoria", "DELETE FROM auditoria WHERE ts < %(limite)s", 90),
    ("eventos", "DELETE FROM eventos WHERE criado < %(limite)s", 30),
    ("nuvem_turnos", "DELETE FROM nuvem_turnos WHERE sincronizado IS NOT NULL"
                     " AND sincronizado < %(limite)s", 30),
    ("confirmacoes", "DELETE FROM confirmacoes WHERE expira < %(limite)s", 7),
    ("pareamentos", "DELETE FROM pareamentos WHERE expira < %(limite)s", 1),
)
JOBS_DIAS = 30
_JOBS_VELHOS = """
SELECT j.id FROM procrastinate_jobs j
JOIN LATERAL (SELECT max(e.at) AS ultimo FROM procrastinate_events e WHERE e.job_id = j.id) u ON true
WHERE j.status::text IN ('succeeded', 'cancelled') AND u.ultimo < %(limite)s
"""


def limpar_banco(db: Db, agora: datetime) -> dict[str, int]:
    """Apaga o que passou da retenção da §3; devolve quantas linhas saíram por tabela."""
    saida: dict[str, int] = {}
    with transacao(db) as conn:
        for nome, sql, dias in RETENCAO:
            saida[nome] = conn.execute(sql, {"limite": agora - timedelta(days=dias)}).rowcount
        saida["procrastinate_jobs"] = _limpar_jobs(conn, agora - timedelta(days=JOBS_DIAS))
    return saida


def _limpar_jobs(conn: psycopg.Connection, limite: datetime) -> int:
    if conn.execute("SELECT to_regclass('procrastinate_jobs')").fetchone()[0] is None:
        return 0
    ids = [r[0] for r in conn.execute(_JOBS_VELHOS, {"limite": limite}).fetchall()]
    if not ids:
        return 0
    # periodic_defers referencia o job sem ON DELETE CASCADE
    conn.execute("UPDATE procrastinate_periodic_defers SET job_id = NULL WHERE job_id = ANY(%s)", (ids,))
    return conn.execute("DELETE FROM procrastinate_jobs WHERE id = ANY(%s)", (ids,)).rowcount


def limpar_entrada(dados: Path, agora: datetime, dias: int = ENTRADA_DIAS) -> int:
    """Remove arquivos de ``<dados>/entrada/`` modificados há mais de ``dias``."""
    pasta = dados / "entrada"
    if not pasta.is_dir():
        return 0
    limite = (agora - timedelta(days=dias)).timestamp()
    n = 0
    for f in pasta.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink() and f.stat().st_mtime < limite:
                f.unlink()
                n += 1
        except OSError as e:
            log.warning("limpeza: não apagou um arquivo de entrada (%s)", type(e).__name__)
    return n


async def limpeza_diaria(deps: Deps, contexto: JobContext, *, timestamp: int | None = None) -> dict[str, Any]:
    agora = deps.relogio.agora()
    saida = await asyncio.to_thread(limpar_banco, deps.db, agora)
    saida["entrada"] = await asyncio.to_thread(limpar_entrada, deps.dados, agora)
    log.info("limpeza: %s", saida)
    return {"texto": "limpeza feita", "dados": saida}


def _voltar_na_fila(db: Db, job_ids: list[int], agora: datetime) -> int:
    with transacao(db) as conn:
        return conn.execute(
            "UPDATE tarefas SET estado = 'na_fila', atualizada = %s"
            " WHERE job_id = ANY(%s) AND estado = 'rodando'",
            (agora, job_ids),
        ).rowcount


async def reanimar(deps: Deps, contexto: JobContext, *, timestamp: int | None = None) -> dict[str, Any]:
    jm = contexto.app.job_manager
    presos = list(await jm.get_stalled_jobs(seconds_since_heartbeat=SEM_BATIMENTO_S))
    ids: list[int] = []
    for job in presos:
        if job.id == contexto.job.id:
            continue
        await jm.retry_job(job)
        ids.append(int(job.id))
    if ids:
        await asyncio.to_thread(_voltar_na_fila, deps.db, ids, deps.relogio.agora())
        log.info("reanimar: %d job(s) de volta à fila", len(ids))
    return {"texto": f"{len(ids)} job(s) reanimado(s)", "dados": {"jobs": ids}}
