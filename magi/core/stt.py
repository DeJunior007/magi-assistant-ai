"""Transcrição com vocabulário de dica (tarefa 1.5; R3.1, R3.2, R3.5, R3.6; §4.1 ``stt``).

``HintedStt`` embrulha o provedor de transcrição da config (``SttProvider``) e acrescenta a dica:
nomes dos jogos instalados, gírias/apelidos do ``VocabRepo`` e termos das correções salvas,
priorizados por uso/peso e cortados em ``STT_HINT_MAX_TOKENS``. O áudio só passa em memória
(R3.6). Falha do provedor ou texto vazio viram ``Transcript.raw("")`` e o turno responde
"não peguei, repete?" (R3.5).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from magi.common.contracts import (
    STT_HINT_MAX_TOKENS,
    CorrectionsRepo,
    GameCatalog,
    PcmFormat,
    SttProvider,
    Transcript,
    VocabRepo,
)

log = logging.getLogger(__name__)

#: Heurística de tokens sem API: ~3,5 caracteres por token em português.
CHARS_PER_TOKEN = 3.5
HINT_PREFIX = "Vocabulário: "
HINT_SEP = ", "
HINT_END = "."

#: Pesos base por fonte. Correções somam o número de usos; vocabulário usa o próprio peso.
CORRECTION_BASE = 1.0
GAME_WEIGHT = 1.0
ALIAS_WEIGHT = 0.8


def estimate_tokens(text: str) -> int:
    """Tokens estimados de ``text`` (≈ 3,5 caracteres por token)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


@dataclass(frozen=True, slots=True)
class HintTerm:
    term: str
    score: float


def build_hint(terms: Iterable[HintTerm], max_tokens: int = STT_HINT_MAX_TOKENS) -> str:
    """Monta a dica em português: termos por nota (desc.), sem repetição, ≤ ``max_tokens``.

    Empate mantém a ordem de chegada; repetido fica com a maior nota. Termo que não cabe é
    pulado (um menor pode caber).
    """
    ordered = sorted((-t.score, i, term) for i, t in enumerate(terms) if (term := " ".join(t.term.split())))
    seen: set[str] = set()
    picked: list[str] = []
    for _, _, term in ordered:
        if (key := term.casefold()) in seen:
            continue
        seen.add(key)
        candidate = HINT_PREFIX + HINT_SEP.join([*picked, term]) + HINT_END
        if estimate_tokens(candidate) <= max_tokens:
            picked.append(term)
    return HINT_PREFIX + HINT_SEP.join(picked) + HINT_END if picked else ""


class HintedStt:
    """``SttProvider`` com vocabulário de dica e falha tolerada.

    ``provider``: o ``SttProvider`` da config, ou uma função que o devolve a cada chamada
    (ex.: ``registry.stt``), para seguir a releitura da config. Fontes de dica são opcionais.
    """

    def __init__(
        self,
        provider: SttProvider | Callable[[], SttProvider],
        *,
        catalog: GameCatalog | None = None,
        vocab: VocabRepo | None = None,
        corrections: CorrectionsRepo | None = None,
        max_hint_tokens: int = STT_HINT_MAX_TOKENS,
    ) -> None:
        self._provider = provider
        self.catalog = catalog
        self.vocab = vocab
        self.corrections = corrections
        self.max_hint_tokens = max_hint_tokens

    @property
    def inner(self) -> SttProvider:
        p = self._provider
        return p if isinstance(p, SttProvider) else p()

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def model(self) -> str:
        return self.inner.model

    @property
    def free_tier(self) -> bool:
        return self.inner.free_tier

    async def hint_terms(self) -> list[HintTerm]:
        """Termos candidatos de todas as fontes. Fonte que falha é ignorada."""
        terms: list[HintTerm] = []
        if self.corrections is not None:
            try:
                for c in await self.corrections.all():
                    terms.append(HintTerm(c.correct, CORRECTION_BASE + max(c.uses, 0)))
            except Exception as e:  # noqa: BLE001 - dica é opcional
                log.warning("dica: correções indisponíveis: %s", e)
        if self.vocab is not None:
            try:
                for v in await self.vocab.all():
                    terms.append(HintTerm(v.term, v.weight))
            except Exception as e:  # noqa: BLE001
                log.warning("dica: vocabulário indisponível: %s", e)
        if self.catalog is not None:
            try:
                games = self.catalog.all()
                terms.extend(HintTerm(g.name, GAME_WEIGHT) for g in games)
                terms.extend(HintTerm(a, ALIAS_WEIGHT) for g in games for a in g.aliases)
            except Exception as e:  # noqa: BLE001
                log.warning("dica: catálogo indisponível: %s", e)
        return terms

    async def build_hint(self, extra: str = "") -> str:
        """Dica final. ``extra`` (dica de quem chamou) entra como termos de maior prioridade."""
        terms = [HintTerm(t, math.inf) for t in extra.split(",") if t.strip()]
        terms += await self.hint_terms()
        return build_hint(terms, self.max_hint_tokens)

    async def transcribe(
        self, audio: bytes, fmt: PcmFormat, *, hint: str = "", language: str = "pt", personal: bool
    ) -> Transcript:
        """Transcreve em memória (R3.6). Falha ou texto vazio → ``Transcript.raw("")`` (R3.5)."""
        if not audio:
            return Transcript.raw("", language)
        full_hint = await self.build_hint(hint)
        try:
            result = await self.inner.transcribe(
                audio, fmt, hint=full_hint, language=language, personal=personal
            )
        except Exception as e:  # noqa: BLE001 - qualquer falha vira "não peguei" (R3.5)
            log.warning("transcrição falhou: %s", e)
            return Transcript.raw("", language)
        text = " ".join((result.heard or "").split())
        return Transcript.raw(text, result.language or language)
