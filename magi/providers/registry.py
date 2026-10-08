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

import asyncio
import dataclasses
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
    ProviderError,
    ProviderTask,
    SearchResult,
    ToolSpec,
    Transcript,
    Usage,
)
from magi.providers.base import Backend, BackendFactory, CallCtx
from magi.providers.gemini_provider import GeminiBackend
from magi.providers.keypool import Clock, FreeQuotaExhausted, KeyRejected, RotatingKeyPool, SecretGetter
from magi.providers.kokoro_provider import KokoroBackend
from magi.providers.openai_provider import OpenAIBackend

log = logging.getLogger(__name__)

T = TypeVar("T")

#: Backends conhecidos, pela chave ``kind`` de ``[providers.<p>]`` (padrão: o nome do provedor).
BACKENDS: dict[str, BackendFactory] = {
    "openai": OpenAIBackend,
    "gemini": GeminiBackend,
    "kokoro": KokoroBackend,  # voz local, sem chave
}

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

    def _available(self) -> int:
        if isinstance(self._pool, RotatingKeyPool):
            return self._pool.available(self.model)
        return self._pool.available()

    def _ok(self, key: ApiKey) -> None:
        if isinstance(self._pool, RotatingKeyPool):
            self._pool.mark_ok(key, self.model)
        else:
            self._pool.mark_ok(key)

    def _failed(self, key: ApiKey, e: KeyRejected) -> None:
        """Cota zerada só deste modelo põe em espera o par (chave, modelo), não a chave (S3)."""
        if e.model_scoped and isinstance(self._pool, RotatingKeyPool):
            self._pool.mark_failed(key, e.status, self.model)
        else:
            self._pool.mark_failed(key, e.status)

    def _acquire(self) -> ApiKey:
        try:
            if isinstance(self._pool, RotatingKeyPool):
                return self._pool.acquire(self.model)
            return self._pool.acquire()
        except NoKeyAvailable as e:
            if self.free_tier:
                raise FreeQuotaExhausted(str(e)) from e
            raise

    async def warm(self) -> bool:
        """Abre a conexão HTTP do backend com uma chave do pool, sem custo (1.23). ``False`` se o
        backend não sabe aquecer ou se falhou (nunca levanta)."""
        warm = getattr(self._backend, "warm", None)
        if warm is None:
            return False
        try:
            await warm(self._acquire(), self._ctx)
        except Exception as e:  # noqa: BLE001 - aquecimento é só otimização
            log.debug("%s: aquecimento falhou: %s", self.name, e)
            return False
        return True

    def _no_key(self, last: KeyRejected | None) -> NoKeyAvailable:
        msg = f"{self.name}: todas as chaves recusadas"
        return FreeQuotaExhausted(msg) if self.free_tier else NoKeyAvailable(msg)

    async def _with_key(self, op: Callable[[ApiKey], Awaitable[T]]) -> T:
        last: KeyRejected | None = None
        for _ in range(max(1, self._available())):
            key = self._acquire()
            try:
                out = await op(key)
            except KeyRejected as e:
                self._failed(key, e)
                last = e
                continue
            self._ok(key)
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

    @property
    def streaming(self) -> bool:
        """``[tasks].stt`` com ``streaming = true`` e backend que sabe transcrever enquanto fala
        (1.25)."""
        return bool(self._ctx.options.get("streaming", False)) and hasattr(
            self._backend, "stream_transcribe"
        )

    async def stream_transcribe(
        self,
        chunks: AsyncIterator[bytes],
        fmt: PcmFormat,
        *,
        hint: str = "",
        language: str = "pt",
        personal: bool,
    ) -> Transcript:
        """Transcrição enquanto fala (1.25). Uma chave só, sem rodízio: os pedaços não podem ser
        reenviados (quem chama cai no ``transcribe`` com o áudio inteiro). Mesmo orçamento e
        regra de dados pessoais do ``transcribe``; modelo de ``streaming_model`` ou o da tarefa."""
        model = str(self._ctx.options.get("streaming_model") or self.model)
        ctx = dataclasses.replace(self._ctx, model=model)
        await self._before(personal)
        key = self._acquire()
        try:
            result, usage = await self._backend.stream_transcribe(key, ctx, chunks, fmt, hint, language)  # type: ignore[attr-defined]
        except KeyRejected as e:
            self._failed(key, e)
            raise
        self._ok(key)
        await self._after(usage)
        return result


class GuardedTts(_Guarded):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.output_format = self._backend.tts_format(self._ctx)
        #: Voz de ``[tasks].tts.voice`` ("" = padrão do backend); entra na chave do cache de frases.
        self.voice = str(self._ctx.options.get("voice") or "")

    @property
    def whole_sentence(self) -> bool:
        """O backend entrega cada frase inteira de uma vez (Kokoro): a duração do áudio é
        conhecida antes de tocar, e a legenda do HUD acompanha a fala com ela."""
        return bool(getattr(self._backend, "whole_sentence", False))

    def synthesize(self, text: str | AsyncIterable[str], *, personal: bool) -> AsyncIterator[bytes]:
        self._check_personal(personal)  # recusa já na chamada, antes de consumir o texto
        return self._stream(text, personal)

    async def _stream(self, text: str | AsyncIterable[str], personal: bool) -> AsyncIterator[bytes]:
        await self._before(personal)
        async for segment in tts_segments(text):
            last: KeyRejected | None = None
            for _ in range(max(1, self._available())):
                key = self._acquire()
                started = False
                try:
                    async for chunk in self._backend.synthesize(key, self._ctx, segment):
                        started = True
                        yield chunk
                except KeyRejected as e:
                    self._failed(key, e)
                    if started:  # já tocou parte da frase: não dá para repetir com outra chave
                        raise
                    last = e
                    continue
                self._ok(key)
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
        json_schema: dict | None = None,
        personal: bool,
    ) -> ChatReply:
        # ``json_schema`` só vai ao backend quando presente: quem não pede segue com a chamada de
        # sempre (e backends de teste sem o parâmetro continuam valendo).
        extra: dict[str, Any] = {"json_schema": json_schema} if json_schema is not None else {}

        async def op(k: ApiKey) -> tuple[ChatReply, Usage | None]:
            reply = await self._backend.chat(k, self._ctx, messages, tools, json_mode, **extra)
            return reply, reply.usage

        return await self._run(personal, op)

    async def chat_stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        personal: bool,
        on_text: Callable[[str], None],
    ) -> ChatReply:
        """``chat`` em streaming (1.24): o texto vai para ``on_text`` conforme chega (nada depois
        de uma chamada de ferramenta). Orçamento e uso como em ``chat``. Recusa de chave depois de
        o texto começar não troca de chave (o texto já saiu). Backend sem streaming: ``chat`` e o
        texto inteiro de uma vez, se não houver ferramenta."""
        stream = getattr(self._backend, "chat_stream", None)
        if stream is None:
            reply = await self.chat(messages, tools=tools, personal=personal)
            if reply.text and not reply.tool_calls:
                on_text(reply.text)
            return reply
        started = False

        def emit(piece: str) -> None:
            nonlocal started
            started = True
            on_text(piece)

        async def op(k: ApiKey) -> tuple[ChatReply, Usage | None]:
            try:
                reply = await stream(k, self._ctx, messages, tools, False, emit)
            except KeyRejected as e:
                if started:
                    raise ProviderError(str(e)) from e
                raise
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

        res = await self._run(personal, op)
        for extra in getattr(res, "extra_usage", ()):  # taxa por chamada da ferramenta de busca
            await self._after(extra)
        return res


#: Tarefa opcional em ``[tasks]`` com a pesquisa reserva (3.8).
SEARCH_FALLBACK_TASK = "search_fallback"

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
        self._cache: dict[tuple[type, str], _Guarded] = {}

    @property
    def config(self) -> Config:
        return self._config

    def reload(self, config: Config) -> set[str]:
        """Troca a config (recarga a quente, 1.22). Só os backends e provedores afetados são
        refeitos: backend cujo ``[providers.<p>]`` mudou e objeto de tarefa cuja ``[tasks.<t>]``
        (ou provedor) mudou. Pools com os mesmos nomes de chave são mantidos, com o estado de
        espera. Devolve as tarefas refeitas."""
        old, self._config = self._config, config
        changed_providers = {
            n for n in set(old.providers) | set(config.providers)
            if old.providers.get(n) != config.providers.get(n)
        }
        for name in changed_providers:
            self._backends.pop(name, None)
        rebuilt: set[str] = set()
        for ck in list(self._cache):
            cls, task = ck
            tname = task.value if isinstance(task, ProviderTask) else str(task)
            deps = [tname]
            if cls is GuardedEmbeddings and tname == ProviderTask.NEWS.value:
                deps.append(ProviderTask.EMBEDDINGS.value)
            stale = self._cache[ck].name in changed_providers or any(
                old.tasks.get(d) != config.tasks.get(d) for d in deps
            )
            if stale:
                del self._cache[ck]
                rebuilt.add(tname)
        for name in list(self._pools):
            p = config.providers.get(name)
            if p is None or p.keys != self._pools[name][0]:
                del self._pools[name]
        return rebuilt

    def pool(self, provider: str) -> KeyPool:
        """KeyPool do provedor (criado na primeira vez, lendo o keyring)."""
        cfg = self._config.providers.get(provider)
        if cfg is None:
            raise ConfigError(f"provedor '{provider}' não está em [providers]")
        if provider not in self._pools:
            if cfg.options.get("local"):  # provedor local (Kokoro): uma "chave" simbólica
                pool = RotatingKeyPool(provider, [ApiKey(provider=provider, name="local", secret="")],
                                       clock=self._clock)
            else:
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

    async def warm(self) -> int:
        """Pré-aquece as conexões do caminho de voz (STT, TTS, agente) em paralelo (1.23).
        Chamado a cada ativação: o TLS fica pronto enquanto o usuário fala. Backends repetidos
        (mesmo provedor) são aquecidos uma vez. Devolve quantos aqueceram; nunca levanta."""
        picks: dict[int, _Guarded] = {}
        for get in (self.stt, self.tts, self.chat):
            try:
                g = get()
            except Exception:  # noqa: BLE001 - tarefa sem provedor/chave: nada a aquecer
                continue
            picks.setdefault(id(g._backend), g)
        done = await asyncio.gather(*(g.warm() for g in picks.values()))
        return sum(done)

    def search_fallback(self) -> GuardedSearch | None:
        """Pesquisa reserva de ``[tasks.search_fallback]`` (S3: OpenAI + ``web_search``, paga, para
        quando o Gemini estoura o prazo ou a cota); ``None`` se não configurada. Conta e é bloqueada
        no orçamento como ``search`` (R16.4)."""
        tcfg = self._config.tasks.get(SEARCH_FALLBACK_TASK)
        if tcfg is None:
            return None
        ck = (GuardedSearch, SEARCH_FALLBACK_TASK)
        if ck not in self._cache:
            ctx = CallCtx(provider=tcfg.provider, task=ProviderTask.SEARCH, model=tcfg.model,
                          options=dict(tcfg.options))
            pcfg = self._config.providers[tcfg.provider]
            self._cache[ck] = GuardedSearch(
                self._backend(pcfg), ctx, self.pool(pcfg.name), self._budget, pcfg.free_tier
            )
        return self._cache[ck]  # type: ignore[return-value]

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
