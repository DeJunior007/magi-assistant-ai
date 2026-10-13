"""Pareamento e o próprio dispositivo (dono: Y2.1; spec §2.2, design §4.1, R7.1).

- ``POST /v1/pareamento`` (tipo ``pc``): código de 6 dígitos, 5 min, uso único; um código novo
  invalida o anterior. No banco vai só o ``sha256`` do código.
- ``POST /v1/pareamento/trocar`` (sem token): código + nome → token ``celular``. ``400`` código
  errado/expirado; ``409`` nome em uso (o código continua valendo); ``429`` com > 5 tentativas/min
  do mesmo IP ou no 10º erro do código vigente (o código morre).
- ``DELETE /v1/dispositivo``: revoga o próprio token. ``PUT /v1/dispositivo/preferencias``
  (``conversa``): grava ``dispositivos.preferencias`` (§16.1).
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator

from ayanami.api import auditoria
from ayanami.api.auth import (
    Dispositivo,
    ErroApi,
    NomeEmUso,
    criar_dispositivo,
    exigir_rota,
    iso_z,
    nome_valido,
)
from ayanami.db import transacao

router = APIRouter()

VALIDADE = timedelta(minutes=5)
MAX_ERROS = 10
_SILENCIO_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def _hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()


class PedidoPareamento(BaseModel):
    nome_sugerido: str | None = None


class Troca(BaseModel):
    codigo: str
    nome: str


class Preferencias(BaseModel):
    model_config = ConfigDict(extra="forbid")

    push: bool = True
    push_com_pc: bool = False
    silencio: str = ""
    tv_padrao: str | None = None
    voz_em_texto: bool = False

    @field_validator("silencio")
    @classmethod
    def _silencio(cls, v: str) -> str:
        if v and not _SILENCIO_RE.match(v):
            raise ValueError("silencio = 'HH:MM-HH:MM' ou ''")
        return v


@router.post("/v1/pareamento", status_code=201)
def parear(
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/pareamento"))],
    corpo: PedidoPareamento | None = None,
) -> dict:
    ctx = request.app.state.ctx
    agora = ctx.relogio.agora()
    codigo = ctx.gerar_codigo()
    expira = agora + VALIDADE
    nome = (corpo.nome_sugerido if corpo else None) or None
    with transacao(ctx.db) as conn:
        conn.execute("UPDATE pareamentos SET expira = %s WHERE usado IS NULL AND expira > %s", (agora, agora))
        conn.execute(
            "INSERT INTO pareamentos (codigo_hash, criado_por, nome_sugerido, expira) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (codigo_hash) DO UPDATE SET criado_por = EXCLUDED.criado_por,"
            " nome_sugerido = EXCLUDED.nome_sugerido, expira = EXCLUDED.expira, usado = NULL, erros = 0",
            (_hash_codigo(codigo), disp.id, nome, expira),
        )
        auditoria.registrar(conn, tipo="dispositivo", dispositivo=disp.id, alvo="pareamento",
                            resumo="código de pareamento emitido", ok=True)
    return {"codigo": codigo, "expira_em": iso_z(expira)}


@router.post("/v1/pareamento/trocar", status_code=201)
def trocar(request: Request, corpo: Troca) -> dict:
    ctx = request.app.state.ctx
    ctx.limites.por_ip(request)
    agora = ctx.relogio.agora()
    if not nome_valido(corpo.nome):
        raise ErroApi(422, "nome_invalido", "nome: a-z, 0-9 e '-', até 32 caracteres")
    with transacao(ctx.db) as conn:
        vigente = conn.execute(
            "SELECT codigo_hash, erros, criado_por FROM pareamentos"
            " WHERE usado IS NULL AND expira > %s AND erros < %s ORDER BY expira DESC LIMIT 1 FOR UPDATE",
            (agora, MAX_ERROS),
        ).fetchone()
        if vigente is None:
            erro = ErroApi(400, "codigo_invalido", "código errado ou expirado")
        elif vigente[0] != _hash_codigo(corpo.codigo.strip()):
            erros = vigente[1] + 1
            conn.execute("UPDATE pareamentos SET erros = %s WHERE codigo_hash = %s", (erros, vigente[0]))
            if erros >= MAX_ERROS:
                conn.execute("UPDATE pareamentos SET expira = %s WHERE codigo_hash = %s", (agora, vigente[0]))
                erro = ErroApi(429, "codigo_morto", "erros demais; peça um código novo",
                               {"Retry-After": "60"})
            else:
                erro = ErroApi(400, "codigo_invalido", "código errado ou expirado")
            auditoria.registrar(conn, tipo="dispositivo", alvo="pareamento",
                                resumo=f"troca recusada (erro {erros})", ok=False)
        else:
            try:
                token, novo = criar_dispositivo(conn, corpo.nome, "celular")
            except NomeEmUso:
                erro = ErroApi(409, "nome_em_uso", "já existe um dispositivo com esse nome")
            else:
                conn.execute("UPDATE pareamentos SET usado = %s WHERE codigo_hash = %s", (agora, vigente[0]))
                auditoria.registrar(conn, tipo="dispositivo", dispositivo=novo.id, alvo=novo.nome,
                                    resumo=f"celular pareado (código do dispositivo {vigente[2]})", ok=True)
                return {"token": token, "nome": novo.nome, "escopos": sorted(novo.escopos)}
    raise erro


@router.delete("/v1/dispositivo", status_code=204)
def sair(
    request: Request, disp: Annotated[Dispositivo, Depends(exigir_rota("DELETE", "/v1/dispositivo"))]
) -> Response:
    ctx = request.app.state.ctx
    ctx.auth.revogar(disp.id)
    auditoria.registrar(ctx.db, tipo="dispositivo", dispositivo=disp.id, alvo=disp.nome,
                        resumo="revogou o próprio token", ok=True)
    return Response(status_code=204)


@router.put("/v1/dispositivo/preferencias", status_code=204)
def preferencias(
    request: Request,
    corpo: Preferencias,
    disp: Annotated[Dispositivo, Depends(exigir_rota("PUT", "/v1/dispositivo/preferencias"))],
) -> Response:
    ctx = request.app.state.ctx
    with transacao(ctx.db) as conn:
        conn.execute("UPDATE dispositivos SET preferencias = %s WHERE id = %s",
                     (Jsonb(corpo.model_dump()), disp.id))
        auditoria.registrar(conn, tipo="dispositivo", dispositivo=disp.id, alvo=disp.nome,
                            resumo="preferências gravadas", ok=True)
    return Response(status_code=204)

