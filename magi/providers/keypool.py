"""Rodízio de chaves por provedor (tarefa 3.1, R21.2-R21.4, §4.7).

As chaves são lidas do keyring pelos NOMES listados em ``[providers.<p>].keys``; o segredo nunca
passa pela config. Em 429/401/403 a chave fica em espera: 60 s, dobrando a cada falha seguida,
até 1 h. Sucesso zera a espera.

Um 429 de cota zerada só para um modelo ("limit: 0", modelo sem cota gratuita) não tira a chave do
rodízio: a espera vale só para o par (chave, modelo), e as outras tarefas seguem usando a chave
(achado do S3). Os adaptadores marcam esse caso com ``KeyRejected(..., model_scoped=True)``.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from magi.common.contracts import ApiKey, NoKeyAvailable, ProviderError, QuotaExhausted

log = logging.getLogger(__name__)

#: Status HTTP que tiram a chave do rodízio por um tempo (limite de uso e autenticação).
COOLDOWN_STATUSES: frozenset[int] = frozenset({401, 403, 429})
BASE_COOLDOWN_S = 60.0
MAX_COOLDOWN_S = 3600.0

#: Sinais de cota zerada para um modelo específico (e não de limite geral da chave).
_MODEL_QUOTA = re.compile(
    r"\blimit['\"]?\s*[:=]\s*['\"]?0\b|quota_?value['\"]?\s*[:=]\s*['\"]?0\b"
    r"|not available (?:on|in) the free tier|no free (?:tier )?quota",
    re.IGNORECASE,
)

Clock = Callable[[], float]
SecretGetter = Callable[[str], "str | None"]


class KeyRejected(ProviderError):
    """Levantado pelos adaptadores quando o provedor recusa a chave (limite ou autenticação).

    O registro captura, chama ``KeyPool.mark_failed(key, status)`` e tenta a próxima chave.
    """

    def __init__(self, status: int, message: str = "", *, model_scoped: bool = False) -> None:
        super().__init__(message or f"chave recusada (HTTP {status})")
        self.status = status
        #: ``True`` quando a recusa vale só para o modelo pedido (429 com cota 0 daquele modelo).
        self.model_scoped = model_scoped


def is_model_quota(status: int, text: str) -> bool:
    """429 cujo texto indica cota zerada/inexistente para o modelo (não limite geral da chave)."""
    return status == 429 and bool(_MODEL_QUOTA.search(text or ""))


class FreeQuotaExhausted(NoKeyAvailable, QuotaExhausted):
    """Todas as chaves de um provedor em cota gratuita estão em espera: quem chamou deve adiar,
    sem cair para um provedor pago (R18.6). É ``NoKeyAvailable`` e ``QuotaExhausted`` ao mesmo
    tempo."""


@dataclass
class _Slot:
    key: ApiKey
    strikes: int = 0
    until: float = 0.0


class RotatingKeyPool:
    """Implementação de ``contracts.KeyPool``: rodízio simples com espera progressiva."""

    def __init__(
        self,
        provider: str,
        keys: Iterable[ApiKey],
        *,
        clock: Clock = time.monotonic,
        base_s: float = BASE_COOLDOWN_S,
        max_s: float = MAX_COOLDOWN_S,
    ) -> None:
        self.provider = provider
        self._slots = [_Slot(k) for k in keys]
        self._clock = clock
        self._base = base_s
        self._max = max_s
        self._next = 0
        self._models: dict[tuple[str, str], _Slot] = {}  # espera por (chave, modelo)

    @classmethod
    def from_keyring(
        cls,
        provider: str,
        names: Sequence[str],
        *,
        get_secret: SecretGetter | None = None,
        clock: Clock = time.monotonic,
    ) -> RotatingKeyPool:
        """Lê cada nome do keyring (R21.4). Nomes sem segredo são ignorados com aviso."""
        if get_secret is None:
            from magi.common.secrets import get_secret as get_secret
        keys: list[ApiKey] = []
        for name in names:
            try:
                secret = get_secret(name)
            except Exception as exc:  # keyring indisponível, nome inválido...
                log.warning("chave '%s' (%s) ilegível no keyring: %s", name, provider, exc)
                continue
            if not secret:
                log.warning(
                    "chave '%s' (%s) não está no keyring; rode `magi-keys add %s`", name, provider, name
                )
                continue
            keys.append(ApiKey(provider=provider, name=name, secret=secret))
        return cls(provider, keys, clock=clock)

    # -- contrato KeyPool ------------------------------------------------------------------

    def acquire(self, model: str | None = None) -> ApiKey:
        """Próxima chave livre; com ``model``, pula também as chaves em espera para esse modelo."""
        now = self._clock()
        n = len(self._slots)
        for i in range(n):
            idx = (self._next + i) % n
            slot = self._slots[idx]
            if self._free(slot, model, now):
                self._next = (idx + 1) % n
                return slot.key
        if not n:
            raise NoKeyAvailable(f"{self.provider}: nenhuma chave configurada no keyring")
        wait = min(self._until(s, model) for s in self._slots) - now
        what = f" para {model}" if model and any(s.until <= now for s in self._slots) else ""
        raise NoKeyAvailable(
            f"{self.provider}: todas as {n} chaves em espera{what} (próxima em {wait:.0f} s)"
        )

    def mark_ok(self, key: ApiKey, model: str | None = None) -> None:
        slot = self._slot(key)
        if slot is not None:
            slot.strikes = 0
            slot.until = 0.0
        if model is not None:
            self._models.pop((key.name, model), None)

    def mark_failed(self, key: ApiKey, status: int, model: str | None = None) -> None:
        """Com ``model``, a espera vale só para (chave, modelo); sem, para a chave inteira."""
        if status not in COOLDOWN_STATUSES:
            return
        slot = self._slot(key)
        if slot is None:
            return
        if model is not None:
            slot = self._models.setdefault((key.name, model), _Slot(key))
        slot.strikes += 1
        wait = self.cooldown_for(slot.strikes)
        slot.until = self._clock() + wait
        where = f" para {model}" if model is not None else ""
        log.warning(
            "%s: chave '%s' em espera%s por %.0f s (HTTP %d)", self.provider, key.name, where, wait, status
        )

    def available(self, model: str | None = None) -> int:
        now = self._clock()
        return sum(1 for s in self._slots if self._free(s, model, now))

    def _until(self, slot: _Slot, model: str | None) -> float:
        per_model = self._models.get((slot.key.name, model)) if model is not None else None
        return max(slot.until, per_model.until if per_model else 0.0)

    def _free(self, slot: _Slot, model: str | None, now: float) -> bool:
        return self._until(slot, model) <= now

    # -- extras ----------------------------------------------------------------------------

    def cooldown_for(self, strikes: int) -> float:
        """Espera após ``strikes`` falhas seguidas: 60, 120, 240... até ``max_s``."""
        if strikes <= 0:
            return 0.0
        return min(self._base * 2 ** min(strikes - 1, 30), self._max)

    def names(self) -> tuple[str, ...]:
        return tuple(s.key.name for s in self._slots)

    def __len__(self) -> int:
        return len(self._slots)

    def _slot(self, key: ApiKey) -> _Slot | None:
        for s in self._slots:
            if s.key.name == key.name:
                return s
        return None
