"""E5.1: jogo em foco no ``TurnContext`` e nos moldes ``{jogo}`` da frase de espera.

Fonte de jogo falsa no ``TurnDeps.jogo``; a espera de ``frase_apos_ms`` usa o relógio controlado
de ``test_espera_turno`` (sem sono real)."""

from __future__ import annotations

import asyncio
import dataclasses
import random

from magi.agent.graph import GraphAgent
from magi.common.contracts import TurnState
from magi.core.assemble import _jogo_aberto
from magi.core.espera import Catalogo, EsperaCfg
from magi.core.turn import EsperaDeps, TurnDeps, TurnMachine, TurnPipeline

from .test_espera_turno import Clock, Stt, _spin
from .test_stream_speech import CTX, FMT, FakeHud, FakeLink, PcmTts, Providers, StreamChat, speaker

YAML = """
topicos:
  jogo:
    palavras: [build]
    moldes: ["Hm, {jogo}… deixa eu lembrar."]
  geral:
    frases: ["Opa, deixa eu pensar."]
demorados: [jogo]
sinais_demora: []
"""


def maquina(tmp_path, jogo) -> tuple[TurnMachine, FakeLink, PcmTts, Clock, StreamChat]:
    p = tmp_path / "espera.yaml"
    p.write_text(YAML, encoding="utf-8")
    clock, tts = Clock(), PcmTts()
    chat = StreamChat([(["A build boa ", "é de força."], ())])
    chat.gate.clear()
    deps = TurnDeps(
        stt=Stt("qual a melhor build"),
        agent=GraphAgent(Providers(chat)),
        speaker=speaker(tmp_path, tts),
        espera=EsperaDeps(
            cfg=EsperaCfg(frase=True), catalogo=Catalogo.load(p), rng=random.Random(1), sleep=clock.sleep
        ),
        jogo=jogo,
    )
    m = TurnMachine(FakeLink(), FakeHud(), TurnPipeline(deps))
    m._state = TurnState.THINKING
    return m, m.link, tts, clock, chat


def test_contexto_leva_o_jogo(tmp_path):
    m, *_ = maquina(tmp_path, lambda: "  Elden Ring ")
    assert m._make_ctx(None).jogo == "Elden Ring"


def test_contexto_sem_jogo(tmp_path):
    def quebra() -> str:
        raise RuntimeError("varredura falhou")

    for fonte in (None, lambda: None, lambda: "  ", quebra):
        m, *_ = maquina(tmp_path, fonte)
        assert m._make_ctx(None).jogo is None


async def _frase(tmp_path, jogo: str | None) -> str:
    m, link, tts, clock, chat = maquina(tmp_path, None)
    m._start(m._think(b"\0\0", FMT, dataclasses.replace(CTX, jogo=jogo)))
    await _spin()
    clock.go.set()
    await asyncio.wait_for(link.first_audio.wait(), 1)
    chat.gate.set()
    await asyncio.wait_for(m._task, 1)
    return tts.calls[0]


async def test_molde_sai_com_o_jogo(tmp_path):
    assert await _frase(tmp_path, "Hades") == "Hm, Hades… deixa eu lembrar."


async def test_sem_jogo_ou_nome_longo_cai_na_geral(tmp_path):
    assert await _frase(tmp_path, None) == "Opa, deixa eu pensar."
    assert await _frase(tmp_path, "X" * 31) == "Opa, deixa eu pensar."


def test_assemble_le_o_watcher():
    class Watcher:
        game = None

        def running(self):
            return self.game

    w = Watcher()
    nome = _jogo_aberto(w)
    assert nome() is None
    w.game = type("G", (), {"name": "Hollow Knight"})()
    assert nome() == "Hollow Knight"
    assert _jogo_aberto(None)() is None
