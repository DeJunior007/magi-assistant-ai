"""Respostas em lotes (espera viva E3.1, spec §6, CA-07, CA-10)."""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path

from magi.agent.graph import GraphAgent
from magi.common.contracts import SubtitleMsg, ThinkMsg, ToolCall
from magi.core.early import EARLY_SPEECH, THINK_HUD, EarlySpeech
from magi.core.espera import Catalogo, EsperaCfg
from magi.core.turn import EsperaDeps

# Dublês de ``test_stream_speech.py`` (chat em streaming, TTS, link e HUD falsos), sem duplicar.
_DUBLES = Path(__file__).with_name("test_stream_speech.py")
_spec = importlib.util.spec_from_file_location("_stream_dubles", _DUBLES)
assert _spec is not None and _spec.loader is not None
_dub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dub)
CTX, FMT, Providers, StreamChat, machine = _dub.CTX, _dub.FMT, _dub.Providers, _dub.StreamChat, _dub.machine


def tool(i: int) -> tuple[ToolCall, ...]:
    return (ToolCall(f"c{i}", "nao_existe", {}),)


async def run(script, *, lotes_max: int = 3, max_steps: int = 4):
    """Roda o agente com ``EarlySpeech`` e gancho do HUD; devolve (falado, early, avisos, chat)."""
    chat = StreamChat(script)
    said: list[str] = []
    msgs: list[ThinkMsg] = []

    async def play(texts: AsyncIterator[str]) -> None:
        said.extend([t async for t in texts])

    early = EarlySpeech(play, lotes_max=lotes_max)
    chat.early = early
    token, hud = EARLY_SPEECH.set(early), THINK_HUD.set(msgs.append)
    try:
        result = await GraphAgent(Providers(chat), max_steps=max_steps).answer("o tempo e o patch", CTX)
    finally:
        THINK_HUD.reset(hud)
        EARLY_SPEECH.reset(token)
    await early.finish(early.missing(result.speech))
    return said, early, [m for m in msgs if m.v == "lote"], chat, result


DUAS_PARTES = [
    (("",), tool(1)),
    (("O tempo: sol e 25 graus. ",), tool(2)),
    (("Do patch: saiu ontem.",), ()),
]


async def test_ca07_lote_antes_da_segunda_ferramenta_e_legenda_completa():
    said, early, lotes, chat, result = await run(DUAS_PARTES)
    assert chat.spoken_at_call == [0, 0, 1]  # o lote saiu antes de a 2ª ferramenta voltar
    assert early.lotes == [["O tempo: sol e 25 graus."]] and early.interim == []
    assert lotes == [ThinkMsg("lote", n=1)]
    assert said == ["O tempo: sol e 25 graus.", "Do patch: saiu ontem."]
    assert early.full_text(result.full_text) == "O tempo: sol e 25 graus. Do patch: saiu ontem."
    assert len(said) <= 6


async def test_ca10_sem_lotes_e_interina_como_antes():
    said, early, lotes, _, _ = await run(DUAS_PARTES, lotes_max=0)
    assert early.lotes == [] and lotes == []
    assert early.interim == ["O tempo: sol e 25 graus."]
    assert said == ["O tempo: sol e 25 graus.", "Do patch: saiu ontem."]


async def test_primeira_volta_com_duas_frases_vira_lote_e_uma_so_e_interina():
    said, early, lotes, _, _ = await run(
        [(("O tempo: sol. ", "Faz 25 graus. "), tool(1)), (("Do patch: saiu ontem.",), ())]
    )
    assert early.lotes == [["O tempo: sol.", "Faz 25 graus."]] and lotes == [ThinkMsg("lote", n=1)]
    said, early, lotes, _, _ = await run([(("Deixa eu ver. ",), tool(1)), (("Achei.",), ())])
    assert early.lotes == [] and early.interim == ["Deixa eu ver."] and lotes == []


async def test_quatro_voltas_nunca_passam_de_seis_frases_nem_tres_lotes():
    script = [
        (("A um. ", "A dois. "), tool(1)),
        (("B um. ", "B dois. "), tool(2)),
        (("C um. ", "C dois. "), tool(3)),
        (("D um. ", "D dois. "), tool(4)),
        (("Fim um. ", "Fim dois."), ()),
    ]
    said, early, lotes, _, _ = await run(script, max_steps=5)
    assert len(early.lotes) == 3 and [m.n for m in lotes] == [1, 2, 3]
    assert len(said) == 6  # 3 lotes de 2; a 4ª volta vira interina e a final não cabe mais
    counted = [s for s in said if s not in early.interim]
    assert len(counted) <= 6


async def test_early_unidade_tetos_e_full_text():
    said: list[str] = []

    async def play(texts: AsyncIterator[str]) -> None:
        said.extend([t async for t in texts])

    off = EarlySpeech(play)
    assert not off.open_lote() and off.lotes == []
    early = EarlySpeech(play, lotes_max=1, lotes_frases_max=3)
    assert early.open_lote()
    assert early.say("Um.", lote=True) and early.say("Dois.", lote=True)
    assert not early.say("Três.", lote=True)  # até 2 frases por lote
    assert early.close_lote() == 1 and not early.open_lote()  # teto de lotes
    assert early.say("Final.") and not early.say("Outra.")  # 2 + 1 = teto de 3 no turno
    assert early.full_text("Dois. Final.") == "Um. Dois. Final."
    await early.finish(["Sobra."])  # a sobra não passa do teto
    assert said == ["Um.", "Dois.", "Final."]
    assert EarlySpeech(play, lotes_max=1).close_lote() == 0


async def test_turno_liga_lotes_pelo_config_e_legenda_full_tem_o_lote(tmp_path):
    chat = StreamChat(DUAS_PARTES)
    m, _, hud, tts = machine(tmp_path, chat)
    m.pipeline.deps.espera = EsperaDeps(cfg=EsperaCfg(frase=False))
    chat.early = None
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(m._task, 1)
    assert tts.calls == ["O tempo: sol e 25 graus.", "Do patch: saiu ontem."]
    sub = [x for x in hud.msgs if isinstance(x, SubtitleMsg)][-1]
    assert sub.full == "O tempo: sol e 25 graus. Do patch: saiu ontem."
    assert ThinkMsg("lote", n=1) in hud.msgs


async def test_desabafo_e_lotes_desligados_nao_abrem_lote(tmp_path):
    for deps in (
        EsperaDeps(cfg=EsperaCfg(frase=False, lotes=False)),
        EsperaDeps(cfg=EsperaCfg(frase=False), catalogo=Catalogo(sem_espera=("aranh",))),
    ):
        chat = StreamChat(DUAS_PARTES)
        m, _, hud, tts = machine(tmp_path, chat)
        m.pipeline.deps.espera = deps
        m._start(m._think(b"\0\0", FMT, CTX))
        await asyncio.wait_for(m._task, 1)
        assert tts.calls == ["O tempo: sol e 25 graus.", "Do patch: saiu ontem."]
        assert not any(isinstance(x, ThinkMsg) and x.v == "lote" for x in hud.msgs)
        sub = [x for x in hud.msgs if isinstance(x, SubtitleMsg)][-1]
        assert sub.full == "Do patch: saiu ontem."
