"""Ids do elo: ULID (26 caracteres Crockford, [DS2]) sem dependência nova (spec §1.1).

48 bits de milissegundos desde a época + 80 bits aleatórios. ``novo_id`` aceita relógio e ``rng``
injetados (testes determinísticos); ``para_bytes``/``de_bytes`` dão a forma binária de 16 bytes
usada no cabeçalho dos quadros (§1.4).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from typing import Final

ALFABETO: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE: Final = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_VALOR: Final = {c: i for i, c in enumerate(ALFABETO)}
_MAX_MS: Final = (1 << 48) - 1


def novo_id(
    *,
    agora_ms: Callable[[], int] | None = None,
    rng: Callable[[int], bytes] | None = None,
) -> str:
    """ULID novo. ``agora_ms``: ms desde a época (padrão: relógio real). ``rng(n)``: ``n`` bytes."""
    ms = agora_ms() if agora_ms is not None else time.time_ns() // 1_000_000
    if not 0 <= ms <= _MAX_MS:
        raise ValueError(f"tempo fora da faixa do ULID: {ms}")
    aleatorio = (rng or os.urandom)(10)
    if len(aleatorio) != 10:
        raise ValueError("rng precisa devolver 10 bytes")
    return de_bytes(ms.to_bytes(6, "big") + aleatorio)


def valido(s: object) -> bool:
    """``True`` se ``s`` é um ULID canônico (maiúsculas, 26 caracteres, sem estouro de 128 bits)."""
    return isinstance(s, str) and ULID_RE.fullmatch(s) is not None


def para_bytes(s: str) -> bytes:
    """ULID → 16 bytes (big-endian). ``ValueError`` se inválido."""
    if not valido(s):
        raise ValueError(f"ULID inválido: {s!r}")
    n = 0
    for c in s:
        n = (n << 5) | _VALOR[c]
    return n.to_bytes(16, "big")


def de_bytes(b: bytes) -> str:
    """16 bytes → ULID. ``ValueError`` se o tamanho não for 16."""
    if len(b) != 16:
        raise ValueError("ULID binário precisa de 16 bytes")
    n = int.from_bytes(b, "big")
    return "".join(ALFABETO[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def ms_de(s: str) -> int:
    """Milissegundos do carimbo de tempo do ULID."""
    return int.from_bytes(para_bytes(s)[:6], "big")
