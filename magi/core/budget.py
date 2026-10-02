"""Orçamento mensal (tarefa 3.2, §4.6, R16.1-R16.5).

``MonthlyBudget`` implementa ``magi.common.contracts.Budget``. O registro de provedores (3.1)
chama ``ensure_allowed(task)`` antes e ``record(usage)`` depois de cada chamada paga.

Regras:

- **Preço** (R16.1): ``Usage`` chega com ``usd=0`` e unidades (tokens de entrada/saída, segundos
  de áudio no STT, caracteres no TTS). O USD sai da tabela ``[budget.prices.<provider>."<model>"]``
  da config (``input``/``output`` em USD por ``per`` unidades; ``"*"`` vale para qualquer modelo
  do provedor). Se o provedor já mandou ``usd > 0``, esse valor é mantido. Sem preço: custo 0 e
  um aviso no log (uma vez por provedor/modelo).
- **Mês** (R16.5): soma do mês civil em America/Sao_Paulo; no dia 1 o acumulado recomeça sozinho
  (a soma é por mês, nada é apagado).
- **Aviso** (R16.3): ao cruzar 80% do teto, ``on_warn(status)`` é chamado uma vez por mês e por
  teto (se o teto muda, o aviso pode voltar para o novo teto). O núcleo fala o aviso.
- **Bloqueio** (R16.4): com gasto >= teto, ``ensure_allowed`` levanta ``BudgetExceeded`` só para
  ``BUDGET_BLOCKED_TASKS`` (agente, visão, pesquisa). STT/TTS/embeddings/notícias passam.
- **Teto por voz** (R16.2): ``set_cap`` grava num arquivo de estado JSON
  (``<paths.data_dir>/budget_state.json``, escrita atômica, modo 0600) em vez de reescrever o
  ``config.toml`` do usuário (não há escritor de TOML que preserve comentários). O estado guarda
  também o teto da config no momento do ajuste: se o usuário editar ``budget.monthly_usd`` depois,
  a config vence e o ajuste por voz é descartado ("o mais recente vence").
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from magi.common.config import Config, ConfigError
from magi.common.contracts import (
    BUDGET_BLOCKED_TASKS,
    BudgetExceeded,
    BudgetStatus,
    CostsRepo,
    ProviderTask,
    Usage,
)

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")
WARN_FRACTION = 0.8
STATE_FILE = "budget_state.json"

OnWarn = Callable[[BudgetStatus], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class Price:
    """USD por ``per`` unidades de entrada (``input``) e de saída (``output``)."""

    input: float = 0.0
    output: float = 0.0
    per: float = 1_000_000.0

    def usd(self, usage: Usage) -> float:
        return (usage.input_units * self.input + usage.output_units * self.output) / self.per


Prices = dict[tuple[str, str], Price]


def parse_prices(raw: Mapping[str, Any]) -> Prices:
    """Lê ``[budget.prices]`` da config crua (``Config.raw``). Chave: (provedor, modelo)."""
    table = (raw.get("budget") or {}).get("prices") or {}
    prices: Prices = {}
    for provider, models in table.items():
        if not isinstance(models, Mapping):
            raise ConfigError(f"budget.prices.{provider} deve ser uma tabela de modelos")
        for model, p in models.items():
            where = f'budget.prices.{provider}."{model}"'
            if not isinstance(p, Mapping):
                raise ConfigError(f"{where} deve ter input/output/per")
            try:
                price = Price(
                    input=float(p.get("input", 0.0)),
                    output=float(p.get("output", 0.0)),
                    per=float(p.get("per", 1_000_000.0)),
                )
            except (TypeError, ValueError) as e:
                raise ConfigError(f"{where}: valor inválido ({e})") from e
            if price.input < 0 or price.output < 0 or price.per <= 0:
                raise ConfigError(f"{where}: preços >= 0 e per > 0")
            prices[(str(provider), str(model))] = price
    return prices


class CapStateFile:
    """Estado persistido do orçamento (teto por voz e aviso de 80%) num JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("estado do orçamento ilegível (%s): %s; ignorando", self.path, e)
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".budget_", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(dict(data), f)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _month_key(at: datetime) -> str:
    return f"{at.year:04d}-{at.month:02d}"


class MonthlyBudget:
    """``Budget`` com teto mensal, preços da config e soma em ``costs``."""

    def __init__(
        self,
        repo: CostsRepo,
        *,
        cap_usd: float,
        prices: Prices | None = None,
        state: CapStateFile | None = None,
        on_warn: OnWarn | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repo
        self._prices: Prices = dict(prices or {})
        self._state = state
        self._data: dict[str, Any] = state.load() if state else {}
        self._config_cap = 0.0
        self._cap = 0.0
        self.on_warn = on_warn
        self._now = now or (lambda: datetime.now(TZ))
        self._lock = asyncio.Lock()
        self._month: str | None = None
        self._spent = 0.0
        self._unpriced: set[tuple[str, str]] = set()
        self._apply_cap(cap_usd)

    @classmethod
    def from_config(
        cls,
        cfg: Config,
        repo: CostsRepo,
        *,
        on_warn: OnWarn | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> MonthlyBudget:
        return cls(
            repo,
            cap_usd=cfg.budget.monthly_usd,
            prices=parse_prices(cfg.raw),
            state=CapStateFile(cfg.paths.data_dir / STATE_FILE),
            on_warn=on_warn,
            now=now,
        )

    def apply_config(self, cfg: Config) -> None:
        """Releitura da config (``ConfigWatcher``): troca preços e teto."""
        self._prices = parse_prices(cfg.raw)
        self._apply_cap(cfg.budget.monthly_usd)

    # -- teto -------------------------------------------------------------------------------

    def _apply_cap(self, config_cap: float) -> None:
        self._config_cap = float(config_cap)
        voice = self._data.get("cap_usd")
        if voice is not None and self._data.get("config_cap_usd") == self._config_cap:
            self._cap = float(voice)
            return
        if voice is not None:  # config mudou depois do ajuste por voz: a config vence
            log.info("teto da config mudou para %.2f; descartando ajuste por voz", config_cap)
            self._data.pop("cap_usd", None)
            self._data.pop("config_cap_usd", None)
            self._save()
        self._cap = self._config_cap

    @property
    def cap_usd(self) -> float:
        return self._cap

    async def set_cap(self, usd: float) -> None:
        usd = float(usd)
        if usd < 0:
            raise ValueError("o teto não pode ser negativo")
        async with self._lock:
            self._cap = usd
            self._data["cap_usd"] = usd
            self._data["config_cap_usd"] = self._config_cap
            self._save()
            status = await self._status_locked()
        await self._maybe_warn(status)

    def _save(self) -> None:
        if self._state is None:
            return
        try:
            self._state.save(self._data)
        except OSError as e:
            log.warning("não consegui gravar o estado do orçamento: %s", e)

    # -- preço ------------------------------------------------------------------------------

    def price_usd(self, usage: Usage) -> float:
        if usage.usd > 0:
            return usage.usd
        price = self._prices.get((usage.provider, usage.model)) or self._prices.get((usage.provider, "*"))
        if price is None:
            key = (usage.provider, usage.model)
            if key not in self._unpriced:
                self._unpriced.add(key)
                log.warning("sem preço em [budget.prices] para %s/%s; custo 0", *key)
            return 0.0
        return price.usd(usage)

    # -- mês --------------------------------------------------------------------------------

    def _local_now(self) -> datetime:
        return self._now().astimezone(TZ)

    async def _sync_month(self, at: datetime) -> str:
        key = _month_key(at)
        if key != self._month:  # primeiro uso ou virada do mês (R16.5)
            self._spent = round(await self._repo.month_total(at.year, at.month), 6)
            self._month = key
        return key

    async def _status_locked(self) -> BudgetStatus:
        await self._sync_month(self._local_now())
        return BudgetStatus(spent_usd=self._spent, cap_usd=self._cap)

    async def status(self) -> BudgetStatus:
        async with self._lock:
            return await self._status_locked()

    # -- Budget -----------------------------------------------------------------------------

    async def ensure_allowed(self, task: ProviderTask) -> None:
        if task not in BUDGET_BLOCKED_TASKS:
            return
        st = await self.status()
        if st.spent_usd >= st.cap_usd:
            raise BudgetExceeded(
                f"teto mensal atingido (US$ {st.spent_usd:.2f} de US$ {st.cap_usd:.2f}); "
                f"tarefa {task} bloqueada"
            )

    async def record(self, usage: Usage) -> None:
        usd = round(self.price_usd(usage), 6)  # precisão de costs.usd (numeric(12, 6))
        priced = replace(usage, usd=usd)
        async with self._lock:
            at = self._local_now()
            await self._sync_month(at)
            try:
                await self._repo.add(priced, at)
            except Exception:  # falha do banco não derruba a resposta; o teto segue em memória
                log.exception("não consegui gravar custo de %s/%s", usage.provider, usage.model)
            self._spent = round(self._spent + usd, 6)
            status = BudgetStatus(spent_usd=self._spent, cap_usd=self._cap)
        await self._maybe_warn(status)

    async def _maybe_warn(self, status: BudgetStatus) -> None:
        if status.cap_usd <= 0 or status.fraction < WARN_FRACTION or self._month is None:
            return
        mark = {"month": self._month, "cap": status.cap_usd}
        if self._data.get("warned") == mark:
            return
        self._data["warned"] = mark
        self._save()
        if self.on_warn is None:
            return
        try:
            res = self.on_warn(status)
            if inspect.isawaitable(res):
                await res
        except Exception:
            log.exception("on_warn do orçamento falhou")
