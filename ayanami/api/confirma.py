"""Resposta a uma confirmação (dono: Y2.2; spec §2.2, R5.3).

``POST /v1/confirma/{pedido}`` ``{"resposta": true}`` → ``200`` ``{"pedido","resposta",
"resultado"}`` (``resultado`` = ``AcaoResultado`` da ação confirmada, ou ``null``); ``404`` não
existe; ``410`` expirada; ``409`` já respondida.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from ayanami.api import auditoria
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.api.casa import para_json, servicos
from ayanami.confirmacoes import ErroConfirmacao

router = APIRouter()


@router.post("/v1/confirma/{pedido}")
async def confirmar(
    pedido: str,
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/confirma/{pedido}"))],
    resposta: Annotated[bool, Body(embed=True, strict=True)],
) -> dict:
    ctx = request.app.state.ctx
    _, conf = servicos(ctx)
    try:
        c, resultado = await conf.responder(pedido, resposta)
    except ErroConfirmacao as e:
        raise ErroApi(e.status, e.codigo, e.msg) from e
    await asyncio.to_thread(auditoria.registrar, ctx.db, tipo="mcp", alvo=c.id,
                            resumo=f"confirmacao respondida {resposta}", ok=True, dispositivo=disp.id)
    return {"pedido": c.id, "resposta": c.resposta, "resultado": para_json(resultado)}
