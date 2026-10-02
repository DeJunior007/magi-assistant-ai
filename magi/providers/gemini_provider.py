"""Adaptador fino do Gemini (SDK ``google-genai``), tarefa 3.1.

Usa a API assíncrona (``genai.Client(...).aio``). Pedidos e configs vão como dicts, que o SDK
aceita no lugar dos tipos pydantic. Toda chamada leva o ``timeout_s`` da tarefa em
``http_options`` (e um teto em ``asyncio``); estouro vira ``ProviderError``. A chamada automática
de funções (AFC) do SDK fica desligada: quem executa as ferramentas é o agente.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from magi.common.config import ProviderConfig
from magi.common.contracts import (
    ApiKey,
    ChatMessage,
    ChatReply,
    PcmFormat,
    ProviderError,
    SearchResult,
    SearchSource,
    ToolCall,
    ToolSpec,
    Transcript,
    Usage,
)
from magi.providers.base import (
    CallCtx,
    approx_tokens,
    audio_seconds,
    get_attr,
    pcm_to_wav,
    timeout_s,
    with_timeout,
)
from magi.providers.keypool import COOLDOWN_STATUSES, KeyRejected, is_model_quota

#: Saída de voz dos modelos TTS do Gemini: 24 kHz, 16 bits, mono.
TTS_FORMAT = PcmFormat(rate=24_000, width=2, channels=1)
DEFAULT_DIMENSIONS = 3072
TTS_CHUNK = 4096
STT_PROMPT = (
    "Transcreva literalmente o áudio (idioma: {language}). Responda só com o texto falado, "
    "sem comentários. Se não houver fala, responda vazio."
)


@contextmanager
def gemini_errors(provider: str) -> Iterator[None]:
    """Traduz exceções do SDK: 429/401/403 -> ``KeyRejected``; o resto -> ``ProviderError``."""
    import httpx
    from google.genai import errors

    try:
        yield
    except errors.APIError as e:
        if e.code in COOLDOWN_STATUSES:
            # 429 "limit: 0" do modelo (ex.: grounding do Gemini 3.x) espera só por (chave, modelo).
            scoped = is_model_quota(e.code, f"{e.message} {e.details}")
            raise KeyRejected(e.code, f"{provider}: {e.message}", model_scoped=scoped) from e
        raise ProviderError(f"{provider}: HTTP {e.code}: {e.message}") from e
    except httpx.HTTPError as e:
        raise ProviderError(f"{provider}: {e}") from e


def _tool_result(content: str) -> dict[str, Any]:
    try:
        val = json.loads(content)
    except (TypeError, ValueError):
        return {"result": content}
    return val if isinstance(val, dict) else {"result": val}


def _contents(messages: Sequence[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
    """Separa as mensagens ``system`` (vão em ``system_instruction``) do histórico."""
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for m in messages:
        if m.role == "system":
            system.append(m.content)
        elif m.role == "user":
            contents.append({"role": "user", "parts": [{"text": m.content}]})
        elif m.role == "assistant":
            parts: list[dict[str, Any]] = [{"text": m.content}] if m.content else []
            for tc in m.tool_calls:
                names[tc.id] = tc.name
                parts.append({"function_call": {"id": tc.id, "name": tc.name, "args": dict(tc.arguments)}})
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        else:
            call_id = m.tool_call_id or ""
            fr = {"id": call_id, "name": names.get(call_id, call_id), "response": _tool_result(m.content)}
            contents.append({"role": "user", "parts": [{"function_response": fr}]})
    return "\n\n".join(system), contents


def _parts(resp: Any) -> list[Any]:
    cands = get_attr(resp, "candidates") or [None]
    return list(get_attr(cands[0], "content", "parts", default=[]))


def _reply(resp: Any, ctx: CallCtx) -> ChatReply:
    texts: list[str] = []
    calls: list[ToolCall] = []
    for i, p in enumerate(_parts(resp)):
        fc = get_attr(p, "function_call")
        if fc is not None:
            calls.append(
                ToolCall(
                    id=str(get_attr(fc, "id", default=f"call_{i}")),
                    name=str(get_attr(fc, "name", default="")),
                    arguments=dict(get_attr(fc, "args", default={})),
                )
            )
        elif get_attr(p, "text") and not get_attr(p, "thought"):
            texts.append(get_attr(p, "text"))
    return ChatReply(text="".join(texts), tool_calls=tuple(calls), usage=_usage(resp, ctx))


def _usage(resp: Any, ctx: CallCtx) -> Usage:
    out = get_attr(resp, "usage_metadata", "candidates_token_count", default=0)
    out += get_attr(resp, "usage_metadata", "thoughts_token_count", default=0)
    return ctx.usage(get_attr(resp, "usage_metadata", "prompt_token_count", default=0), out)


#: Prazo mínimo que a API do Gemini aceita (HTTP 400 "Minimum allowed deadline is 10s").
MIN_DEADLINE_MS = 10_000


def _http_options(ctx: CallCtx) -> dict[str, Any]:
    """Prazo do pedido em ms, com o mínimo da API; ``with_timeout`` corta antes se ``timeout_s`` < 10."""
    return {"timeout": max(int(timeout_s(ctx) * 1000), MIN_DEADLINE_MS)}


class GeminiBackend:
    """Implementa ``base.Backend`` com o ``google-genai``."""

    def __init__(self, cfg: ProviderConfig, client_factory: Callable[[ApiKey], Any] | None = None) -> None:
        self.cfg = cfg
        self._factory = client_factory or self._default_client
        self._clients: dict[tuple[str, str], Any] = {}

    def _default_client(self, key: ApiKey) -> Any:
        from google import genai

        return genai.Client(api_key=key.secret).aio

    def _client(self, key: ApiKey) -> Any:
        ck = (key.name, key.secret)
        if ck not in self._clients:
            self._clients[ck] = self._factory(key)
        return self._clients[ck]

    async def _generate(self, key: ApiKey, ctx: CallCtx, contents: Any, config: dict[str, Any]) -> Any:
        config = {**config, "http_options": _http_options(ctx)}
        if "tools" in config:  # sem AFC: nada de chamadas extras nem aviso a cada pedido (S3)
            config["automatic_function_calling"] = {"disable": True}
        with gemini_errors(ctx.provider):
            return await with_timeout(
                ctx,
                self._client(key).models.generate_content(model=ctx.model, contents=contents, config=config),
            )

    # -- STT -------------------------------------------------------------------------------

    async def transcribe(
        self, key: ApiKey, ctx: CallCtx, audio: bytes, fmt: PcmFormat, hint: str, language: str
    ) -> tuple[Transcript, Usage | None]:
        prompt = STT_PROMPT.format(language=language)
        if hint:
            prompt += f"\nVocabulário provável: {hint}"
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"data": pcm_to_wav(audio, fmt), "mime_type": "audio/wav"}},
                ],
            }
        ]
        resp = await self._generate(key, ctx, contents, {})
        reply = _reply(resp, ctx)
        usage = ctx.usage(audio_seconds(audio, fmt))
        return Transcript.raw(reply.text.strip(), language), usage

    # -- TTS -------------------------------------------------------------------------------

    def tts_format(self, ctx: CallCtx) -> PcmFormat:
        return TTS_FORMAT

    async def synthesize(self, key: ApiKey, ctx: CallCtx, text: str) -> AsyncIterator[bytes]:
        voice = ctx.options.get("voice", "Kore")
        config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}},
        }
        resp = await self._generate(key, ctx, text, config)
        for p in _parts(resp):
            data = get_attr(p, "inline_data", "data", default=b"")
            for i in range(0, len(data), TTS_CHUNK):
                yield data[i : i + TTS_CHUNK]

    # -- chat / visão ----------------------------------------------------------------------

    async def chat(
        self,
        key: ApiKey,
        ctx: CallCtx,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        json_mode: bool,
    ) -> ChatReply:
        system, contents = _contents(messages)
        config: dict[str, Any] = {}
        if system:
            config["system_instruction"] = system
        if tools:
            decls = [
                {"name": t.name, "description": t.description, "parameters_json_schema": dict(t.parameters)}
                if t.parameters
                else {"name": t.name, "description": t.description}
                for t in tools
            ]
            config["tools"] = [{"function_declarations": decls}]
        if json_mode:
            config["response_mime_type"] = "application/json"
        if "temperature" in ctx.options:
            config["temperature"] = ctx.options["temperature"]
        return _reply(await self._generate(key, ctx, contents, config), ctx)

    async def ask(self, key: ApiKey, ctx: CallCtx, question: str, image: bytes, mime: str) -> ChatReply:
        contents = [
            {
                "role": "user",
                "parts": [{"text": question}, {"inline_data": {"data": image, "mime_type": mime}}],
            }
        ]
        return _reply(await self._generate(key, ctx, contents, {}), ctx)

    # -- embeddings ------------------------------------------------------------------------

    def embed_dimensions(self, ctx: CallCtx) -> int:
        return int(ctx.options.get("dimensions", DEFAULT_DIMENSIONS))

    async def embed(
        self, key: ApiKey, ctx: CallCtx, texts: Sequence[str]
    ) -> tuple[list[list[float]], Usage | None]:
        config: dict[str, Any] = {"http_options": _http_options(ctx)}
        if "dimensions" in ctx.options:
            config["output_dimensionality"] = int(ctx.options["dimensions"])
        # Um Content por texto: com a lista de strings, o gemini-embedding-2 junta tudo num único
        # conteúdo e devolve 1 vetor para N textos (S3).
        contents = [{"parts": [{"text": t}]} for t in texts]
        with gemini_errors(ctx.provider):
            resp = await with_timeout(
                ctx, self._client(key).models.embed_content(model=ctx.model, contents=contents, config=config)
            )
        vectors = [list(get_attr(e, "values", default=[])) for e in get_attr(resp, "embeddings", default=[])]
        if len(vectors) != len(texts):
            raise ProviderError(
                f"{ctx.provider}: {len(vectors)} vetores para {len(texts)} textos ({ctx.model})"
            )
        return vectors, ctx.usage(approx_tokens(texts))

    # -- pesquisa --------------------------------------------------------------------------

    async def search(self, key: ApiKey, ctx: CallCtx, query: str) -> SearchResult:
        resp = await self._generate(key, ctx, query, {"tools": [{"google_search": {}}]})
        reply = _reply(resp, ctx)
        cands = get_attr(resp, "candidates") or [None]
        sources: dict[str, SearchSource] = {}
        for chunk in get_attr(cands[0], "grounding_metadata", "grounding_chunks", default=[]):
            uri = get_attr(chunk, "web", "uri")
            if uri and uri not in sources:
                sources[uri] = SearchSource(title=get_attr(chunk, "web", "title", default=uri), url=uri)
        return SearchResult(answer=reply.text, sources=tuple(sources.values()), usage=reply.usage)
