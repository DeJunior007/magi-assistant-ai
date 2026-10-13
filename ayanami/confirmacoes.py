"""Confirmações de ações perigosas (dono: Y2.2; R5.3, spec §1.2 ``Confirma``, §2.2, §3).

Pedido ``danger`` vindo do MCP não roda direto: vira uma linha em ``confirmacoes`` (id ULID,
``expira`` = agora + 120 s pelo relógio injetado) e uma pergunta ``confirma`` ao PC (e ao SSE, Y2.3).
Quem responde (``POST /v1/confirma/{pedido}`` ou ``confirma`` com ``resp`` pela WS do PC):

- não existe → :class:`NaoEncontrada` (404); vencida → :class:`Expirada` (410); já respondida →
  :class:`JaRespondida` (409). A resposta é gravada de forma atômica (uma só vence).
- ``resposta=True`` → roda o executor registrado para ``pedido["tipo"]`` (:meth:`Confirmacoes.
  ao_confirmar`; a casa registra ``"casa.acao"``) e devolve o resultado.

``pedido`` (jsonb) leva ``{"tipo": …, "origem": "mcp", …}``; nunca token nem texto de conversa.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from ayanami.db import Db, transacao
from magi.elo.ids import novo_id
from magi.elo.mensagens import Confirma, Envelope, Tipo

log = logging.getLogger("ayanami.confirmacoes")

EXPIRA_S: Final = 120
PRAZO_PERGUNTA_S: Final = 30.0


class ErroConfirmacao(Exception):
    status = 400
    codigo = "invalido"
    msg = "confirmação inválida"


class NaoEncontrada(ErroConfirmacao):
    status, codigo, msg = 404, "nao_encontrada", "confirmação não encontrada"


class Expirada(ErroConfirmacao):
    status, codigo, msg = 410, "expirada", "a confirmação expirou"


class JaRespondida(ErroConfirmacao):
    status, codigo, msg = 409, "ja_respondida", "a confirmação já foi respondida"


@dataclass(frozen=True)
class Confirmacao:
    id: str
    origem: int | None
    descricao: str
    pedido: Mapping[str, Any]
    expira: datetime
    resposta: bool | None = None
    respondida: datetime | None = None

    def para_elo(self) -> Confirma:
        return Confirma(pedido=self.id, descricao=self.descricao,
                        origem=str(self.pedido.get("origem", "mcp")), expira_em=self.expira,
                        resposta=self.resposta)


_COLUNAS = "id, origem, descricao, pedido, expira, resposta, respondida"


def _linha(r: Any) -> Confirmacao:
    pedido = r[3] if isinstance(r[3], Mapping) else json.loads(r[3])
    return Confirmacao(r[0], r[1], r[2], pedido, r[4], r[5], r[6])


def criar(db: Db, relogio: Any, *, descricao: str, pedido: Mapping[str, Any],
          origem: int | None = None, expira_s: float = EXPIRA_S) -> Confirmacao:
    expira = relogio.agora() + timedelta(seconds=expira_s)
    with transacao(db) as conn:
        r = conn.execute(
            f"INSERT INTO confirmacoes (id, origem, descricao, pedido, expira)"
            f" VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING {_COLUNAS}",
            (novo_id(), origem, descricao[:200], json.dumps(dict(pedido), ensure_ascii=False), expira),
        ).fetchone()
    return _linha(r)


def obter(db: Db, id_: str) -> Confirmacao | None:
    with db.connection() as conn:
        r = conn.execute(f"SELECT {_COLUNAS} FROM confirmacoes WHERE id = %s", (id_,)).fetchone()
    return _linha(r) if r else None


def responder(db: Db, relogio: Any, id_: str, resposta: bool) -> Confirmacao:
    """Grava a resposta (uma só vez, antes de ``expira``)."""
    agora = relogio.agora()
    with transacao(db) as conn:
        r = conn.execute(
            f"UPDATE confirmacoes SET resposta = %s, respondida = %s"
            f" WHERE id = %s AND resposta IS NULL AND expira > %s RETURNING {_COLUNAS}",
            (resposta, agora, id_, agora),
        ).fetchone()
        if r is not None:
            return _linha(r)
        atual = conn.execute(f"SELECT {_COLUNAS} FROM confirmacoes WHERE id = %s", (id_,)).fetchone()
    if atual is None:
        raise NaoEncontrada
    if atual[5] is not None:
        raise JaRespondida
    raise Expirada


def pendentes(db: Db, relogio: Any) -> list[Confirmacao]:
    """Não respondidas e ainda dentro do prazo (mais antigas primeiro)."""
    with db.connection() as conn:
        rs = conn.execute(
            f"SELECT {_COLUNAS} FROM confirmacoes WHERE resposta IS NULL AND expira > %s ORDER BY expira",
            (relogio.agora(),),
        ).fetchall()
    return [_linha(r) for r in rs]


def expiradas(db: Db, relogio: Any, desde: datetime | None = None) -> list[Confirmacao]:
    """Sem resposta e vencidas (``expira`` ≤ agora; ``desde`` filtra as que venceram depois)."""
    sql = f"SELECT {_COLUNAS} FROM confirmacoes WHERE resposta IS NULL AND expira <= %s"
    params: list[Any] = [relogio.agora()]
    if desde is not None:
        sql += " AND expira > %s"
        params.append(desde)
    with db.connection() as conn:
        rs = conn.execute(sql + " ORDER BY expira", params).fetchall()
    return [_linha(r) for r in rs]


Executor = Callable[[Confirmacao], Any]


@dataclass
class Confirmacoes:
    """Serviço da app (``ctx.extras["confirmacoes"]``): cria, pergunta ao PC e executa na resposta."""

    db: Db
    relogio: Any
    hub: Any = None
    executores: dict[str, Executor] = field(default_factory=dict)

    def ao_confirmar(self, tipo: str, fn: Executor) -> None:
        self.executores[tipo] = fn

    async def criar(self, *, descricao: str, pedido: Mapping[str, Any], origem: int | None = None,
                    perguntar: bool = True) -> Confirmacao:
        c = await asyncio.to_thread(criar, self.db, self.relogio, descricao=descricao, pedido=pedido,
                                    origem=origem)
        if perguntar and self.hub is not None:
            asyncio.ensure_future(self._perguntar_ao_pc(c))
        return c

    async def _perguntar_ao_pc(self, c: Confirmacao) -> None:
        env = Envelope(t=Tipo.CONFIRMA, corpo=c.para_elo(), de="ayanami", para="pc")
        try:
            r = await self.hub.enviar_e_esperar(env, PRAZO_PERGUNTA_S)
        except Exception as e:  # noqa: BLE001 - PC offline: a confirmação segue pelo PWA
            log.info("confirma_pc_sem_resposta (%s)", type(e).__name__)
            return
        if isinstance(r.corpo, Confirma) and r.corpo.resposta is not None:
            try:
                await self.responder(c.id, r.corpo.resposta)
            except ErroConfirmacao as e:
                log.info("confirma_pc_recusada (%s)", e.codigo)

    async def responder(self, id_: str, resposta: bool) -> tuple[Confirmacao, Any]:
        c = await asyncio.to_thread(responder, self.db, self.relogio, id_, resposta)
        resultado: Any = None
        if resposta:
            fn = self.executores.get(str(c.pedido.get("tipo", "")))
            if fn is not None:
                resultado = fn(c)
                if inspect.isawaitable(resultado):
                    resultado = await resultado
        return c, resultado

    async def resposta_do_pc(self, _disp: Any, env: Envelope) -> Envelope | None:
        """Gancho ``hub.ao_receber(CONFIRMA)``: o PC respondeu fora da espera da pergunta."""
        corpo = env.corpo
        if isinstance(corpo, Confirma) and corpo.resposta is not None:
            try:
                await self.responder(corpo.pedido, corpo.resposta)
            except ErroConfirmacao as e:
                log.info("confirma_pc_recusada (%s)", e.codigo)
        return None


def confirmacoes_de(ctx: Any) -> Confirmacoes:
    """O serviço da app (``ctx.extras["confirmacoes"]``), ligado ao hub na 1ª vez."""
    from ayanami.hub import hub_de

    svc = ctx.extras.get("confirmacoes")
    if svc is None:
        hub = hub_de(ctx)
        svc = Confirmacoes(ctx.db, ctx.relogio, hub)
        hub.ao_receber(Tipo.CONFIRMA, svc.resposta_do_pc)
        ctx.extras["confirmacoes"] = svc
    return svc
