"""Registro de provedores por tarefa (tarefa 3.1, R21.1-R21.5, §4.7).

``Registry`` implementa ``contracts.ProviderRegistry``: lê ``[tasks]`` e ``[providers]`` da config,
monta o backend de cada provedor (OpenAI, Gemini ou outro registrado em ``BACKENDS``) e devolve
objetos que já aplicam, nesta ordem:

1. recusa de ``personal=True`` em provedor ``free_tier`` (``PersonalDataRefused``, R21.5);
2. ``Budget.ensure_allowed(task)`` (só provedores pagos; ``BudgetExceeded`` sobe);
3. rodízio no ``KeyPool``: recusa de chave (429/401/403) põe a chave em espera e tenta a próxima;
   sem chave disponível -> ``NoKeyAvailable`` (``FreeQuotaExhausted`` em cota gratuita);
4. ``Budget.record(usage)`` depois da chamada (só provedores pagos).

``Registry.reload(config)`` serve de callback do ``ConfigWatcher``: troca os provedores e mantém o
estado de espera das chaves cujos nomes não mudaram.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeVar

from magi.common.config import Config, ConfigError, ProviderConfig
from magi.common.contracts import (
    ApiKey,
    Budget,
    ChatMessage,
    ChatReply,
    KeyPool,
    NoKeyAvailable,
    PcmFormat,
    PersonalDataRefused,
    ProviderTask,
    SearchResult,
    ToolSpec,
    Transcript,
    Usage,
)
from magi.providers.base import Backend, BackendFactory, CallCtx
from magi.providers.gemini_provider import GeminiBackend
from magi.providers.keypool import Clock, FreeQuotaExhausted, KeyRejected, RotatingKeyPool, SecretGetter
from magi.providers.openai_provider import OpenAIBackend

log = logging.getLogger(__name__)

T = TypeVar("T")

#: Backends conhecidos, pela chave ``kind`` de ``[providers.<p>]`` (padrão: o nome do provedor).
BACKENDS: dict[str, BackendFactory] = {"openai": OpenAIBackend, "gemini": GeminiBackend}

_SENTENCE_END = re.compile(r"[.!?…;:\n]+[\"')\]»]*\s+")
MAX_TTS_SEGMENT = 400


async def tts_segments(text: str | AsyncIterable[str]) -> AsyncIterator[str]:
    """Quebra um fluxo de texto em frases para o TTS começar a falar antes do fim (R12.1)."""
    if isinstance(text, str):
        if text.strip():
            yield text.strip()
        return
    buf = ""
    async for piece in text:
        buf += piece
        while True:
            ends = list(_SENTENCE_END.finditer(buf))
            if ends:
                cut = ends[-1].end()
            elif len(buf) >= MAX_TTS_SEGMENT:
                cut = buf.rfind(" ", 0, MAX_TTS_SEGMENT) + 1 or MAX_TTS_SEGMENT
            else:
                break
            seg, buf = buf[:cut].strip(), buf[cut:]
            if seg:
                yield seg
    if buf.strip():
        yield buf.strip()


class _Guarded:
    """Base dos provedores devolvidos pelo registro."""

    def __init__(
        self, backend: Backend, ctx: CallCtx, pool: KeyPool, budget: Budget, free_tier: bool
    ) -> None:
        self.name = ctx.provider
        self.model = ctx.model
        self.free_tier = free_tier
        self.task = ctx.task
        self._backend = backend
        self._ctx = ctx
        self._pool = pool
        self._budget = budget

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.task}: {self.name}/{self.model}>"

    def _check_personal(self, personal: bool) -> None:
        if personal and self.free_tier:
            raise PersonalDataRefused(
                f"{self.name} está em cota gratuita e não recebe dados pessoais (tarefa {self.task})"
            )

    async def _before(self, personal: bool) -> None:
        self._check_personal(personal)
        if not self.free_tier:
            await self._budget.ensure_allowed(self.task)

    async def _after(self, usage: Usage | None) -> None:
        if usage is not None and not self.free_tier:
            await self._budget.record(usage)

    def _acquire(self) -> ApiKey:
        try:
            return self._pool.acquire()
        except NoKeyAvailable as e:
            if self.free_tier:
                raise FreeQuotaExhausted(str(e)) from e
            raise

    def _no_key(self, last: KeyRejected | None) -> NoKeyAvailable:
        msg = f"{self.name}: todas as chaves recusadas"
        return FreeQuotaExhausted(msg) if self.free_tier else NoKeyAvailable(msg)

    async def _with_key(self, op: Callable[[ApiKey], Awaitable[T]]) -> T:
        last: KeyRejected | None = None
        for _ in range(max(1, self._pool.available())):
            key = self._acquire()
            try:
                out = await op(key)
            except KeyRejected as e:
                self._pool.mark_failed(key, e.status)
                last = e
                continue
            self._pool.mark_ok(key)
            return out
        raise self._no_key(last) from last

    async def _run(self, personal: bool, op: Callable[[ApiKey], Awaitable[tuple[T, Usage | None]]]) -> T:
        await self._before(personal)
        result, usage = await self._with_key(op)
        await self._after(usage)
        return result


class GuardedStt(_Guarded):
    async def transcribe(
        self, audio: bytes, fmt: PcmFormat, *, hint: str = "", language: str = "pt", personal: bool
    ) -> Transcript:
        return await self._run(
            personal, lambda k: self._backend.transcribe(k, self._ctx, audio, fmt, hint, language)
        )


class GuardedTts(_Guarded):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.output_format = self._backend.tts_format(self._ctx)

    def synthesize(self, text: str | AsyncIterable[str], *, personal: bool) -> AsyncIterator[bytes]:
        self._check_personal(personal)  # recusa já na chamada, antes de consumir o texto
        return self._stream(text, personal)

    async def _stream(self, text: str | AsyncIterable[str], personal: bool) -> AsyncIterator[bytes]:
        await self._before(personal)
        async for segment in tts_segments(text):
            last: KeyRejected | None = None
            for _ in range(max(1, self._pool.available())):
                key = self._acquire()
                started = False
                try:
                    async for chunk in self._backend.synthesize(key, self._ctx, segment):
                        started = True
                        yield chunk
                except KeyRejected as e:
                    self._pool.mark_failed(key, e.status)
                    if started:  # já tocou parte da frase: não dá para repetir com outra chave
                        raise
                    last = e
                    continue
                self._pool.mark_ok(key)
                break
            else:
                raise self._no_key(last) from last
            await self._after(self._ctx.usage(len(segment)))


class GuardedChat(_Guarded):
    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        json_mode: bool = False,
        personal: bool,
    ) -> ChatReply:
        async def op(k: ApiKey) -> tuple[ChatReply, Usage | None]:
            reply = await self._backend.chat(k, self._ctx, messages, tools, json_mode)
            return reply, reply.usage

        return await self._run(personal, op)


class GuardedVision(_Guarded):
    async def ask(self, question: str, image: bytes, *, mime: str = "image/png", personal: bool) -> ChatReply:
        async def op(k: ApiKey) -> tuple[ChatReply, Usage | None]:
            reply = await self._backend.ask(k, self._ctx, question, image, mime)
            return reply, reply.usage

        return await self._run(personal, op)


class GuardedEmbeddings(_Guarded):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dimensions = self._backend.embed_dimensions(self._ctx)

    async def embed(self, texts: Sequence[str], *, personal: bool) -> list[list[float]]:
        if not texts:
            self._check_personal(personal)
            return []
        return await self._run(personal, lambda k: self._backend.embed(k, self._ctx, texts))


class GuardedSearch(_Guarded):
    async def search(self, query: str, *, personal: bool) -> SearchResult:
        async def op(k: ApiKey) -> tuple[SearchResult, Usage | None]:
            res = await self._backend.search(k, self._ctx, query)
            return res, res.usage

        return await self._run(personal, op)


G = TypeVar("G", bound=_Guarded)


class Registry:
    """Implementação de ``contracts.ProviderRegistry`` a partir da ``Config``.

    ``budget`` é injetado (implementação real na tarefa 3.2). ``backends``, ``get_secret`` e
    ``clock`` existem para testes.
    """

    def __init__(
        self,
        config: Config,
        budget: Budget,
        *,
        backends: Mapping[str, BackendFactory] | None = None,
        get_secret: SecretGetter | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self._budget = budget
        self._factories: Mapping[str, BackendFactory] = backends if backends is not None else BACKENDS
        self._get_secret = get_secret
        self._clock = clock
        self._pools: dict[str, tuple[tuple[str, ...], KeyPool]] = {}
        self._config = config
        self._backends: dict[str, Backend] = {}
        self._cache: dict[tuple[type, ProviderTask], _Guarded] = {}

    @property
    def config(self) -> Config:
        return self._config

    def reload(self, config: Config) -> None:
        """Troca a config (callback do ``ConfigWatcher``). Pools com os mesmos nomes de chave são
        mantidos, com o estado de espera."""
        self._config = config
        self._backends.clear()
        self._cache.clear()
        for name in list(self._pools):
            p = config.providers.get(name)
            if p is None or p.keys != self._pools[name][0]:
                del self._pools[name]

    def pool(self, provider: str) -> KeyPool:
        """KeyPool do provedor (criado na primeira vez, lendo o keyring)."""
        cfg = self._config.providers.get(provider)
        if cfg is None:
            raise ConfigError(f"provedor '{provider}' não está em [providers]")
        if provider not in self._pools:
            pool = RotatingKeyPool.from_keyring(
                provider, cfg.keys, get_secret=self._get_secret, clock=self._clock
            )
            self._pools[provider] = (cfg.keys, pool)
        return self._pools[provider][1]

    # -- contrato ProviderRegistry ---------------------------------------------------------

    def stt(self) -> GuardedStt:
        return self._get(GuardedStt, ProviderTask.STT)

    def tts(self) -> GuardedTts:
        return self._get(GuardedTts, ProviderTask.TTS)

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> GuardedChat:
        if task not in (ProviderTask.AGENT, ProviderTask.NEWS):
            raise ValueError(f"chat atende agent ou news, não {task}")
        return self._get(GuardedChat, task)

    def vision(self) -> GuardedVision:
        return self._get(GuardedVision, ProviderTask.VISION)

    def embeddings(self, task: ProviderTask = ProviderTask.EMBEDDINGS) -> GuardedEmbeddings:
        if task not in (ProviderTask.EMBEDDINGS, ProviderTask.NEWS):
            raise ValueError(f"embeddings atende embeddings ou news, não {task}")
        return self._get(GuardedEmbeddings, task)

    def search(self) -> GuardedSearch:
        return self._get(GuardedSearch, ProviderTask.SEARCH)

    # -- montagem --------------------------------------------------------------------------

    def _get(self, cls: type[G], task: ProviderTask) -> G:
        ck = (cls, task)
        if ck not in self._cache:
            ctx = self._ctx(cls, task)
            pcfg = self._config.providers[ctx.provider]
            self._cache[ck] = cls(
                self._backend(pcfg), ctx, self.pool(pcfg.name), self._budget, pcfg.free_tier
            )
        return self._cache[ck]  # type: ignore[return-value]

    def _ctx(self, cls: type, task: ProviderTask) -> CallCtx:
        tcfg = self._config.task(task.value)
        model = tcfg.model
        options = dict(tcfg.options)
        if cls is GuardedEmbeddings and task is ProviderTask.NEWS:
            # O modelo de [tasks.news] é de chat; o de embeddings vem de `embedding_model` ou, no
            # mesmo provedor, de [tasks.embeddings].
            emb = self._config.tasks.get(ProviderTask.EMBEDDINGS.value)
            if "embedding_model" in options:
                model = str(options["embedding_model"])
            elif emb is not None and emb.provider == tcfg.provider:
                model = emb.model
                options = {**emb.options, **options}
            else:
                raise ConfigError("tasks.news precisa de embedding_model para agrupar notícias")
        return CallCtx(provider=tcfg.provider, task=task, model=model, options=options)

    def _backend(self, pcfg: ProviderConfig) -> Backend:
        if pcfg.name not in self._backends:
            kind = str(pcfg.options.get("kind", pcfg.name))
            factory = self._factories.get(kind)
            if factory is None:
                raise ConfigError(
                    f"providers.{pcfg.name}: tipo '{kind}' desconhecido; "
                    f"use kind = um de {sorted(self._factories)}"
                )
            self._backends[pcfg.name] = factory(pcfg)
        return self._backends[pcfg.name]
