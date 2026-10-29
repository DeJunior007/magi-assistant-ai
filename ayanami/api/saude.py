"""``GET /saude`` (dono: Y2.1; spec §2.2, R1.6, CA-Y9).

Sem token (só tailnet) e sem dado pessoal: banco, fila (contagem por estado e fila; zeros enquanto a
tabela do ``procrastinate`` não existe), batimento dos workers, último backup, quem está online e
``faltando`` (só **nomes** de segredos ausentes). Banco fora → ``503``.

``online``: ``pc``/``casa`` = dispositivo ativo com ``visto`` (último ``ola``/``bate``) dentro de
``[rede] offline_apos_s``; ``celulares`` = celulares ativos com ``ultimo_uso`` na mesma janela. A
Y2.2 pode trocar a fonte por ``ctx.extras["online"]`` (função ``() -> dict``) com o hub em memória.

``app``/``retrato`` (condessa-celular M1.1, spec §9.2/§9.3): ``{"versao": versionCode|null}`` do
``versao.json`` de ``[app] dir`` e ``{"versao": sha12|null}`` do ponteiro ``<dados>/retrato/atual``
(arquivo com a versão, ou link para a pasta dela); ausente ou ilegível → ``null``.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ayanami.api.app_android import dir_app, version_code_publicado
from ayanami.api.auth import iso_z
from ayanami.deps import DADOS_PADRAO

log = logging.getLogger("ayanami.api.saude")
router = APIRouter()

FILAS = ("rapida", "agendada", "lenta")
_VERSAO_RETRATO_RE = re.compile(r"^[0-9a-f]{12,64}$")


def versao_retrato(dados: Path) -> str | None:
    """Os 12 primeiros hex da versão atual do retrato, ou ``None``."""
    atual = dados / "retrato" / "atual"
    try:
        texto = atual.resolve().name if atual.is_dir() else atual.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return texto[:12] if _VERSAO_RETRATO_RE.match(texto) else None


def _fila(conn: Any) -> dict[str, dict[str, int]]:
    saida = {f: {"todo": 0, "doing": 0, "failed_24h": 0} for f in FILAS}
    if conn.execute("SELECT to_regclass('procrastinate_jobs')").fetchone()[0] is None:
        return saida
    try:
        with conn.transaction():
            for fila, status, n in conn.execute(
                "SELECT queue_name, status::text, count(*) FROM procrastinate_jobs"
                " WHERE status IN ('todo', 'doing') GROUP BY 1, 2"
            ).fetchall():
                saida.setdefault(fila, {"todo": 0, "doing": 0, "failed_24h": 0})[status] = n
            if conn.execute("SELECT to_regclass('procrastinate_events')").fetchone()[0] is not None:
                for fila, n in conn.execute(
                    "SELECT j.queue_name, count(DISTINCT j.id) FROM procrastinate_jobs j"
                    " JOIN procrastinate_events e ON e.job_id = j.id"
                    " WHERE j.status = 'failed' AND e.type::text = 'failed'"
                    " AND e.at > now() - interval '24 hours'"
                    " GROUP BY 1"
                ).fetchall():
                    saida.setdefault(fila, {"todo": 0, "doing": 0, "failed_24h": 0})["failed_24h"] = n
    except psycopg.Error as e:  # esquema do procrastinate diferente: não derruba a saúde
        log.warning("saude: contagem da fila falhou (%s)", type(e).__name__)
    return saida


def coletar(ctx: Any) -> dict:
    agora = ctx.relogio.agora()
    limite = agora - timedelta(seconds=ctx.cfg.rede.offline_apos_s)
    with ctx.db.connection() as conn:
        conn.execute("SELECT 1")
        fila = _fila(conn)
        workers = {f: iso_z(v) for f, v in conn.execute(
            "SELECT fila, visto FROM workers_batimento ORDER BY fila").fetchall()}
        pc, ayn, restic = conn.execute(
            "SELECT max(recebido) FILTER (WHERE origem = 'pc'),"
            " max(recebido) FILTER (WHERE origem = 'ayanami'),"
            " max(enviado) FROM backups"
        ).fetchone()
        pc_on, casa_on, cel = conn.execute(
            "SELECT bool_or(tipo = 'pc' AND visto > %(l)s), bool_or(tipo = 'casa' AND visto > %(l)s),"
            " count(*) FILTER (WHERE tipo = 'celular' AND ultimo_uso > %(l)s)"
            " FROM dispositivos WHERE revogado IS NULL",
            {"l": limite},
        ).fetchone()
        if not conn.autocommit:
            conn.rollback()
    online = {"pc": bool(pc_on), "casa": bool(casa_on), "celulares": int(cel)}
    if callable(ctx.extras.get("online")):
        online = ctx.extras["online"]()
    faltando = list(ctx.segredos.faltando) if ctx.segredos is not None else []
    return {
        "ok": not faltando,
        "banco": "ok",
        "fila": fila,
        "workers": workers,
        "ultimo_backup": {"pc": iso_z(pc), "ayanami": iso_z(ayn), "restic": iso_z(restic)},
        "online": online,
        "faltando": faltando,
        "app": {"versao": version_code_publicado(dir_app(ctx))},
        "retrato": {"versao": versao_retrato(Path(ctx.extras.get("dados") or DADOS_PADRAO))},
    }


@router.get("/saude")
def saude(request: Request) -> JSONResponse:
    ctx = request.app.state.ctx
    try:
        return JSONResponse(coletar(ctx))
    except Exception as e:  # banco fora (ou falso quebrado): 503 sem detalhe do DSN
        log.warning("saude: banco falhou (%s)", type(e).__name__)
        faltando = list(ctx.segredos.faltando) if ctx.segredos is not None else []
        return JSONResponse({"ok": False, "banco": "falha", "faltando": faltando}, status_code=503)
