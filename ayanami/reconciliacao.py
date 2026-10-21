"""Reconciliação ``resumo_nuvem`` na Ayanami (dono: Y6.5; R8.5, D6a, design §7.5, spec §6.6).

No ``ola`` do ``pc`` (gancho ``hub.ao_ola("pc", …)``) a Ayanami manda os ``nuvem_turnos`` com
``sincronizado IS NULL`` em envelopes ``resumo_nuvem`` de ≤ 50 turnos, na ordem ``(ts, uid)``.
O PC responde ``Ack(ids=…)``; só os ids do ``ack`` (e que estavam no envelope) ganham
``sincronizado = agora``. Um envelope sem ``ack`` (PC caiu, tempo, ``erro``) encerra a rodada: o
resto vai no próximo ``ola``. Ids não confirmados num ``ack`` parcial também ficam para o próximo
``ola`` (a rodada anda por cursor ``(ts, uid)``, nunca reenvia o mesmo turno na mesma rodada).

Envelope acima de 64 KiB (textos longos): o lote encolhe até caber; um turno sozinho grande demais
tem os textos cortados aos limites do elo só no envio (o banco fica intacto).

``reconciliacao_de(ctx)`` cria o serviço da app e liga o gancho (uma vez por app).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, Protocol

from magi.elo.mensagens import (
    MAX_RESUMO_TURNOS,
    MAX_TEXTO_BYTES,
    MAX_TURNO_FIM_TEXTO,
    MAX_TURNO_TEXTO,
    Ack,
    EloError,
    Envelope,
    ResumoNuvem,
    Tipo,
    TurnoNuvem,
    encode,
)

log = logging.getLogger("ayanami.reconciliacao")

LOTE: Final = MAX_RESUMO_TURNOS  # 50
PRAZO_PC_S: Final = 60.0  # o hub reenvia o mesmo envelope a cada 10 s até 3× dentro do prazo
DISPOSITIVO_PADRAO: Final = "celular"

Cursor = tuple[datetime, str]


class Armazem(Protocol):
    def pendentes(self, depois: Cursor | None, n: int) -> list[TurnoNuvem]: ...
    def contar(self, depois: Cursor | None) -> int: ...
    def marcar(self, uids: Sequence[str], quando: datetime) -> int: ...


class Enviador(Protocol):
    async def enviar_e_esperar(self, env: Envelope, prazo: float) -> Envelope: ...


_SEL = (
    "SELECT t.uid::text, t.ts, coalesce(d.nome, %s), t.texto_usuario, t.texto_resposta,"
    " t.ferramentas FROM nuvem_turnos t LEFT JOIN dispositivos d ON d.id = t.dispositivo"
    " WHERE t.sincronizado IS NULL"
)


class ArmazemPg:
    """``nuvem_turnos`` no ``ayanami-pg`` (``db.connection()`` síncrono; chamado em thread)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def pendentes(self, depois: Cursor | None, n: int) -> list[TurnoNuvem]:
        sql, args = _SEL, [DISPOSITIVO_PADRAO]
        if depois is not None:
            sql += " AND (t.ts, t.uid) > (%s, %s::uuid)"
            args += [depois[0], depois[1]]
        sql += " ORDER BY t.ts, t.uid LIMIT %s"
        with self.db.connection() as conn:
            linhas = conn.execute(sql, [*args, n]).fetchall()
        return [
            TurnoNuvem(uid=r[0], ts=r[1], dispositivo=r[2], texto_usuario=r[3], texto_resposta=r[4],
                       ferramentas=tuple(r[5] or ()))
            for r in linhas
        ]

    def contar(self, depois: Cursor | None) -> int:
        sql, args = "SELECT count(*) FROM nuvem_turnos t WHERE t.sincronizado IS NULL", []
        if depois is not None:
            sql += " AND (t.ts, t.uid) > (%s, %s::uuid)"
            args = [depois[0], depois[1]]
        with self.db.connection() as conn:
            return int(conn.execute(sql, args).fetchone()[0])

    def marcar(self, uids: Sequence[str], quando: datetime) -> int:
        if not uids:
            return 0
        with self.db.connection() as conn, conn.transaction():
            cur = conn.execute(
                "UPDATE nuvem_turnos SET sincronizado = %s"
                " WHERE uid = ANY(%s::uuid[]) AND sincronizado IS NULL", [quando, list(uids)])
            return cur.rowcount


def _cabe(turnos: Sequence[TurnoNuvem], restam: int) -> Envelope | None:
    env = Envelope(t=Tipo.RESUMO_NUVEM, corpo=ResumoNuvem(turnos=tuple(turnos), restam=restam),
                   de="ayanami", para="pc")
    try:
        encode(env)
    except EloError:
        return None
    return env


def _corta(t: TurnoNuvem) -> TurnoNuvem:
    """Um turno sozinho acima do frame: textos aos limites do elo (o JSON escapado ainda cabe)."""
    return replace(t, texto_usuario=t.texto_usuario[:MAX_TURNO_TEXTO // 4],
                   texto_resposta=t.texto_resposta[:MAX_TURNO_FIM_TEXTO // 4],
                   ferramentas=t.ferramentas[:32])


def montar_envelope(turnos: Sequence[TurnoNuvem], restam_depois: int) -> tuple[Envelope, int]:
    """Maior prefixo de ``turnos`` (≥ 1) que cabe em ``MAX_TEXTO_BYTES``. Devolve o envelope e
    quantos turnos entraram; ``restam`` conta os que ficaram de fora + ``restam_depois``."""
    n = len(turnos)
    while n > 1:
        env = _cabe(turnos[:n], restam_depois + len(turnos) - n)
        if env is not None:
            return env, n
        n = max(1, n // 2) if n > 8 else n - 1
    restam = restam_depois + len(turnos) - 1
    env = _cabe(turnos[:1], restam) or _cabe((_corta(turnos[0]),), restam)
    if env is None:  # pragma: no cover - limites do elo garantem que cabe
        raise EloError("tamanho", f"turno {turnos[0].uid} não cabe num envelope ({MAX_TEXTO_BYTES})")
    return env, 1


@dataclass
class Rodada:
    enviados: int = 0
    confirmados: int = 0
    envelopes: int = 0
    interrompida: bool = False


class Reconciliacao:
    """Serviço da app: uma rodada por ``ola`` do PC (a nova espera a anterior terminar)."""

    def __init__(self, armazem: Armazem, relogio: Any, hub: Enviador, *,
                 prazo_pc_s: float = PRAZO_PC_S, lote: int = LOTE) -> None:
        self.armazem = armazem
        self.relogio = relogio
        self.hub = hub
        self.prazo_pc_s = prazo_pc_s
        self.lote = max(1, min(lote, MAX_RESUMO_TURNOS))
        self._trava = asyncio.Lock()
        self._tarefas: set[asyncio.Task[Any]] = set()

    async def rodada(self) -> Rodada:
        """Manda os pendentes em envelopes de ≤ ``lote``; para no 1º envelope sem ``ack``."""
        r = Rodada()
        async with self._trava:
            cursor: Cursor | None = None
            while True:
                lote = await asyncio.to_thread(self.armazem.pendentes, cursor, self.lote)
                if not lote:
                    return r
                ultimo = lote[-1]
                restam = await asyncio.to_thread(self.armazem.contar, (ultimo.ts, ultimo.uid))
                env, n = montar_envelope(lote, restam)
                enviados = lote[:n]
                cursor = (enviados[-1].ts, enviados[-1].uid)
                try:
                    resp = await self.hub.enviar_e_esperar(env, self.prazo_pc_s)
                except Exception as e:  # noqa: BLE001 - offline/tempo: o resto vai no próximo ola
                    log.info("resumo_nuvem_sem_ack (%s)", type(e).__name__)
                    r.interrompida = True
                    return r
                r.envelopes += 1
                r.enviados += n
                if not isinstance(resp.corpo, Ack):
                    log.info("resumo_nuvem_recusado (%s)", resp.t.value)
                    r.interrompida = True
                    return r
                no_envelope = {t.uid for t in enviados}
                ok = [u for u in dict.fromkeys(resp.corpo.ids) if u in no_envelope]
                if ok:
                    await asyncio.to_thread(self.armazem.marcar, ok, self.relogio.agora())
                r.confirmados += len(ok)
                if len(ok) < n:
                    log.info("resumo_nuvem_ack_parcial (%d de %d)", len(ok), n)

    async def ao_ola_pc(self, _disp: Any, _ola: Any) -> None:
        """Gancho ``hub.ao_ola("pc")``: roda em segundo plano (o ``ola`` não espera o PC gravar)."""
        tarefa = asyncio.create_task(self._rodada_segura())
        self._tarefas.add(tarefa)
        tarefa.add_done_callback(self._tarefas.discard)

    async def _rodada_segura(self) -> None:
        try:
            r = await self.rodada()
        except Exception:  # noqa: BLE001 - banco fora: tenta no próximo ola
            log.exception("resumo_nuvem_falhou")
            return
        if r.envelopes:
            log.info("resumo_nuvem: %d envelopes, %d/%d confirmados", r.envelopes, r.confirmados,
                     r.enviados)

    async def fechar(self) -> None:
        for t in list(self._tarefas):
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*self._tarefas, return_exceptions=True)


def reconciliacao_de(ctx: Any) -> Reconciliacao:
    """O serviço da app (``ctx.extras["reconciliacao"]``), ligado ao ``ola`` do ``pc`` na 1ª vez."""
    svc = ctx.extras.get("reconciliacao")
    if svc is not None:
        return svc
    from ayanami.hub import hub_de

    hub = hub_de(ctx)
    svc = Reconciliacao(ArmazemPg(ctx.db), ctx.relogio, hub)
    hub.ao_ola("pc", svc.ao_ola_pc)
    ctx.extras["reconciliacao"] = svc
    return svc
