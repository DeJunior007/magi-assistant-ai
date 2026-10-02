"""Rodízio de chaves por provedor (tarefa 3.1, R21.2-R21.4, §4.7).

As chaves são lidas do keyring pelos NOMES listados em ``[providers.<p>].keys``; o segredo nunca
passa pela config. Em 429/401/403 a chave fica em espera: 60 s, dobrando a cada falha seguida,
até 1 h. Sucesso zera a espera.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from magi.common.contracts import ApiKey, NoKeyAvailable, ProviderError, QuotaExhausted

log = logging.getLogger(__name__)

#: Status HTTP que tiram a chave do rodízio por um tempo (limite de uso e autenticação).
COOLDOWN_STATUSES: frozenset[int] = frozenset({401, 403, 429})
BASE_COOLDOWN_S = 60.0
MAX_COOLDOWN_S = 3600.0

Clock = Callable[[], float]
SecretGetter = Callable[[str], "str | None"]


class KeyRejected(ProviderError):
    """Levantado pelos adaptadores quando o provedor recusa a chave (limite ou autenticação).

    O registro captura, chama ``KeyPool.mark_failed(key, status)`` e tenta a próxima chave.
    """

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message or f"chave recusada (HTTP {status})")
        self.status = status


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

    def acquire(self) -> ApiKey:
        now = self._clock()
        n = len(self._slots)
        for i in range(n):
            idx = (self._next + i) % n
            slot = self._slots[idx]
            if slot.until <= now:
                self._next = (idx + 1) % n
                return slot.key
        if not n:
            raise NoKeyAvailable(f"{self.provider}: nenhuma chave configurada no keyring")
        wait = min(s.until for s in self._slots) - now
        raise NoKeyAvailable(f"{self.provider}: todas as {n} chaves em espera (próxima em {wait:.0f} s)")

    def mark_ok(self, key: ApiKey) -> None:
        slot = self._slot(key)
        if slot is not None:
            slot.strikes = 0
            slot.until = 0.0

    def mark_failed(self, key: ApiKey, status: int) -> None:
        if status not in COOLDOWN_STATUSES:
            return
        slot = self._slot(key)
        if slot is None:
            return
        slot.strikes += 1
        wait = self.cooldown_for(slot.strikes)
        slot.until = self._clock() + wait
        log.warning("%s: chave '%s' em espera por %.0f s (HTTP %d)", self.provider, key.name, wait, status)

    def available(self) -> int:
        now = self._clock()
        return sum(1 for s in self._slots if s.until <= now)

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
