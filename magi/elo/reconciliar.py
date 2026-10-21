"""Reconciliação ``resumo_nuvem`` no PC (dono: Y6.5; R8.5, D6a, design §7.5, spec §6.6).

O ``NoPc`` (Y6.2) despacha ``resumo_nuvem`` → :meth:`Reconciliador.gravar_resumo` e responde
``Ack(ids=…)`` com o que ela devolver. :func:`gravar_resumo` grava cada ``TurnoNuvem`` em
``turns`` (satélite ``celular``, ``intent = "nuvem:<uid>"`` — a marca ``nuvem`` e a chave da
idempotência, sem migração), ignora ``uid`` já gravado (devolve-o no ``ack`` mesmo assim: está no
PC) e passa os turnos novos pelo extrator de memória dos turnos normais.

Extrator: os turnos normais não têm extração síncrona; quem aprende com ``turns`` é o
``magi.memory.profile.ProfileUpdater`` (perfil + vocabulário do STT, lê ``TurnsRepo.recent``, 1×/dia
pela própria regra ``due``). :class:`PerfilIngest` chama ``ProfileUpdater.maybe_update()`` depois
do lote. O Learning Mode (``TurnDeps.learning``) **não** entra: é a conversa ao vivo da sessão,
não extração. Falha do extrator não tira id do ``ack`` (o turno já está gravado).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence
from typing import Any, Final, Protocol

from magi.common.contracts import TurnRecord
from magi.elo.mensagens import ResumoNuvem, TurnoNuvem

log = logging.getLogger(__name__)

SATELITE: Final = "celular"
MARCA: Final = "nuvem:"


def marca(uid: str) -> str:
    """``turns.intent`` de um turno do modo nuvem."""
    return f"{MARCA}{uid}"


class TurnRepo(Protocol):
    """O que a reconciliação usa de ``turns``."""

    async def add(self, turn: TurnRecord) -> int: ...
    async def ja_gravados(self, uids: Sequence[str]) -> set[str]: ...


class MemoryIngest(Protocol):
    async def ingerir(self, turnos: Sequence[TurnRecord]) -> None: ...


class TurnosNuvemPg:
    """``TurnRepo`` sobre a conexão async compartilhada do PC (``Repos.conn``, ``SerialConn``)."""

    def __init__(self, conn: Any, turns: Any = None) -> None:
        self._conn = conn
        self._turns = turns  # PgTurnsRepo; None → insert próprio na mesma conexão

    async def add(self, turn: TurnRecord) -> int:
        if self._turns is not None:
            return int(await self._turns.add(turn))
        from magi.memory.memories_repo import PgTurnsRepo

        return int(await PgTurnsRepo(self._conn).add(turn))

    async def ja_gravados(self, uids: Sequence[str]) -> set[str]:
        if not uids:
            return set()
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "SELECT intent FROM turns WHERE satellite = %s AND intent = ANY(%s)",
                [SATELITE, [marca(u) for u in uids]])
            linhas = await cur.fetchall()
        return {r[0][len(MARCA):] for r in linhas}


class PerfilIngest:
    """``MemoryIngest`` pelo ``ProfileUpdater`` (o extrator que já lê ``turns``)."""

    def __init__(self, profile: Any) -> None:
        self.profile = profile

    async def ingerir(self, turnos: Sequence[TurnRecord]) -> None:
        if turnos:
            await self.profile.maybe_update()


def registro(t: TurnoNuvem) -> TurnRecord:
    return TurnRecord(satellite=SATELITE, text_heard=t.texto_usuario, text_final=t.texto_usuario,
                      at=t.ts, intent=marca(t.uid), routed_local=False, reply=t.texto_resposta)


async def gravar_resumo(r: ResumoNuvem, turns: TurnRepo, memoria: MemoryIngest | None) -> tuple[str, ...]:
    """Grava os turnos novos do envelope e devolve os ``uid`` que estão no PC (novos + já gravados),
    na ordem do envelope. Erro ao gravar um turno: ele fica fora do ``ack`` (a Ayanami reenvia)."""
    uids = list(dict.fromkeys(t.uid for t in r.turnos))
    ja = await turns.ja_gravados(uids)
    vistos: set[str] = set()
    ok: list[str] = []
    novos: list[TurnRecord] = []
    for t in r.turnos:
        if t.uid in vistos:
            continue
        vistos.add(t.uid)
        if t.uid in ja:
            ok.append(t.uid)
            continue
        rec = registro(t)
        try:
            tid = await turns.add(rec)
        except Exception:  # noqa: BLE001 - um turno ruim não derruba o envelope
            log.exception("reconciliar: falha ao gravar turno da nuvem")
            continue
        ok.append(t.uid)
        novos.append(dataclasses.replace(rec, id=tid))
    if memoria is not None and novos:
        try:
            await memoria.ingerir(novos)
        except Exception:  # noqa: BLE001 - extrator falhou: turnos já gravados, ack segue
            log.exception("reconciliar: extrator de memória falhou")
    return tuple(ok)


class Reconciliador:
    def __init__(self, core: Any = None, *, turns: TurnRepo | None = None,
                 memoria: MemoryIngest | None = None) -> None:
        """``core``: ``magi.core.assemble.Core`` (``repos.conn``/``repos.turns``, ``profile``), ou
        ``None``. ``turns``/``memoria`` explícitos têm prioridade (testes)."""
        self.core = core
        self._turns = turns
        self._memoria = memoria

    def _repo(self) -> TurnRepo | None:
        if self._turns is not None:
            return self._turns
        repos = getattr(self.core, "repos", None)
        conn = getattr(repos, "conn", None)
        if conn is None:
            return None
        return TurnosNuvemPg(conn, getattr(repos, "turns", None))

    def _extrator(self) -> MemoryIngest | None:
        if self._memoria is not None:
            return self._memoria
        profile = getattr(self.core, "profile", None)
        return PerfilIngest(profile) if profile is not None else None

    async def gravar_resumo(self, resumo: ResumoNuvem) -> tuple[str, ...]:
        turns = self._repo()
        if turns is None:
            log.info("ayanami: resumo_nuvem sem banco local; nada gravado (reenvia no próximo ola)")
            return ()
        return await gravar_resumo(resumo, turns, self._extrator())
