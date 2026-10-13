"""``GET /v1/custos?desde=<uid>`` (dono: Y6.1; spec §2.2, §6.4).

O PC puxa as linhas ``source='nuvem'`` depois do último ``uid`` que já tem (a cada ``ola`` e a cada
15 min) e grava no ``costs`` local com ``origem_uid``. Página de até ``n`` linhas (padrão e máximo
:data:`ayanami.custos.PAGINA_MAX`), em ordem de inserção; o PC repete com o ``uid`` da última
linha até vir menos que ``n``. ``desde`` desconhecido recomeça do início.

O ``lifespan`` deste roteador liga o gancho do ``bate`` (``custos_mes_usd`` → ``custos_pc``) ao
hub da app; a rota também liga (idempotente), para apps sem ``lifespan`` (testes ASGI).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from ayanami import custos
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.hub import hub_de


def ligar_ctx(ctx: Any) -> None:
    custos.ligar(hub_de(ctx), ctx.db, ctx.relogio)


@asynccontextmanager
async def _vida(app: FastAPI) -> AsyncIterator[None]:
    ligar_ctx(app.state.ctx)
    yield


router = APIRouter(lifespan=_vida)


@router.get("/v1/custos")
async def listar(
    request: Request,
    _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/custos"))],
    desde: str | None = None,
    n: Annotated[int, Query(ge=1, le=custos.PAGINA_MAX)] = custos.PAGINA_MAX,
) -> JSONResponse:
    ctx = request.app.state.ctx
    ligar_ctx(ctx)
    uid: UUID | None = None
    if desde:
        try:
            uid = UUID(desde)
        except ValueError as e:
            raise ErroApi(422, "invalido", "desde não é um uid") from e
    linhas = await asyncio.to_thread(custos.linhas_desde, ctx.db, uid, n)
    return JSONResponse({"linhas": linhas})
