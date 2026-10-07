"""Transcrição com vocabulário de dica (tarefa 1.5; R3.1, R3.2, R3.5, R3.6; §4.1 ``stt``).

``HintedStt`` embrulha o provedor de transcrição da config (``SttProvider``) e acrescenta a dica:
nomes dos jogos instalados, gírias/apelidos do ``VocabRepo`` e termos das correções salvas,
priorizados por uso/peso e cortados em ``STT_HINT_MAX_TOKENS``. O áudio só passa em memória
(R3.6). Falha do provedor ou texto vazio viram ``Transcript.raw("")`` e o turno responde
"não peguei, repete?" (R3.5).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import AsyncIterator, Callable, Iterable
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
#: Contexto em português: só a lista de nomes (quase todos de jogos em inglês) puxava a
#: transcrição para o inglês ("Is it early?", "The Earlids").
HINT_PREFIX = "Pedro fala em português do Brasil com a assistente Condessa, no PC de jogos. Vocabulário: "
HINT_SEP = ", "
HINT_END = "."

#: Pesos base por fonte. Correções somam o número de usos; vocabulário usa o próprio peso.
CORRECTION_BASE = 1.0
GAME_WEIGHT = 1.0
ALIAS_WEIGHT = 0.8
#: Termos fixos da dica: como o Pedro chama a assistente para ativar e no meio da fala.
BASE_TERMS: tuple[str, ...] = (
    "Condessa", "HUD", "LEDs", "RGB", "Spotify", "modo ocioso", "volume", "Discord", "Steam",
)
BASE_WEIGHT = 2.0
#: Espera máxima pelo texto final da transcrição enquanto fala depois do fim da fala (1.25);
#: estourou, cai no envio do áudio inteiro.
STREAM_FINAL_TIMEOUT_S = 1.5


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
        base_terms: tuple[str, ...] = BASE_TERMS,
    ) -> None:
        self._provider = provider
        self.base_terms = base_terms
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
        terms = [HintTerm(t, BASE_WEIGHT) for t in self.base_terms]
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
        """Transcreve em memória (R3.6). Falha ou texto vazio → ``Transcript.raw("")`` (R3.5).
        ``language`` padrão ("pt") segue ``[speech] listen`` ("auto" = o modelo detecta)."""
        language = _listen(language)
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

    # -- transcrição enquanto fala (1.25) ------------------------------------------------------

    @property
    def streaming(self) -> bool:
        return bool(getattr(self.inner, "streaming", False))

    def open_stream(
        self, fmt: PcmFormat, *, hint: str = "", language: str = "pt", personal: bool
    ) -> SttStream | None:
        """Abre a transcrição enquanto fala, se o provedor da config a tem ligada; senão ``None``.
        Não bloqueia: a conexão abre em segundo plano e os pedaços esperam numa fila."""
        language = _listen(language)
        try:
            inner = self.inner
            if not getattr(inner, "streaming", False):
                return None
        except Exception as e:  # noqa: BLE001 - sem streaming, o turno segue pelo caminho antigo
            log.debug("transcrição enquanto fala indisponível: %s", e)
            return None
        return SttStream(self, inner, fmt, hint=hint, language=language, personal=personal)


_END = None


def _listen(language: str) -> str:
    """O padrão "pt" dos chamadores vira o idioma de escuta da config ("auto", "en"...)."""
    from magi.core import i18n

    return i18n.listen_language() if language == "pt" else language


class SttStream:
    """Uma sessão de transcrição enquanto fala (1.25). ``feed`` não bloqueia; ``finish`` fecha
    o envio e espera o texto final por até ``timeout`` s, devolvendo ``None`` em falha/estouro
    (quem chama manda o áudio inteiro pelo caminho antigo); ``cancel`` derruba a sessão
    (interrupção, silêncio)."""

    def __init__(
        self, owner: HintedStt, inner: object, fmt: PcmFormat, *, hint: str, language: str, personal: bool
    ) -> None:
        self.fmt = fmt
        self.language = language
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._closed = False
        self._task = asyncio.create_task(self._run(owner, inner, hint, personal), name="stt-stream")
        self._task.add_done_callback(lambda t: t.cancelled() or t.exception())  # sem aviso de erro solto

    async def _chunks(self) -> AsyncIterator[bytes]:
        while (chunk := await self._queue.get()) is not _END:
            yield chunk

    async def _run(self, owner: HintedStt, inner: object, hint: str, personal: bool) -> Transcript:
        full_hint = await owner.build_hint(hint)
        result = await inner.stream_transcribe(  # type: ignore[attr-defined]
            self._chunks(), self.fmt, hint=full_hint, language=self.language, personal=personal
        )
        return Transcript.raw(" ".join((result.heard or "").split()), result.language or self.language)

    @property
    def failed(self) -> bool:
        return self._task.done() and (self._task.cancelled() or self._task.exception() is not None)

    def feed(self, chunk: bytes) -> None:
        if not self._closed and chunk and not self._task.done():
            self._queue.put_nowait(chunk)

    async def finish(self, timeout: float = STREAM_FINAL_TIMEOUT_S) -> Transcript | None:
        """Texto final, ou ``None`` se a sessão falhou, estourou ``timeout`` ou veio vazia."""
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(_END)
        try:
            result = await asyncio.wait_for(asyncio.shield(self._task), timeout)
        except TimeoutError:
            log.warning("transcrição enquanto fala: sem texto em %.1f s; mandando o áudio inteiro", timeout)
            await self.cancel()
            return None
        except asyncio.CancelledError:
            if self._task.cancelled() and not _current_cancelling():
                return None
            await self.cancel()
            raise
        except Exception as e:  # noqa: BLE001 - qualquer falha cai no caminho antigo
            log.warning("transcrição enquanto fala falhou: %s; mandando o áudio inteiro", e)
            return None
        return None if result.is_empty else result

    async def cancel(self) -> None:
        self._closed = True
        if not self._task.done():
            self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task


def _current_cancelling() -> bool:
    task = asyncio.current_task()
    return bool(task is not None and task.cancelling())
