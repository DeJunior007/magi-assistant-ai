"""Custos da nuvem no PC (ayanami-central Y6.6, spec §6.4, R8.4).

``CustosPc.rodar()`` puxa ``GET /v1/custos?desde=<último uid>`` a cada conexão nova do elo
(``ola``) e a cada 15 min, e insere em ``costs`` com ``origem_uid`` (``ON CONFLICT DO NOTHING``:
duas puxadas seguidas não duplicam). ``total_mes()`` dá ao ``Bate.custos_mes_usd`` o gasto **local**
do mês (``origem_uid IS NULL``, mês civil de São Paulo): a Ayanami soma a nuvem por conta própria,
então mandar as linhas copiadas contaria a nuvem duas vezes. ``None`` até a 1ª leitura (o ``NoPc``
usa o ``Budget`` local).

O ``EloCliente`` não tem gancho de ``ola``: ``rodar`` observa ``cliente.modo`` (``None`` → ``ws``/
``longpoll`` = conexão nova) a cada ``checagem_s``; ``ao_ola()`` força a próxima puxada. Na mesma
volta checa o card "backup não subiu" (``AvisoBackup``, pedido da Y4.1).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import httpx

from magi.core.proactive.ayanami import AvisoBackup, AvisosAyanami
from magi.memory.costs_repo import TZ, month_bounds

log = logging.getLogger(__name__)

INTERVALO_S = 900.0  # 15 min
CHECAGEM_S = 5.0
PAGINA = 500
MAX_PAGINAS = 200


class CustosNuvemRepo(Protocol):
    async def ultimo_uid(self) -> str | None: ...
    async def inserir(self, linhas: Sequence[Mapping[str, Any]]) -> int: ...
    async def total_local_mes(self, ano: int, mes: int) -> float: ...


class PgCustosNuvem:
    """``costs`` do ``magi-pg`` (coluna ``origem_uid`` da migração 005)."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @classmethod
    def de_core(cls, core: Any) -> PgCustosNuvem | None:
        """A conexão do ``CostsRepo`` aberto pelo ``assemble`` (``Repos`` não expõe outra)."""
        conn = getattr(getattr(getattr(core, "repos", None), "costs", None), "_conn", None)
        return cls(conn) if conn is not None else None

    async def ultimo_uid(self) -> str | None:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "SELECT origem_uid FROM costs WHERE origem_uid IS NOT NULL ORDER BY id DESC LIMIT 1"
            )
            row = await cur.fetchone()
        return str(row[0]) if row else None

    async def inserir(self, linhas: Sequence[Mapping[str, Any]]) -> int:
        n = 0
        async with self._conn.transaction():
            for ln in linhas:
                cur = await self._conn.execute(
                    "INSERT INTO costs (at, provider, task, model, input_units, output_units, usd,"
                    " origem_uid) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (origem_uid) DO NOTHING",
                    [ln["at"], ln["provider"], ln["task"], ln["model"], ln["input_units"],
                     ln["output_units"], ln["usd"], ln["uid"]],
                )
                n += cur.rowcount or 0
        return n

    async def total_local_mes(self, ano: int, mes: int) -> float:
        inicio, fim = month_bounds(ano, mes)
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "SELECT coalesce(sum(usd), 0) FROM costs"
                " WHERE origem_uid IS NULL AND at >= %s AND at < %s", [inicio, fim]
            )
            row = await cur.fetchone()
        return float(row[0]) if row else 0.0


def linha_valida(d: Any) -> dict[str, Any] | None:
    """Linha do ``GET /v1/custos`` → colunas de ``costs``; inválida → ``None`` (pulada)."""
    if not isinstance(d, Mapping):
        return None
    try:
        uid, provider, task = str(d["uid"]), str(d["provider"]), str(d["task"])
        at = datetime.fromisoformat(str(d["at"]))
        usd = float(d.get("usd") or 0)
        entrada = round(float(d.get("input_units") or 0))
        saida = round(float(d.get("output_units") or 0))
    except (KeyError, TypeError, ValueError):
        return None
    if at.tzinfo is None or not uid or not math.isfinite(usd) or usd < 0:
        return None
    modelo = d.get("model")
    return {"uid": uid, "at": at, "provider": provider, "task": task,
            "model": str(modelo) if modelo else None,
            "input_units": entrada, "output_units": saida, "usd": usd}


class CustosPc:
    def __init__(
        self,
        core: Any = None,
        cliente: Any = None,
        *,
        repo: CustosNuvemRepo | None = None,
        http: httpx.AsyncClient | None = None,
        aviso_backup: AvisoBackup | None = None,
        intervalo_s: float = INTERVALO_S,
        checagem_s: float = CHECAGEM_S,
        relogio: Callable[[], float] = time.monotonic,
        agora: Callable[[], datetime] = lambda: datetime.now(TZ),
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """``core``: ``magi.core.assemble.Core``; ``cliente``: ``EloCliente`` (``base_url``,
        cabeçalho com o token, ``modo``)."""
        self.core = core
        self.cliente = cliente
        self._repo = repo
        self._http = http
        self._aviso_backup = aviso_backup
        self._intervalo = intervalo_s
        self._checagem = checagem_s
        self._relogio = relogio
        self._agora = agora
        self._dormir = dormir
        self._desde: str | None = None
        self._desde_lido = False
        self._total: float | None = None
        self._forcar = False

    @property
    def repo(self) -> CustosNuvemRepo | None:
        if self._repo is None and self.core is not None:
            self._repo = PgCustosNuvem.de_core(self.core)
        return self._repo

    def ao_ola(self) -> None:
        self._forcar = True

    def total_mes(self) -> float | None:
        return self._total

    async def atualizar_total(self) -> float | None:
        repo = self.repo
        if repo is None:
            return None
        hoje = self._agora().astimezone(TZ)
        self._total = await repo.total_local_mes(hoje.year, hoje.month)
        return self._total

    async def _get(self, desde: str | None) -> list[Any]:
        base = str(getattr(self.cliente, "base_url", "")).rstrip("/")
        cab = dict(getattr(self.cliente, "_cabecalhos", {}) or {})
        params: dict[str, Any] = {"n": PAGINA}
        if desde:
            params["desde"] = desde
        if self._http is not None:
            r = await self._http.get(base + "/v1/custos", params=params, headers=cab)
        else:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(base + "/v1/custos", params=params, headers=cab)
        r.raise_for_status()
        linhas = r.json().get("linhas", [])
        return linhas if isinstance(linhas, list) else []

    async def puxar(self) -> int:
        """Uma puxada completa (todas as páginas). Devolve quantas linhas novas entraram."""
        repo = self.repo
        if repo is None or self.cliente is None:
            return 0
        if not self._desde_lido:
            self._desde = await repo.ultimo_uid()
            self._desde_lido = True
        novas = 0
        for _ in range(MAX_PAGINAS):
            brutas = await self._get(self._desde)
            linhas = [x for x in (linha_valida(b) for b in brutas) if x is not None]
            if linhas:
                novas += await repo.inserir(linhas)
                self._desde = linhas[-1]["uid"]
            if len(brutas) < PAGINA or not linhas:
                break
        if novas:
            log.info("ayanami: %d custo(s) da nuvem copiados", novas)
        return novas

    async def _volta(self) -> None:
        try:
            await self.puxar()
        except Exception as e:  # rede fora, 401, banco: tenta na próxima volta
            log.info("ayanami: custos não puxados (%s)", type(e).__name__)
        try:
            await self.atualizar_total()
        except Exception as e:
            log.debug("ayanami: total do mês ilegível (%s)", type(e).__name__)
        if self._aviso_backup is None and self.core is not None:
            proativo = getattr(self.core, "proactive", None)
            self._aviso_backup = AvisoBackup.de_core(self.core, AvisosAyanami(proativo))
        if self._aviso_backup is not None:
            try:
                await self._aviso_backup.checar()
            except Exception:
                log.exception("ayanami: aviso de backup falhou")

    async def rodar(self) -> None:
        conectado = False
        proxima: float | None = None
        while True:
            modo = getattr(self.cliente, "modo", None)
            agora = self._relogio()
            conectou = modo is not None and not conectado
            conectado = modo is not None
            if conectou or self._forcar or proxima is None or agora >= proxima:
                self._forcar = False
                await self._volta()
                proxima = self._relogio() + self._intervalo
            await self._dormir(self._checagem)
