"""Orçamento do Learning Mode (tarefa LM3.1; LM-006, spec §2).

Toda chamada de LLM do Learning Mode conta no orçamento mensal existente (``[budget]``, tabela
``costs``) e é **recusada antes da chamada** quando o teto estoura (CA-13). ``LearningBudget``
embrulha o ``Budget`` do núcleo (``magi.core.budget.MonthlyBudget``):

- ``ensure_allowed(label)`` levanta ``BudgetExceeded`` com gasto >= teto. O ``MonthlyBudget`` só
  bloqueia ``BUDGET_BLOCKED_TASKS`` (agent/vision/search), por isso o teto é conferido aqui pelo
  ``status()``. Observações também param ao chegar em ``observe_daily_max`` chamadas no dia.
- ``record(usage, label)`` grava em ``costs`` com ``task`` = ``learning_actions`` ou
  ``learning_observe`` (os rótulos de ``LearningCostTask``) e devolve o custo em USD.

Os rótulos não estão em ``magi.common.contracts.ProviderTask``: a coluna ``costs.task`` é texto
livre e ``CostsRepo.add`` grava ``str(usage.task)``, então um ``StrEnum`` próprio basta.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from magi.common.contracts import Budget, BudgetExceeded, BudgetStatus, Usage
from magi.learning.config import TASK_ACTIONS, TASK_OBSERVE, LearningConfig

TZ = ZoneInfo("America/Sao_Paulo")


class LearningCostTask(StrEnum):
    """Rótulo da coluna ``costs.task`` das chamadas do Learning Mode (LM-006)."""

    ACTIONS = TASK_ACTIONS
    OBSERVE = TASK_OBSERVE


#: Linha curta para o balão quando o teto estoura (design §12).
BUDGET_MESSAGE = "monthly budget reached"


class LearningBudget:
    """Teto e registro de custo das chamadas do Learning Mode sobre o ``Budget`` do núcleo."""

    def __init__(
        self,
        core: Budget,
        *,
        observe_daily_max: int = LearningConfig.observe_daily_max,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._core = core
        self.observe_daily_max = observe_daily_max
        self._now = now or (lambda: datetime.now(TZ))
        self._lock = asyncio.Lock()
        self._day: date | None = None
        self._observe_today = 0

    @classmethod
    def from_config(
        cls, core: Budget, cfg: LearningConfig, *, now: Callable[[], datetime] | None = None
    ) -> LearningBudget:
        return cls(core, observe_daily_max=cfg.observe_daily_max, now=now)

    # -- dia (limite de observações) ----------------------------------------------------------

    def _today(self) -> date:
        today = self._now().astimezone(TZ).date()
        if today != self._day:
            self._day = today
            self._observe_today = 0
        return today

    @property
    def observe_today(self) -> int:
        """Chamadas de observação registradas hoje (dia civil em America/Sao_Paulo)."""
        self._today()
        return self._observe_today

    # -- teto ---------------------------------------------------------------------------------

    async def status(self) -> BudgetStatus:
        return await self._core.status()

    async def ensure_allowed(self, label: LearningCostTask | str) -> None:
        """Levanta ``BudgetExceeded`` se a chamada não pode acontecer (sem chamar o modelo)."""
        label = LearningCostTask(label)
        st = await self._core.status()
        if st.spent_usd >= st.cap_usd:
            raise BudgetExceeded(
                f"{BUDGET_MESSAGE} (US$ {st.spent_usd:.2f} de US$ {st.cap_usd:.2f}); {label} recusada"
            )
        if label is LearningCostTask.OBSERVE and self.observe_today >= self.observe_daily_max:
            raise BudgetExceeded(
                f"limite diário de observações atingido ({self.observe_daily_max}); {label} recusada"
            )

    async def allowed(self, label: LearningCostTask | str) -> bool:
        """``True`` se ``ensure_allowed(label)`` passaria."""
        try:
            await self.ensure_allowed(label)
        except BudgetExceeded:
            return False
        return True

    # -- custo --------------------------------------------------------------------------------

    def price_usd(self, usage: Usage) -> float:
        """USD da chamada pela tabela de preços do núcleo (ou ``usage.usd`` se já vier)."""
        price: Any = getattr(self._core, "price_usd", None)
        usd = float(price(usage)) if callable(price) else float(usage.usd)
        return round(usd, 6)

    async def record(self, usage: Usage, label: LearningCostTask | str | None = None) -> float:
        """Grava em ``costs`` com o rótulo do Learning Mode e devolve o custo em USD."""
        task = LearningCostTask(label if label is not None else str(usage.task))
        usd = self.price_usd(usage)
        priced = replace(usage, task=task, usd=usd)  # type: ignore[arg-type]
        await self._core.record(priced)
        if task is LearningCostTask.OBSERVE:
            async with self._lock:
                self._today()
                self._observe_today += 1
        return usd
