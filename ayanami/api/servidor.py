"""``GET /v1/servidor`` (dono: Y1.3c): "como está o servidor?".

Lê o ``servidor.json`` do vigia (Y1.3b) por :func:`ayanami.servidor.ler` com o relógio da app e
devolve o dict dele (``estado``, campos validados, ``disco`` e ``resumo`` em pt-BR). Sempre ``200``:
leitura ausente/corrompida/velha vem em ``estado``. Caminho: ``ctx.extras["servidor_json"]`` (testes)
ou :func:`ayanami.servidor.caminho_padrao`.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ayanami import servidor
from ayanami.api.auth import Dispositivo, exigir_rota

router = APIRouter()
EXIGE = exigir_rota("GET", "/v1/servidor")


@router.get("/v1/servidor")
async def ver(request: Request, _: Annotated[Dispositivo, Depends(EXIGE)]) -> JSONResponse:
    ctx = request.app.state.ctx
    caminho = ctx.extras.get("servidor_json")
    dados = await asyncio.to_thread(servidor.ler, caminho, agora=ctx.relogio.agora())
    return JSONResponse(dados)
