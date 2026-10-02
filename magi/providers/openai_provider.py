"""Adaptador fino da OpenAI (SDK ``openai``), tarefa 3.1.

Serve qualquer API compatível: ``[providers.x] kind = "openai"`` + ``base_url``. O cliente é
criado com ``max_retries=0`` para que 429/401/403 cheguem ao KeyPool na hora.
"""

from __future__ import annotations

import base64
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
from magi.providers.base import CallCtx, approx_tokens, audio_seconds, get_attr, pcm_to_wav
from magi.providers.keypool import COOLDOWN_STATUSES, KeyRejected

#: Saída ``pcm`` do endpoint de voz: 24 kHz, 16 bits, mono.
TTS_FORMAT = PcmFormat(rate=24_000, width=2, channels=1)
DEFAULT_DIMENSIONS = 1536
TTS_CHUNK = 4096


@contextmanager
def openai_errors(provider: str) -> Iterator[None]:
    """Traduz exceções do SDK: 429/401/403 -> ``KeyRejected``; o resto -> ``ProviderError``."""
    import openai

    try:
        yield
    except openai.APIStatusError as e:
        if e.status_code in COOLDOWN_STATUSES:
            raise KeyRejected(e.status_code, f"{provider}: {e.message}") from e
        raise ProviderError(f"{provider}: HTTP {e.status_code}: {e.message}") from e
    except openai.OpenAIError as e:
        raise ProviderError(f"{provider}: {e}") from e


def _messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        d: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.role == "assistant" and m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(dict(tc.arguments))},
                }
                for tc in m.tool_calls
            ]
        if m.role == "tool":
            d["tool_call_id"] = m.tool_call_id
        out.append(d)
    return out


def _tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": dict(t.parameters) or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {"_raw": raw}
    return val if isinstance(val, dict) else {"_value": val}


def _reply(resp: Any, ctx: CallCtx) -> ChatReply:
    choices = get_attr(resp, "choices") or [None]
    msg = get_attr(choices[0], "message")
    calls = tuple(
        ToolCall(
            id=str(get_attr(tc, "id", default="")),
            name=str(get_attr(tc, "function", "name", default="")),
            arguments=_parse_args(get_attr(tc, "function", "arguments")),
        )
        for tc in (get_attr(msg, "tool_calls") or ())
    )
    usage = ctx.usage(
        get_attr(resp, "usage", "prompt_tokens", default=0),
        get_attr(resp, "usage", "completion_tokens", default=0),
    )
    return ChatReply(text=get_attr(msg, "content", default=""), tool_calls=calls, usage=usage)


class OpenAIBackend:
    """Implementa ``base.Backend`` com o SDK assíncrono da OpenAI."""

    def __init__(self, cfg: ProviderConfig, client_factory: Callable[[ApiKey], Any] | None = None) -> None:
        self.cfg = cfg
        self._factory = client_factory or self._default_client
        self._clients: dict[tuple[str, str], Any] = {}

    def _default_client(self, key: ApiKey) -> Any:
        import openai

        return openai.AsyncOpenAI(
            api_key=key.secret,
            base_url=self.cfg.options.get("base_url"),
            timeout=float(self.cfg.options.get("timeout_s", 30.0)),
            max_retries=0,
        )

    def _client(self, key: ApiKey) -> Any:
        ck = (key.name, key.secret)
        if ck not in self._clients:
            self._clients[ck] = self._factory(key)
        return self._clients[ck]

    # -- STT -------------------------------------------------------------------------------

    async def transcribe(
        self, key: ApiKey, ctx: CallCtx, audio: bytes, fmt: PcmFormat, hint: str, language: str
    ) -> tuple[Transcript, Usage | None]:
        kwargs: dict[str, Any] = {
            "model": ctx.model,
            "file": ("audio.wav", pcm_to_wav(audio, fmt), "audio/wav"),
            "language": language,
        }
        if hint:
            kwargs["prompt"] = hint
        with openai_errors(ctx.provider):
            res = await self._client(key).audio.transcriptions.create(**kwargs)
        text = res if isinstance(res, str) else get_attr(res, "text", default="")
        return Transcript.raw(text.strip(), language), ctx.usage(audio_seconds(audio, fmt))

    # -- TTS -------------------------------------------------------------------------------

    def tts_format(self, ctx: CallCtx) -> PcmFormat:
        return TTS_FORMAT

    async def synthesize(self, key: ApiKey, ctx: CallCtx, text: str) -> AsyncIterator[bytes]:
        kwargs: dict[str, Any] = {
            "model": ctx.model,
            "voice": ctx.options.get("voice", "alloy"),
            "input": text,
            "response_format": "pcm",
        }
        for opt in ("instructions", "speed"):
            if opt in ctx.options:
                kwargs[opt] = ctx.options[opt]
        with openai_errors(ctx.provider):
            stream = self._client(key).audio.speech.with_streaming_response.create(**kwargs)
            async with stream as resp:
                async for chunk in resp.iter_bytes(TTS_CHUNK):
                    if chunk:
                        yield chunk

    # -- chat / visão ----------------------------------------------------------------------

    async def chat(
        self,
        key: ApiKey,
        ctx: CallCtx,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        json_mode: bool,
    ) -> ChatReply:
        kwargs: dict[str, Any] = {"model": ctx.model, "messages": _messages(messages)}
        if tools:
            kwargs["tools"] = _tools(tools)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if "temperature" in ctx.options:
            kwargs["temperature"] = ctx.options["temperature"]
        with openai_errors(ctx.provider):
            resp = await self._client(key).chat.completions.create(**kwargs)
        return _reply(resp, ctx)

    async def ask(self, key: ApiKey, ctx: CallCtx, question: str, image: bytes, mime: str) -> ChatReply:
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        content = [{"type": "text", "text": question}, {"type": "image_url", "image_url": {"url": url}}]
        with openai_errors(ctx.provider):
            resp = await self._client(key).chat.completions.create(
                model=ctx.model, messages=[{"role": "user", "content": content}]
            )
        return _reply(resp, ctx)

    # -- embeddings ------------------------------------------------------------------------

    def embed_dimensions(self, ctx: CallCtx) -> int:
        return int(ctx.options.get("dimensions", DEFAULT_DIMENSIONS))

    async def embed(
        self, key: ApiKey, ctx: CallCtx, texts: Sequence[str]
    ) -> tuple[list[list[float]], Usage | None]:
        kwargs: dict[str, Any] = {"model": ctx.model, "input": list(texts)}
        if "dimensions" in ctx.options:
            kwargs["dimensions"] = int(ctx.options["dimensions"])
        with openai_errors(ctx.provider):
            resp = await self._client(key).embeddings.create(**kwargs)
        data = sorted(get_attr(resp, "data", default=[]), key=lambda d: get_attr(d, "index", default=0))
        vectors = [list(get_attr(d, "embedding", default=[])) for d in data]
        tokens = get_attr(resp, "usage", "prompt_tokens", default=None)
        return vectors, ctx.usage(tokens if tokens is not None else approx_tokens(texts))

    # -- pesquisa --------------------------------------------------------------------------

    async def search(self, key: ApiKey, ctx: CallCtx, query: str) -> SearchResult:
        with openai_errors(ctx.provider):
            resp = await self._client(key).responses.create(
                model=ctx.model, input=query, tools=[{"type": ctx.options.get("search_tool", "web_search")}]
            )
        sources: dict[str, SearchSource] = {}
        for item in get_attr(resp, "output", default=[]):
            for part in get_attr(item, "content", default=[]) or []:
                for ann in get_attr(part, "annotations", default=[]) or []:
                    url = get_attr(ann, "url")
                    if get_attr(ann, "type") == "url_citation" and url and url not in sources:
                        sources[url] = SearchSource(title=get_attr(ann, "title", default=url), url=url)
        usage = ctx.usage(
            get_attr(resp, "usage", "input_tokens", default=0),
            get_attr(resp, "usage", "output_tokens", default=0),
        )
        return SearchResult(
            answer=get_attr(resp, "output_text", default=""), sources=tuple(sources.values()), usage=usage
        )
