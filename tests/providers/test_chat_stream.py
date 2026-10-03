"""Chat em streaming da OpenAI (1.24): texto por pedaço, ferramentas montadas, uso contabilizado."""

from __future__ import annotations

from types import SimpleNamespace as NS

from magi.common.contracts import ChatMessage, ToolCall, ToolSpec
from magi.providers.openai_provider import OpenAIBackend
from magi.providers.registry import Registry


def _chunk(content=None, tool_calls=None, usage=None):
    choices = [] if usage is not None else [NS(delta=NS(content=content, tool_calls=tool_calls))]
    return NS(choices=choices, usage=usage)


class StreamClient:
    def __init__(self, chunks, calls):
        self.chunks = chunks
        self.calls = calls
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kw):
        self.calls.append(kw)

        async def gen():
            for c in self.chunks:
                yield c

        return gen()


def _registry(make_config, budget, get_secret, chunks):
    calls: list = []
    backends = {"openai": lambda cfg: OpenAIBackend(cfg, lambda key: StreamClient(chunks, calls))}
    return Registry(make_config(), budget, backends=backends, get_secret=get_secret), calls


async def test_texto_chega_por_pedaco_e_uso_e_registrado(make_config, budget, get_secret):
    chunks = [_chunk("Oito "), _chunk("patas."), _chunk(usage=NS(prompt_tokens=20, completion_tokens=4))]
    reg, calls = _registry(make_config, budget, get_secret, chunks)
    seen: list[str] = []
    reply = await reg.chat().chat_stream(
        [ChatMessage(role="user", content="oi")], personal=True, on_text=seen.append
    )
    assert seen == ["Oito ", "patas."] and reply.text == "Oito patas." and not reply.tool_calls
    assert calls[0]["stream"] is True and calls[0]["stream_options"] == {"include_usage": True}
    assert (budget.recorded[0].input_units, budget.recorded[0].output_units) == (20, 4)
    assert budget.log[0].startswith("ensure:")


async def test_chamada_de_ferramenta_nao_vira_texto(make_config, budget, get_secret):
    tc1 = NS(index=0, id="c1", function=NS(name="toc", arguments='{"mu'))
    tc2 = NS(index=0, id=None, function=NS(name="ar", arguments='sica": "x"}'))
    chunks = [
        _chunk(tool_calls=[tc1]),
        _chunk(content="depois", tool_calls=[tc2]),
        _chunk(usage=NS(prompt_tokens=9, completion_tokens=2)),
    ]
    reg, _ = _registry(make_config, budget, get_secret, chunks)
    seen: list[str] = []
    reply = await reg.chat().chat_stream(
        [ChatMessage(role="user", content="toca")],
        tools=[ToolSpec("tocar", "x")],
        personal=True,
        on_text=seen.append,
    )
    assert seen == []
    assert reply.tool_calls == (ToolCall("c1", "tocar", {"musica": "x"}),)
    assert budget.recorded[0].output_units == 2
