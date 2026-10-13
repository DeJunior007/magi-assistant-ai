"""Gasto da nuvem: sub-teto do modo nuvem dentro do teto geral (dono: Y6.1; spec §6.4, design §7.4,
R8.4, D11a).

:class:`BudgetNuvem` tem a interface do ``Budget`` do PC (``ensure_allowed``/``record``/
``status``, :mod:`magi.core.budget`), com a mesma contagem: mês civil em America/Sao_Paulo e
bloqueio só das ``BUDGET_BLOCKED_TASKS`` (agente, visão, pesquisa; STT/TTS/embeddings passam, então
"liga a TV" segue sem LLM com o teto batido).

- ``nuvem_mes`` = soma de ``costs.usd`` com ``source='nuvem'`` no mês corrente.
- ``pc_mes`` = ``custos_pc.usd`` do mês corrente, gravado por :func:`ao_bate` a partir do
  ``Bate.custos_mes_usd`` do nó ``pc``; sem linha no mês → 0 (o sub-teto da nuvem sozinho segura).
- Bloqueia quando ``nuvem_mes ≥ teto_nuvem`` **ou** ``nuvem_mes + pc_mes ≥ teto_geral``. Em
  :class:`~magi.common.contracts.BudgetStatus`, ``spent_usd`` = ``nuvem_mes`` e ``cap_usd`` = o
  teto efetivo ``max(0, min(teto_nuvem, teto_geral − pc_mes))`` (``spent ≥ cap`` ⇔ bloqueado).
- Preço: o ``Usage`` chega como no PC; ``preco(usage)`` (injetável, por exemplo o
  ``MonthlyBudget.price_usd`` com a tabela ``[budget.prices]``) dá o USD; sem ele vale
  ``usage.usd``.

Contas em ``Decimal`` (``numeric(12, 6)`` no banco), arredondadas a 6 casas como no PC.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID
from zoneinfo import ZoneInfo

from ayanami.api.auth import iso_z
from ayanami.config import AyanamiConfig
from ayanami.db import Db, transacao
from magi.common.contracts import (
    BUDGET_BLOCKED_TASKS,
    BudgetExceeded,
    BudgetStatus,
    ProviderTask,
    Usage,
)
from magi.elo.mensagens import Bate, Envelope, Tipo

log = logging.getLogger("ayanami.custos")

TZ: Final = ZoneInfo("America/Sao_Paulo")
TETO_NUVEM_USD: Final = Decimal("2.00")  # [budget] teto_nuvem_usd
TETO_GERAL_USD: Final = Decimal("5.00")  # [budget] teto_geral_usd
SOURCE: Final = "nuvem"
PAGINA_MAX: Final = 500
_SEIS: Final = Decimal("0.000001")


def _dec(v: float | Decimal) -> Decimal:
    return Decimal(str(v)).quantize(_SEIS)


def mes_de(agora: datetime) -> tuple[date, date]:
    """``(primeiro dia do mês, primeiro dia do mês seguinte)`` em America/Sao_Paulo."""
    local = agora.astimezone(TZ)
    inicio = date(local.year, local.month, 1)
    fim = date(local.year + (local.month == 12), local.month % 12 + 1, 1)
    return inicio, fim


def _limites(agora: datetime) -> tuple[datetime, datetime]:
    inicio, fim = mes_de(agora)
    return (datetime(inicio.year, inicio.month, 1, tzinfo=TZ),
            datetime(fim.year, fim.month, 1, tzinfo=TZ))


@dataclass(frozen=True, slots=True)
class GastoMes:
    nuvem_usd: Decimal
    pc_usd: Decimal
    teto_nuvem_usd: Decimal
    teto_geral_usd: Decimal

    @property
    def teto_efetivo_usd(self) -> Decimal:
        return max(Decimal(0), min(self.teto_nuvem_usd, self.teto_geral_usd - self.pc_usd))

    @property
    def bloqueado(self) -> bool:
        return (self.nuvem_usd >= self.teto_nuvem_usd
                or self.nuvem_usd + self.pc_usd >= self.teto_geral_usd)


class BudgetNuvem:
    """Sub-teto da nuvem (``[budget] teto_nuvem_usd``) dentro do teto geral (``teto_geral_usd``)."""

    def __init__(
        self,
        db: Db,
        relogio: Any,
        *,
        teto_nuvem_usd: float | Decimal = TETO_NUVEM_USD,
        teto_geral_usd: float | Decimal = TETO_GERAL_USD,
        preco: Callable[[Usage], float] | None = None,
    ) -> None:
        self.db = db
        self.relogio = relogio
        self.teto_nuvem = _dec(teto_nuvem_usd)
        self.teto_geral = _dec(teto_geral_usd)
        self._preco = preco

    @classmethod
    def de_config(cls, db: Db, cfg: AyanamiConfig | None, relogio: Any, **kw: Any) -> BudgetNuvem:
        """Tetos de ``[budget]``; ``cfg`` sem ``budget`` (falsos de teste) → os padrões 2/5."""
        b = getattr(cfg, "budget", None)
        return cls(db, relogio,
                   teto_nuvem_usd=getattr(b, "teto_nuvem_usd", TETO_NUVEM_USD),
                   teto_geral_usd=getattr(b, "teto_geral_usd", TETO_GERAL_USD), **kw)

    # --- leitura -------------------------------------------------------------------------------

    def _ler(self, agora: datetime) -> tuple[Decimal, Decimal]:
        de, ate = _limites(agora)
        mes, _ = mes_de(agora)
        with self.db.connection() as conn:
            nuvem = conn.execute(
                "SELECT coalesce(sum(usd), 0) FROM costs WHERE source = %s AND at >= %s AND at < %s",
                (SOURCE, de, ate),
            ).fetchone()[0]
            linha = conn.execute("SELECT usd FROM custos_pc WHERE mes = %s", (mes,)).fetchone()
        return Decimal(nuvem), Decimal(linha[0]) if linha else Decimal(0)

    async def gasto(self) -> GastoMes:
        nuvem, pc = await asyncio.to_thread(self._ler, self.relogio.agora())
        return GastoMes(nuvem, pc, self.teto_nuvem, self.teto_geral)

    async def status(self) -> BudgetStatus:
        g = await self.gasto()
        return BudgetStatus(spent_usd=float(g.nuvem_usd), cap_usd=float(g.teto_efetivo_usd))

    # --- Budget --------------------------------------------------------------------------------

    async def ensure_allowed(self, task: ProviderTask) -> None:
        if task not in BUDGET_BLOCKED_TASKS:
            return
        g = await self.gasto()
        if g.bloqueado:
            raise BudgetExceeded(
                f"teto da nuvem atingido (nuvem US$ {g.nuvem_usd:.2f} de US$ {g.teto_nuvem_usd:.2f}; "
                f"nuvem + pc US$ {g.nuvem_usd + g.pc_usd:.2f} de US$ {g.teto_geral_usd:.2f}); "
                f"tarefa {task} bloqueada"
            )

    def preco_usd(self, usage: Usage) -> Decimal:
        if usage.usd > 0 or self._preco is None:
            return _dec(max(usage.usd, 0.0))
        return _dec(self._preco(usage))

    async def record(self, usage: Usage) -> None:
        usd = self.preco_usd(usage)
        agora = self.relogio.agora()
        try:
            await asyncio.to_thread(self._inserir, usage, usd, agora)
        except Exception:  # noqa: BLE001 - como no PC: falha do banco não derruba a resposta
            log.exception("custo_nao_gravado %s/%s", usage.provider, usage.model)

    def _inserir(self, usage: Usage, usd: Decimal, agora: datetime) -> None:
        with transacao(self.db) as conn:
            conn.execute(
                "INSERT INTO costs (at, provider, task, model, input_units, output_units, usd, source)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (agora, usage.provider, str(usage.task), usage.model, round(usage.input_units),
                 round(usage.output_units), usd, SOURCE),
            )


# --------------------------------------------------------------------------- custos do PC


def gravar_custos_pc(db: Db, agora: datetime, usd: float) -> None:
    mes, _ = mes_de(agora)
    with transacao(db) as conn:
        conn.execute(
            "INSERT INTO custos_pc (mes, usd, visto) VALUES (%s, %s, %s)"
            " ON CONFLICT (mes) DO UPDATE SET usd = EXCLUDED.usd, visto = EXCLUDED.visto",
            (mes, _dec(usd), agora),
        )


def ao_bate(db: Db, relogio: Any) -> Callable[[Any, Envelope], Any]:
    """Gancho ``hub.ao_receber(Tipo.BATE, …)``: o ``custos_mes_usd`` do nó ``pc`` vira a linha do
    mês em ``custos_pc``. Devolve ``None`` (o hub segue o fluxo normal do ``bate``)."""

    async def gancho(disp: Any, env: Envelope) -> None:
        corpo = env.corpo
        if getattr(disp, "tipo", None) != "pc" or not isinstance(corpo, Bate):
            return None
        v = corpo.custos_mes_usd
        if v is None or isinstance(v, bool) or not math.isfinite(v) or v < 0:
            return None
        try:
            await asyncio.to_thread(gravar_custos_pc, db, relogio.agora(), float(v))
        except Exception as e:  # noqa: BLE001 - o bate não pode cair por isso
            log.warning("custos_pc_nao_gravado (%s)", type(e).__name__)
        return None

    return gancho


def ligar(hub: Any, db: Db, relogio: Any) -> None:
    """Liga :func:`ao_bate` ao hub (uma vez por hub)."""
    if getattr(hub, "_custos_ligado", False):
        return
    hub.ao_receber(Tipo.BATE, ao_bate(db, relogio))
    hub._custos_ligado = True


# --------------------------------------------------------------------------- /v1/custos


def linhas_desde(db: Db, desde: UUID | None, limite: int = PAGINA_MAX) -> list[dict[str, Any]]:
    """Linhas ``nuvem`` depois de ``desde`` (por ``id``, em ordem), no máximo ``limite``. ``desde``
    desconhecido (banco restaurado, linha apagada) recomeça do início: o PC não duplica (chave
    ``origem_uid``)."""
    with db.connection() as conn:
        apos = 0
        if desde is not None:
            r = conn.execute("SELECT id FROM costs WHERE uid = %s", (desde,)).fetchone()
            apos = r[0] if r is not None else 0
        cur = conn.execute(
            "SELECT uid, at, provider, task, model, input_units, output_units, usd FROM costs"
            " WHERE source = %s AND id > %s ORDER BY id LIMIT %s",
            (SOURCE, apos, limite),
        )
        return [
            {"uid": str(uid), "at": iso_z(at), "provider": prov, "task": task, "model": model,
             "input_units": int(iu), "output_units": int(ou), "usd": float(usd)}
            for uid, at, prov, task, model, iu, ou, usd in cur.fetchall()
        ]
