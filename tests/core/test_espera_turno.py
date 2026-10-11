"""E2.3: frase de espera local no turno (spec §3.3, §3.4, §6; CA-05, CA-06, CA-09, CA-10).

Dublês de ``test_stream_speech``; a espera de ``frase_apos_ms`` é um ``sleep`` injetado que só
volta quando o teste solta (relógio controlado, sem sono real)."""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

from magi.agent.graph import GraphAgent
from magi.common.contracts import (
    Intent,
    RouteKind,
    RouteResult,
    StopPlayback,
    ThinkMsg,
    ToolCall,
    Transcript,
    TurnState,
)
from magi.core.early import EarlySpeech
from magi.core.espera import Catalogo, EsperaCfg
from magi.core.turn import EsperaDeps, TurnDeps, TurnMachine, TurnPipeline

from .test_stream_speech import CTX, FMT, FakeHud, FakeLink, PcmTts, Providers, StreamChat, speaker

FRASE = "Hm, deixa eu pensar."
YAML = f"""
topicos:
  conta:
    palavras: [quanto, calcula]
    frases: ["Calma, deixa eu fazer a conta."]
  geral:
    frases: ["{FRASE}"]
demorados: []
sinais_demora: [pesquisa, preco]
sem_espera: [cansad]
"""


class Clock:
    """``sleep`` injetado: anota o pedido e espera o teste soltar."""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self.go = asyncio.Event()

    async def sleep(self, s: float) -> None:
        self.calls.append(s)
        await self.go.wait()


class Stt:
    def __init__(self, text: str) -> None:
        self.text = text

    async def transcribe(self, audio, fmt, *, hint="", language="pt", personal):
        return Transcript.raw(self.text)


class LocalRouter:
    def route(self, text, ctx):
        return RouteResult(RouteKind.LOCAL, text, 100, intent=Intent("media_play"))


def rig(
    tmp_path: Path, chat: StreamChat, text: str, *, frase: bool = True, router=None
) -> tuple[TurnMachine, FakeLink, FakeHud, PcmTts, Clock]:
    p = tmp_path / "espera.yaml"
    p.write_text(YAML, encoding="utf-8")
    clock = Clock()
    esp = EsperaDeps(
        cfg=EsperaCfg(frase=frase), catalogo=Catalogo.load(p), rng=random.Random(1), sleep=clock.sleep
    )
    tts = PcmTts()
    deps = TurnDeps(
        stt=Stt(text),
        router=router,
        agent=GraphAgent(Providers(chat)),
        speaker=speaker(tmp_path, tts),
        espera=esp,
    )
    link, hud = FakeLink(), FakeHud()
    m = TurnMachine(link, hud, TurnPipeline(deps))
    m._state = TurnState.THINKING
    return m, link, hud, tts, clock


async def _spin(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def test_pedido_demorado_frase_e_resposta_no_mesmo_envio(tmp_path):
    chat = StreamChat([(["O preço tá ", "em mil."], ())])
    chat.gate.clear()  # modelo lento
    m, link, hud, tts, clock = rig(tmp_path, chat, "pesquisa o preço da placa de vídeo")
    m._start(m._think(b"\0\0", FMT, CTX))
    await _spin()
    assert clock.calls == [0.7]  # frase_apos_ms
    assert tts.calls == []
    clock.go.set()
    await asyncio.wait_for(link.first_audio.wait(), 1)
    assert tts.calls == [FRASE] and m.state is TurnState.SPEAKING
    assert ThinkMsg("wait") in hud.msgs
    chat.gate.set()
    await asyncio.wait_for(m._task, 1)
    assert len(link.plays) == 1  # a resposta entra no mesmo envio
    assert tts.calls == [FRASE, "O preço tá em mil."]
    assert m.pipeline.deps.espera.cota("pc").ultimas == [FRASE]


async def test_modelo_rapido_sem_frase(tmp_path):
    chat = StreamChat([(["Tá em mil reais. ", "Isso ", "aí."], ())])
    chat.gate.clear()
    m, link, _, tts, clock = rig(tmp_path, chat, "pesquisa o preço da placa")
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(link.first_audio.wait(), 1)  # o modelo falou antes dos 700 ms
    clock.go.set()
    await _spin()
    chat.gate.set()
    await asyncio.wait_for(m._task, 1)
    assert FRASE not in tts.calls and tts.calls[0] == "Tá em mil reais."
    assert m.pipeline.deps.espera.cota("pc").seguidas == 0


async def test_pedido_nao_demorado_sem_frase(tmp_path):
    for texto in ("oi, tudo bem com você?", "quanto é oito vezes sete", "tô cansado, pesquisa um preço"):
        chat = StreamChat([(["Tudo ", "certo."], ())])
        m, link, _, tts, clock = rig(tmp_path, chat, texto)
        clock.go.set()
        m._start(m._think(b"\0\0", FMT, CTX))
        await asyncio.wait_for(m._task, 1)
        assert clock.calls == [] and FRASE not in tts.calls, texto


async def test_comando_local_sem_frase(tmp_path):
    chat = StreamChat([])
    m, _, _, _, clock = rig(tmp_path, chat, "pesquisa o preço", router=LocalRouter())
    early = EarlySpeech(lambda texts: asyncio.sleep(0))
    assert m._start_espera(Transcript.raw("pesquisa o preço"), CTX, early, followup=False) is None
    assert m._espera is None and clock.calls == []


async def test_frase_desligada_reproduz_hoje(tmp_path):
    chat = StreamChat([(["O preço ", "é mil."], ())])
    m, _, hud, tts, clock = rig(tmp_path, chat, "pesquisa o preço", frase=False)
    clock.go.set()
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(m._task, 1)
    assert clock.calls == [] and tts.calls == ["O preço é mil."]
    assert not any(isinstance(x, ThinkMsg) for x in hud.msgs)


async def _eco(tmp_path, interina: str) -> list[str]:
    chat = StreamChat([([interina], (ToolCall("c1", "nao_existe", {}),)), (["Tá em mil."], ())])
    chat.gate.clear()
    m, link, _, tts, clock = rig(tmp_path, chat, "pesquisa o preço da placa")
    m._start(m._think(b"\0\0", FMT, CTX))
    await _spin()
    clock.go.set()
    await asyncio.wait_for(link.first_audio.wait(), 1)
    chat.gate.set()
    await asyncio.wait_for(m._task, 1)
    assert len(link.plays) == 1
    return tts.calls


async def test_eco_da_espera_vazia_nao_toca(tmp_path):
    assert await _eco(tmp_path, "Deixa eu ver isso.") == [FRASE, "Tá em mil."]


async def test_interina_com_conteudo_toca(tmp_path):
    calls = await _eco(tmp_path, "O tempo eu já sei: sol.")
    assert calls == [FRASE, "O tempo eu já sei: sol.", "Tá em mil."]


async def test_ativacao_no_meio_da_frase_cancela_tudo(tmp_path):
    chat = StreamChat([(["O preço ", "é mil."], ())])
    chat.gate.clear()
    m, link, _, tts, clock = rig(tmp_path, chat, "pesquisa o preço")
    m._start(m._think(b"\0\0", FMT, CTX))
    await _spin()
    clock.go.set()
    await asyncio.wait_for(link.first_audio.wait(), 1)
    await m.wake()
    assert any(isinstance(x, StopPlayback) for x in link.sent)
    assert m.state is TurnState.LISTENING and m._espera is None
    chat.gate.set()
    await _spin()
    assert tts.calls == [FRASE] and not link.done.is_set()


async def test_ativacao_antes_da_frase_cancela_a_tarefa(tmp_path):
    chat = StreamChat([(["O preço ", "é mil."], ())])
    chat.gate.clear()
    m, link, _, tts, clock = rig(tmp_path, chat, "pesquisa o preço")
    m._start(m._think(b"\0\0", FMT, CTX))
    await _spin()
    task = m._espera
    assert task is not None and not task.done()
    await m.wake()
    await _spin()
    assert task.cancelled() and m._espera is None
    clock.go.set()
    chat.gate.set()
    await _spin()
    assert tts.calls == [] and link.plays == []


async def test_peek_route_sem_efeito(tmp_path):
    m, *_ = rig(tmp_path, StreamChat([]), "x")
    assert m.pipeline.peek_route("pesquisa o preço", CTX).kind is RouteKind.AGENT
    m2, *_ = rig(tmp_path, StreamChat([]), "x", router=LocalRouter())
    assert m2.pipeline.peek_route("pesquisa o preço", CTX).kind is RouteKind.LOCAL


def test_early_missing_tira_waits_e_drop_so_uma_vez():
    early = EarlySpeech(lambda texts: asyncio.sleep(0))
    early.waits.append(FRASE)
    assert early.missing(f"{FRASE} Tá em mil.") == ["Tá em mil."]
    assert early.drop_wait_echo("Um segundo.")
    assert not early.drop_wait_echo("Deixa eu ver.")  # só a 1ª
    assert early.skipped == ["Um segundo."]
    assert not EarlySpeech(lambda texts: asyncio.sleep(0)).drop_wait_echo("Um segundo.")  # sem frase local
