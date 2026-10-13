"""Rotas ``/v1/tarefas*`` e ``/v1/fila`` (dono: Y3.1 → Y3.6 só o ramo ``stt`` do ``POST``; spec §2.2,
§4.3).

O ``App`` da fila vem de ``ctx.extras["fila"]`` (testes: ``InMemoryConnector``); sem ele, o de
produção (:func:`ayanami.fila.app_aberto`, conector aberto no 1º uso).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ayanami import tarefas as tf
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota, iso_z

router = APIRouter()


class TarefaInCorpo(BaseModel):
    tipo: Literal["pesquisa", "resumo", "lembrete", "monitor", "stt"]
    titulo: str = Field(min_length=1, max_length=120)
    params: dict[str, Any] = Field(default_factory=dict)
    chave: str | None = Field(default=None, min_length=1, max_length=128)
    pessoal: bool = False
    avisar: bool = True


def _app_fila(request: Request) -> Any:
    return request.app.state.ctx.extras.get("fila")


def _uuid(texto: str) -> UUID:
    try:
        return UUID(texto)
    except ValueError as e:
        raise ErroApi(404, "nao_encontrado", "tarefa não existe") from e


@router.get("/v1/tarefas")
def listar(
    request: Request,
    _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/tarefas"))],
    estado: str | None = None,
    n: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    if estado is not None and estado not in tf.ESTADO_DO_JOB.values():
        raise ErroApi(422, "invalido", "estado desconhecido")
    lista = tf.listar_tarefas(request.app.state.ctx.db, estado, n)
    return JSONResponse({"tarefas": [t.para_json() for t in lista]})


@router.post("/v1/tarefas")
async def criar(request: Request, corpo: TarefaInCorpo,
                disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/tarefas"))]) -> JSONResponse:
    ctx = request.app.state.ctx
    t = tf.TarefaIn(tipo=corpo.tipo, titulo=corpo.titulo, params=corpo.params, chave=corpo.chave,
                    pessoal=corpo.pessoal, avisar=corpo.avisar)
    try:
        tarefa, criada = await tf.criar_tarefa(ctx.db, t, disp.id, app=_app_fila(request),
                                               relogio=ctx.relogio)
    except tf.TarefaInvalida as e:
        raise ErroApi(422, "invalido", str(e)) from e
    return JSONResponse(tarefa.para_json(), status_code=201 if criada else 200)


@router.get("/v1/tarefas/{id}")
def ver(request: Request, id: str,
        _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/tarefas/{id}"))]) -> JSONResponse:
    t = tf.obter_tarefa(request.app.state.ctx.db, _uuid(id))
    if t is None:
        raise ErroApi(404, "nao_encontrado", "tarefa não existe")
    return JSONResponse(t.para_json())


@router.delete("/v1/tarefas/{id}")
async def cancelar(
    request: Request, id: str,
    _: Annotated[Dispositivo, Depends(exigir_rota("DELETE", "/v1/tarefas/{id}"))],
) -> JSONResponse:
    ctx = request.app.state.ctx
    try:
        estado = await tf.cancelar_tarefa(ctx.db, _uuid(id), app=_app_fila(request),
                                          relogio=ctx.relogio)
    except tf.TarefaNaoEncontrada as e:
        raise ErroApi(404, "nao_encontrado", "tarefa não existe") from e
    except tf.JaTerminou as e:
        raise ErroApi(409, "ja_terminou", f"a tarefa já terminou ({e.estado})") from e
    return JSONResponse({"estado": estado}, status_code=202)


def _resumo_fila(db: Any) -> dict[str, Any]:
    saida: dict[str, Any] = {"contagem": {}, "lentas": [], "falhas": []}
    with db.connection() as conn:
        if conn.execute("SELECT to_regclass('procrastinate_jobs')").fetchone()[0] is None:
            return saida
        for fila, status, n in conn.execute(
            "SELECT queue_name, status::text, count(*) FROM procrastinate_jobs GROUP BY 1, 2"
        ).fetchall():
            saida["contagem"].setdefault(fila, {})[status] = n
        for jid, nome, fila, desde in conn.execute(
            "SELECT j.id, j.task_name, j.queue_name, max(e.at) FROM procrastinate_jobs j"
            " JOIN procrastinate_events e ON e.job_id = j.id AND e.type::text = 'started'"
            " WHERE j.status = 'doing' GROUP BY 1, 2, 3 ORDER BY 4 ASC LIMIT 10"
        ).fetchall():
            saida["lentas"].append({"job": jid, "tarefa": nome, "fila": fila, "desde": iso_z(desde)})
        for jid, nome, fila, quando, tentativas in conn.execute(
            "SELECT j.id, j.task_name, j.queue_name, max(e.at), j.attempts FROM procrastinate_jobs j"
            " JOIN procrastinate_events e ON e.job_id = j.id AND e.type::text = 'failed'"
            " WHERE j.status = 'failed' GROUP BY 1, 2, 3, 5 ORDER BY 4 DESC LIMIT 10"
        ).fetchall():
            saida["falhas"].append({"job": jid, "tarefa": nome, "fila": fila,
                                    "quando": iso_z(quando), "tentativas": tentativas})
        if not conn.autocommit:
            conn.rollback()
    return saida


@router.get("/v1/fila")
async def ver_fila(request: Request,
                   _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/fila"))]) -> JSONResponse:
    return JSONResponse(await asyncio.to_thread(_resumo_fila, request.app.state.ctx.db))
