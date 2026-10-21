"""Assinatura de Web Push (dono: P2.1; spec §2.2, §15).

- ``POST /v1/push/assinar`` (``conversa``, só celular): corpo = ``PushSubscription.toJSON()``; grava
  em ``push_assinaturas`` (uma por celular: a nova substitui as outras do mesmo dispositivo; o mesmo
  ``endpoint`` muda de dono e zera ``falhas``) → ``201``.
- ``DELETE /v1/push/assinar`` ``{"endpoint"}``: apaga a do próprio dispositivo → ``204`` (idempotente).

Preferências (``push``, ``push_com_pc``, ``silencio``) vão em ``PUT /v1/dispositivo/preferencias``.
Auditoria sem endpoint nem chaves.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ayanami.api import auditoria
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.db import transacao

router = APIRouter()

_B64URL = r"^[A-Za-z0-9_\-]+=*$"


class Chaves(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p256dh: str = Field(min_length=16, max_length=200, pattern=_B64URL)
    auth: str = Field(min_length=8, max_length=100, pattern=_B64URL)


class Assinar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(min_length=12, max_length=2048, pattern=r"^https://\S+$")
    expirationTime: float | None = None  # noqa: N815 - nome do PushSubscription.toJSON()
    keys: Chaves


class Desassinar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(min_length=1, max_length=2048)


def _so_celular(disp: Dispositivo) -> None:
    if disp.tipo != "celular":
        raise ErroApi(403, "tipo_proibido", "só o celular assina Web Push")


@router.post("/v1/push/assinar", status_code=201)
def assinar(
    request: Request,
    corpo: Assinar,
    disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/push/assinar"))],
) -> Response:
    _so_celular(disp)
    ctx = request.app.state.ctx
    with transacao(ctx.db) as conn:
        conn.execute("DELETE FROM push_assinaturas WHERE dispositivo = %s AND endpoint <> %s",
                     (disp.id, corpo.endpoint))
        conn.execute(
            "INSERT INTO push_assinaturas (dispositivo, endpoint, p256dh, auth) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (endpoint) DO UPDATE SET dispositivo = EXCLUDED.dispositivo,"
            " p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, falhas = 0",
            (disp.id, corpo.endpoint, corpo.keys.p256dh, corpo.keys.auth))
        auditoria.registrar(conn, tipo="push", dispositivo=disp.id, alvo=disp.nome,
                            resumo="assinatura gravada", ok=True)
    return Response(status_code=201)


@router.delete("/v1/push/assinar", status_code=204)
def desassinar(
    request: Request,
    corpo: Desassinar,
    disp: Annotated[Dispositivo, Depends(exigir_rota("DELETE", "/v1/push/assinar"))],
) -> Response:
    _so_celular(disp)
    ctx = request.app.state.ctx
    with transacao(ctx.db) as conn:
        n = conn.execute("DELETE FROM push_assinaturas WHERE dispositivo = %s AND endpoint = %s",
                         (disp.id, corpo.endpoint)).rowcount
        if n:
            auditoria.registrar(conn, tipo="push", dispositivo=disp.id, alvo=disp.nome,
                                resumo="assinatura apagada", ok=True)
    return Response(status_code=204)
