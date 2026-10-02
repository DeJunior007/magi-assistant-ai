"""Interface interna dos adaptadores de provedor (tarefa 3.1).

Um *backend* fala com um provedor (OpenAI, Gemini...) e recebe a chave em cada chamada; não sabe
de rodízio, orçamento nem dados pessoais: isso é do registro (``registry.py``). Recusa de chave
(429/401/403) vira ``KeyRejected``; outras falhas viram ``ProviderError``.
"""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from magi.common.config import ProviderConfig
from magi.common.contracts import (
    ApiKey,
    ChatMessage,
    ChatReply,
    PcmFormat,
    ProviderError,
    ProviderTask,
    SearchResult,
    ToolSpec,
    Transcript,
    Usage,
)


@dataclass(frozen=True, slots=True)
class CallCtx:
    """Provedor, tarefa e modelo de uma chamada (modelo e opções vêm de ``[tasks.<t>]``)."""

    provider: str
    task: ProviderTask
    model: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def usage(self, input_units: float = 0.0, output_units: float = 0.0) -> Usage:
        """``usd`` fica 0: o preço é calculado pelo ``Budget`` (tarefa 3.2)."""
        return Usage(
            provider=self.provider,
            task=self.task,
            model=self.model,
            input_units=float(input_units),
            output_units=float(output_units),
        )


class Backend(Protocol):
    """Adaptador fino de um provedor. Toda chamada recebe a ``ApiKey`` escolhida pelo KeyPool."""

    async def transcribe(
        self, key: ApiKey, ctx: CallCtx, audio: bytes, fmt: PcmFormat, hint: str, language: str
    ) -> tuple[Transcript, Usage | None]: ...

    def tts_format(self, ctx: CallCtx) -> PcmFormat: ...

    def synthesize(self, key: ApiKey, ctx: CallCtx, text: str) -> AsyncIterator[bytes]:
        """PCM em ``tts_format(ctx)``. Recusa de chave deve ocorrer antes do primeiro pedaço."""
        ...

    async def chat(
        self,
        key: ApiKey,
        ctx: CallCtx,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        json_mode: bool,
    ) -> ChatReply: ...

    async def ask(self, key: ApiKey, ctx: CallCtx, question: str, image: bytes, mime: str) -> ChatReply: ...

    def embed_dimensions(self, ctx: CallCtx) -> int: ...

    async def embed(
        self, key: ApiKey, ctx: CallCtx, texts: Sequence[str]
    ) -> tuple[list[list[float]], Usage | None]: ...

    async def search(self, key: ApiKey, ctx: CallCtx, query: str) -> SearchResult: ...


#: Cria o backend a partir de ``[providers.<p>]``.
BackendFactory = Callable[[ProviderConfig], Backend]


def pcm_to_wav(audio: bytes, fmt: PcmFormat) -> bytes:
    """Embrulha PCM cru num WAV em memória (o áudio nunca vai para disco, R3.6)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(fmt.channels)
        w.setsampwidth(fmt.width)
        w.setframerate(fmt.rate)
        w.writeframes(audio)
    return buf.getvalue()


def audio_seconds(audio: bytes, fmt: PcmFormat) -> float:
    per_s = fmt.rate * fmt.width * fmt.channels
    return len(audio) / per_s if per_s else 0.0


def approx_tokens(texts: Sequence[str]) -> int:
    """Estimativa (~4 caracteres por token) quando o provedor não informa o consumo."""
    return sum(len(t) for t in texts) // 4 + (1 if texts else 0)


def get_attr(obj: Any, *path: str, default: Any = None) -> Any:
    """Navega atributos ou chaves de dict sem quebrar com ``None`` (respostas de SDK ou falsas)."""
    cur = obj
    for name in path:
        if cur is None:
            return default
        cur = cur.get(name) if isinstance(cur, Mapping) else getattr(cur, name, None)
    return default if cur is None else cur


#: Timeout padrão por chamada (S3: uma pesquisa no Gemini levou 174 s sem timeout).
SEARCH_TIMEOUT_S = 8.0
DEFAULT_TIMEOUT_S = 15.0


def timeout_s(ctx: CallCtx) -> float:
    """``timeout_s`` de ``[tasks.<t>]``; sem ele, 8 s na pesquisa e 15 s nas demais tarefas."""
    if "timeout_s" in ctx.options:
        return float(ctx.options["timeout_s"])
    return SEARCH_TIMEOUT_S if ctx.task is ProviderTask.SEARCH else DEFAULT_TIMEOUT_S


async def with_timeout[T](ctx: CallCtx, aw: Awaitable[T]) -> T:
    """Teto de tempo da chamada: estouro vira ``ProviderError`` (tratável), não trava o turno."""
    limit = timeout_s(ctx)
    try:
        return await asyncio.wait_for(aw, limit)
    except TimeoutError as e:
        raise ProviderError(f"{ctx.provider}: sem resposta em {limit:g} s ({ctx.task}/{ctx.model})") from e


@dataclass(frozen=True, slots=True)
class PricedSearchResult(SearchResult):
    """``SearchResult`` com consumos extras cobrados à parte, como a taxa por chamada da ferramenta
    ``web_search`` da OpenAI (modelo ``"web_search"`` em ``[budget.prices.openai]``)."""

    extra_usage: tuple[Usage, ...] = ()
