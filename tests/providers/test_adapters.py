"""Adaptadores OpenAI e Gemini com clientes HTTP falsos (3.1). Nada de rede aqui; os testes
``live`` só rodam com MAGI_LIVE=1 e chaves no keyring."""

from __future__ import annotations

import dataclasses
import os
from types import SimpleNamespace as NS

import httpx
import openai
import pytest
from google.genai import errors as gerrors

from magi.common.contracts import (
    ChatMessage,
    PcmFormat,
    ProviderError,
    ProviderTask,
    ToolCall,
    ToolSpec,
)
from magi.providers.gemini_provider import GeminiBackend
from magi.providers.openai_provider import OpenAIBackend
from magi.providers.registry import Registry


def _openai_error(status: int) -> openai.APIStatusError:
    resp = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/x"))
    cls = {429: openai.RateLimitError, 401: openai.AuthenticationError, 500: openai.InternalServerError}
    return cls[status]("erro", response=resp, body=None)


class FakeOpenAI:
    """Cliente falso com a forma de ``AsyncOpenAI``. ``fail`` = lista de exceções a levantar antes
    de responder (uma por chamada)."""

    def __init__(self, key, fail=None, calls=None):
        self.key = key
        self.fail = fail if fail is not None else []
        self.calls = calls if calls is not None else []
        self.chat = NS(completions=NS(create=self._chat))
        self.embeddings = NS(create=self._embed)
        self.audio = NS(
            transcriptions=NS(create=self._stt),
            speech=NS(with_streaming_response=NS(create=self._speech)),
        )
        self.responses = NS(create=self._responses)

    def _hit(self, name, kwargs):
        self.calls.append((self.key.name, name, kwargs))
        if self.fail:
            raise self.fail.pop(0)

    async def _chat(self, **kw):
        self._hit("chat", kw)
        tc = NS(id="c1", function=NS(name="tocar", arguments='{"musica": "x"}'))
        msg = NS(content=None if kw.get("tools") else "olá", tool_calls=[tc] if kw.get("tools") else None)
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=12, completion_tokens=3))

    async def _embed(self, **kw):
        self._hit("embed", kw)
        data = [NS(index=i, embedding=[float(i)] * 3) for i in reversed(range(len(kw["input"])))]
        return NS(data=data, usage=NS(prompt_tokens=7))

    async def _stt(self, **kw):
        self._hit("stt", kw)
        return NS(text=" bom dia ")

    def _speech(self, **kw):
        self._hit("tts", kw)

        class Resp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def iter_bytes(self, n):
                yield b"\x01\x02"
                yield b"\x03\x04"

        return Resp()

    async def _responses(self, **kw):
        self._hit("search", kw)
        ann = [
            NS(type="url_citation", url="https://a", title="A"),
            NS(type="url_citation", url="https://a", title="A"),
        ]
        return NS(
            output_text="resposta",
            output=[NS(type="web_search_call"), NS(type="message", content=[NS(annotations=ann)])],
            usage=NS(input_tokens=4, output_tokens=6),
        )


@pytest.fixture
def openai_reg(make_config, budget, get_secret):
    calls: list = []
    fail: list = []
    backends = {"openai": lambda cfg: OpenAIBackend(cfg, lambda key: FakeOpenAI(key, fail, calls))}
    reg = Registry(make_config(), budget, backends=backends, get_secret=get_secret)
    return reg, calls, fail


async def test_openai_chat_mapeia_mensagens_e_ferramentas(openai_reg, budget):
    reg, calls, _ = openai_reg
    msgs = [
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="user", content="toca algo"),
        ChatMessage(role="assistant", content="", tool_calls=(ToolCall("c0", "pausar", {}),)),
        ChatMessage(role="tool", content="ok", tool_call_id="c0"),
    ]
    schema = {"type": "object", "properties": {"musica": {"type": "string"}}}
    tools = [ToolSpec("tocar", "toca música", schema)]
    reply = await reg.chat().chat(msgs, tools=tools, json_mode=True, personal=True)
    assert reply.tool_calls == (ToolCall("c1", "tocar", {"musica": "x"}),)
    key, _, kw = calls[0]
    assert key == "openai-1" and kw["model"] == "chat-x"
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["messages"][2]["tool_calls"][0]["function"] == {"name": "pausar", "arguments": "{}"}
    assert kw["messages"][3] == {"role": "tool", "content": "ok", "tool_call_id": "c0"}
    assert kw["tools"][0]["function"]["name"] == "tocar"
    assert (budget.recorded[0].input_units, budget.recorded[0].output_units) == (12, 3)


async def test_openai_429_alimenta_o_keypool(openai_reg):
    reg, calls, fail = openai_reg
    fail.append(_openai_error(429))
    reply = await reg.chat().chat([ChatMessage(role="user", content="oi")], personal=False)
    assert reply.text == "olá"
    assert [c[0] for c in calls] == ["openai-1", "openai-2"]
    assert reg.pool("openai").available() == 1


async def test_openai_401_em_todas_as_chaves(openai_reg):
    from magi.common.contracts import NoKeyAvailable

    reg, _, fail = openai_reg
    fail.extend([_openai_error(401), _openai_error(401)])
    with pytest.raises(NoKeyAvailable):
        await reg.chat().chat([ChatMessage(role="user", content="oi")], personal=False)


async def test_openai_500_e_erro_comum_sem_espera(openai_reg):
    reg, _, fail = openai_reg
    fail.append(_openai_error(500))
    with pytest.raises(ProviderError, match="500"):
        await reg.chat().chat([ChatMessage(role="user", content="oi")], personal=False)
    assert reg.pool("openai").available() == 2


async def test_openai_stt_tts_embeddings_visao_pesquisa(openai_reg, budget):
    reg, calls, _ = openai_reg
    fmt = PcmFormat()
    t = await reg.stt().transcribe(b"\0" * fmt.bytes_for_ms(500), fmt, hint="Magui", personal=True)
    assert t.heard == "bom dia"
    kw = calls[-1][2]
    assert kw["prompt"] == "Magui" and kw["file"][1][:4] == b"RIFF"
    assert budget.recorded[-1].input_units == pytest.approx(0.5)

    audio = b"".join([c async for c in reg.tts().synthesize("Oi.", personal=True)])
    assert audio == b"\x01\x02\x03\x04"
    assert calls[-1][2]["voice"] == "nova" and calls[-1][2]["response_format"] == "pcm"
    assert reg.tts().output_format == PcmFormat(rate=24_000)

    vecs = await reg.embeddings().embed(["a", "b"], personal=True)
    assert vecs == [[0.0] * 3, [1.0] * 3] and calls[-1][2]["dimensions"] == 8

    r = await reg.vision().ask("o que é?", b"\x89PNG", personal=True)
    content = calls[-1][2]["messages"][0]["content"]
    assert r.text == "olá" and content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    search_openai = {**reg.config.tasks, "search": reg.config.tasks["agent"]}
    reg.reload(dataclasses.replace(reg.config, tasks=search_openai))
    res = await reg.search().search("quem ganhou?", personal=False)
    assert res.answer == "resposta" and [s.url for s in res.sources] == ["https://a"]


# -- Gemini ------------------------------------------------------------------------------------


class FakeGemini:
    """Forma de ``genai.Client(...).aio``."""

    def __init__(self, key, fail, calls, response):
        self.key, self.fail, self.calls, self.response = key, fail, calls, response
        self.models = NS(generate_content=self._gen, embed_content=self._embed)

    async def _gen(self, **kw):
        self.calls.append((self.key.name, "gen", kw))
        if self.fail:
            raise self.fail.pop(0)
        return self.response

    async def _embed(self, **kw):
        self.calls.append((self.key.name, "embed", kw))
        return NS(embeddings=[NS(values=[1.0, 2.0]) for _ in kw["contents"]])


def _gresp(parts, grounding=None):
    cand = NS(content=NS(parts=parts), grounding_metadata=grounding)
    usage = NS(prompt_token_count=9, candidates_token_count=4, thoughts_token_count=None)
    return NS(candidates=[cand], usage_metadata=usage)


@pytest.fixture
def gemini_env(make_config, budget, get_secret):
    calls: list = []
    fail: list = []
    state = {"response": _gresp([NS(text="oi", function_call=None)])}

    def factory(cfg):
        return GeminiBackend(cfg, lambda key: FakeGemini(key, fail, calls, state["response"]))

    reg = Registry(make_config(), budget, backends={"gemini": factory}, get_secret=get_secret)
    return reg, calls, fail, state


async def test_gemini_chat_ferramentas_e_sistema(gemini_env, budget):
    reg, calls, _, state = gemini_env
    state["response"] = _gresp(
        [
            NS(text="pensando", thought=True, function_call=None),
            NS(text=None, function_call=NS(id=None, name="tocar", args={"musica": "x"})),
        ]
    )
    msgs = [
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="assistant", content="", tool_calls=(ToolCall("c0", "pausar", {}),)),
        ChatMessage(role="tool", content='{"ok": true}', tool_call_id="c0"),
    ]
    reply = await reg.chat(ProviderTask.NEWS).chat(
        msgs, tools=[ToolSpec("tocar", "toca", {"type": "object"})], json_mode=True, personal=False
    )
    assert reply.text == "" and reply.tool_calls == (ToolCall("call_1", "tocar", {"musica": "x"}),)
    kw = calls[0][2]
    assert kw["model"] == "news-x"
    assert kw["config"]["system_instruction"] == "persona"
    assert kw["config"]["response_mime_type"] == "application/json"
    assert kw["config"]["tools"][0]["function_declarations"][0]["name"] == "tocar"
    fr = kw["contents"][1]["parts"][0]["function_response"]
    assert fr == {"id": "c0", "name": "pausar", "response": {"ok": True}}
    assert reply.usage.input_units == 9 and reply.usage.output_units == 4
    assert budget.recorded == []  # gemini é free_tier: fora do orçamento


async def test_gemini_pesquisa_com_fontes(gemini_env):
    reg, calls, _, state = gemini_env
    web = [NS(web=NS(uri="https://b", title="B")), NS(web=NS(uri="https://b", title="B")), NS(web=None)]
    state["response"] = _gresp([NS(text="saiu ontem", function_call=None)], NS(grounding_chunks=web))
    res = await reg.search().search("lançamento", personal=False)
    assert res.answer == "saiu ontem" and [(s.title, s.url) for s in res.sources] == [("B", "https://b")]
    assert calls[0][2]["config"] == {"tools": [{"google_search": {}}]}


async def test_gemini_429_troca_e_500_vira_provider_error(gemini_env):
    reg, calls, fail, _ = gemini_env
    fail.append(gerrors.ClientError(429, {"error": {"code": 429, "message": "quota"}}))
    res = await reg.search().search("x", personal=False)
    assert res.answer == "oi" and [c[0] for c in calls] == ["gemini-1", "gemini-2"]
    fail.append(gerrors.ServerError(500, {"error": {"code": 500, "message": "boom"}}))
    with pytest.raises(ProviderError, match="500"):
        await reg.search().search("x", personal=False)
    assert reg.pool("gemini").available() == 1


async def test_gemini_embeddings_de_noticias(gemini_env):
    reg, calls, _, _ = gemini_env
    vecs = await reg.embeddings(ProviderTask.NEWS).embed(["n1", "n2"], personal=False)
    assert vecs == [[1.0, 2.0], [1.0, 2.0]] and calls[0][2]["model"] == "gemb-x"


async def test_gemini_tts_e_stt(make_config, budget, get_secret):
    calls: list = []
    audio = NS(text=None, function_call=None, inline_data=NS(data=b"\x00" * 5000))
    cfg = make_config(
        tasks={
            "stt": {"provider": "gemini", "model": "g-stt"},
            "tts": {"provider": "gemini", "model": "g-tts", "voice": "Kore"},
        }
    )
    reg = Registry(
        cfg,
        budget,
        backends={"gemini": lambda c: GeminiBackend(c, lambda k: FakeGemini(k, [], calls, _gresp([audio])))},
        get_secret=get_secret,
    )
    chunks = [c async for c in reg.tts().synthesize("Oi.", personal=False)]
    assert sum(map(len, chunks)) == 5000 and len(chunks) == 2
    assert calls[0][2]["config"]["response_modalities"] == ["AUDIO"]
    t = await reg.stt().transcribe(b"\0" * 320, PcmFormat(), personal=False)
    assert t.heard == ""
    assert calls[1][2]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "audio/wav"


# -- rede de verdade (pulado por padrão) -------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("MAGI_LIVE"), reason="MAGI_LIVE=1 e chaves no keyring")
async def test_live_chat_pela_config(budget):
    from magi.common.config import load_config

    reg = Registry(load_config(), budget)
    reply = await reg.chat().chat([ChatMessage(role="user", content="Responda só: ok")], personal=False)
    assert reply.text
