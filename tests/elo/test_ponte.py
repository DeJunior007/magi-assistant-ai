"""``PonteTurnos``/``NoPc`` (Y6.2): Turno de texto e de áudio pelo ``TurnMachine`` real com core de
teste (STT/agente/TTS falsos), gancho [DS6] (CA-Y22: ``celular`` emite 1 ``TurnoFim``, ``pc``
nada), prazo, montagem só com ``[ayanami]``. Ayanami falsa em memória; nada de rede."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterable, AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from wyoming.audio import AudioChunk, AudioStart

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    AudioEnd,
    AudioEndReason,
    PcmFormat,
    SatelliteHello,
    Transcript,
    TurnContext,
    WakeEvent,
    WakeSource,
)
from magi.core.assemble import Core, NullBudget, SwitchBudget, _wire_ayanami
from magi.core.hud_client import NullHud
from magi.core.service import CoreService
from magi.core.turn import TurnDeps, TurnMachine
from magi.elo import pc as pc_mod
from magi.elo.cliente import EloCliente
from magi.elo.ids import novo_id
from magi.elo.mensagens import (
    Ack,
    Envelope,
    ResumoNuvem,
    Tipo,
    Turno,
    TurnoFim,
    TurnoNuvem,
    decode,
    encode,
    responder,
)
from magi.elo.pc import NoPc
from magi.elo.ponte import PonteTurnos, _Ativo
from magi.elo.quadros import Quadro, QuadroTipo, encode_quadro
from magi.elo.remote import ENTRADA_FMT

OUT = PcmFormat(rate=24000, width=2, channels=1)
RESPOSTA = "São três horas. Veja https://exemplo.com/hora"


class SttFalso:
    name = "stt-falso"

    def __init__(self) -> None:
        self.audios: list[bytes] = []

    async def transcribe(self, audio: bytes, fmt: PcmFormat, *, hint: str = "",
                         language: str = "pt", personal: bool) -> Transcript:
        self.audios.append(audio)
        return Transcript.raw("que horas são")


class AgenteFalso:
    def __init__(self, *, trava: bool = False) -> None:
        self.textos: list[str] = []
        self.trava = trava

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        self.textos.append(text)
        if self.trava:
            await asyncio.Event().wait()
        return ActionResult(ok=True, speech=RESPOSTA)


class SpeakerFalso:
    async def say(self, text: str, link: Any, *, personal: bool) -> None:
        async def blocos() -> AsyncIterator[bytes]:
            for _ in range(3):
                yield bytes(OUT.bytes_for_ms(80))

        await link.play(blocos(), OUT)


class ClienteFalso:
    """Lado PC do elo sem rede: guarda envelopes e quadros mandados."""

    def __init__(self) -> None:
        self.enviados: list[tuple[Tipo, Any]] = []
        self.quadros: list[Quadro] = []
        self.handlers: dict[Tipo, Any] = {}
        self.handlers_quadro: list[Any] = []

    async def enviar(self, t: Tipo, corpo: Any, para: str = "ayanami", **_: Any) -> None:
        self.enviados.append((t, corpo))

    async def enviar_quadro(self, q: Quadro) -> None:
        self.quadros.append(q)

    def on(self, t: Tipo, fn: Any) -> None:
        self.handlers[Tipo(t)] = fn

    def on_quadro(self, fn: Any) -> None:
        self.handlers_quadro.append(fn)

    def fins(self) -> list[TurnoFim]:
        return [c for t, c in self.enviados if t is Tipo.TURNO_FIM]


class LinkPcFalso:
    def __init__(self) -> None:
        self.hello = SatelliteHello("pc", name="PC")
        self.tocou = 0
        self.enviados: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.enviados.append(msg)

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        async for _ in audio:
            self.tocou += 1


async def _ate(cond: Any, limite_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    fim = loop.time() + limite_s
    while not cond():
        if loop.time() > fim:
            raise AssertionError("condição não chegou")
        await asyncio.sleep(0.001)


def _montar(**kw: Any) -> tuple[CoreService, ClienteFalso, PonteTurnos, SttFalso, AgenteFalso]:
    stt, agente = SttFalso(), AgenteFalso(trava=kw.pop("trava", False))
    service = CoreService(TurnDeps(stt=stt, agent=agente, speaker=SpeakerFalso()), NullHud(), port=0)
    cliente = ClienteFalso()
    return service, cliente, PonteTurnos(service, cliente, **kw), stt, agente


def _env(corpo: Turno) -> Envelope:
    return Envelope(t=Tipo.TURNO, corpo=corpo, de="ayanami", para="pc")


def _fim_da_fala(cliente: ClienteFalso, ponte: PonteTurnos) -> bool:
    return (bool(cliente.fins()) and ponte.machine is not None
            and ponte.machine.state.value == "sleeping"
            and any(q.tipo is QuadroTipo.AUDIO_FIM for q in cliente.quadros))


async def test_turno_de_texto_devolve_turno_fim_com_cards_sem_stt() -> None:
    service, cliente, ponte, stt, agente = _montar()
    t = novo_id()
    await ponte.receber(_env(Turno(turno=t, texto="que horas são?", dispositivo="pedro-cel")))
    await _ate(lambda: _fim_da_fala(cliente, ponte))
    [fim] = cliente.fins()
    assert fim.turno == t and fim.ok and fim.erro is None
    assert fim.cards and fim.cards[0].url == "https://exemplo.com/hora"
    assert "https://exemplo.com/hora" in fim.texto and fim.fala
    assert stt.audios == [] and agente.textos == ["que horas são?"]
    outs = [q for q in cliente.quadros if q.tipo is QuadroTipo.AUDIO_OUT]
    assert outs and all(q.turno == t for q in cliente.quadros)
    assert service.machine("celular") is ponte.machine
    assert "celular" not in service.satellites  # proatividade e clique no rosto não vão ao celular
    await ponte.aclose()


async def test_turno_de_audio_pcm_falso_vira_ptt() -> None:
    _service, cliente, ponte, stt, agente = _montar()
    t = novo_id()
    await ponte.receber(_env(Turno(turno=t, audio=True)))
    pcm = bytes(range(256)) * 10  # 2560 bytes = 80 ms a 16 kHz
    for _ in range(5):
        ponte.receber_quadro(Quadro(QuadroTipo.AUDIO_IN, t, pcm))
    ponte.receber_quadro(Quadro(QuadroTipo.AUDIO_FIM, t))
    await _ate(lambda: _fim_da_fala(cliente, ponte))
    [fim] = cliente.fins()
    assert fim.turno == t and fim.ok and fim.cards
    assert len(stt.audios) == 1 and agente.textos == ["que horas são"]
    assert len(stt.audios[0]) == 5 * len(pcm)
    await ponte.aclose()


async def test_gancho_celular_emite_um_turno_fim_e_pc_nada() -> None:
    """CA-Y22 (parte gancho)."""
    _service, cliente, ponte, _stt, _ag = _montar()
    t = novo_id()
    ponte._ativo = _Ativo(t)  # noqa: SLF001
    ponte.link.novo_turno(t)
    agora = datetime.now(UTC)
    res = ActionResult(ok=True, speech="Oi.")
    await ponte.on_turn_done(TurnContext("pc", WakeSource.WAKE, agora), res)
    await asyncio.sleep(0)
    assert cliente.fins() == []
    await ponte.on_turn_done(TurnContext("celular", WakeSource.PTT, agora), res)
    await ponte.on_turn_done(TurnContext("celular", WakeSource.PTT, agora), res)  # 2ª entrega
    await asyncio.sleep(0)
    assert [f.turno for f in cliente.fins()] == [t]
    await ponte.aclose()


async def test_turno_do_headset_nao_vai_ao_celular() -> None:
    service, cliente, ponte, _stt, _ag = _montar()
    link = LinkPcFalso()
    machine = TurnMachine(link, NullHud(), service.pipeline)
    f = ENTRADA_FMT
    await machine.handle(WakeEvent(WakeSource.PTT, "pc"))
    await machine.handle(AudioStart(rate=f.rate, width=f.width, channels=f.channels))
    await machine.handle(AudioChunk(rate=f.rate, width=f.width, channels=f.channels,
                                    audio=bytes(range(256)) * 10))
    await machine.handle(AudioEnd(reason=AudioEndReason.PTT_RELEASE))
    await _ate(lambda: link.tocou > 0)
    assert cliente.fins() == [] and cliente.quadros == []
    await machine.close()
    await ponte.aclose()


async def test_prazo_estourado_da_erro_tempo_e_descarta_resposta() -> None:
    _service, cliente, ponte, _stt, agente = _montar(trava=True, prazo_s=0.02)
    t = novo_id()
    await ponte.receber(_env(Turno(turno=t, texto="pesquisa algo")))
    await _ate(lambda: bool(cliente.fins()))
    [fim] = cliente.fins()
    assert fim.turno == t and not fim.ok and fim.erro == "tempo"
    assert agente.textos == ["pesquisa algo"]
    await ponte.aclose()


async def test_turno_novo_com_outro_em_andamento_e_ocupado() -> None:
    _service, cliente, ponte, _stt, _ag = _montar(trava=True, prazo_s=5)
    t1, t2 = novo_id(), novo_id()
    await ponte.receber(_env(Turno(turno=t1, texto="um")))
    await ponte.receber(_env(Turno(turno=t2, texto="dois")))
    await _ate(lambda: bool(cliente.fins()))
    assert [(f.turno, f.erro) for f in cliente.fins()] == [(t2, "ocupado")]
    await ponte.aclose()


# --- NoPc ---------------------------------------------------------------------------------------


class ConexaoAyanami:
    """Ayanami falsa em memória: ``ack`` ao ``ola`` e ao ``turno_fim``; guarda o que chega."""

    def __init__(self) -> None:
        self.recebidos: list[str | bytes] = []
        self.entrada: asyncio.Queue[str | bytes] = asyncio.Queue()

    async def enviar(self, dado: str | bytes) -> None:
        self.recebidos.append(dado)
        if isinstance(dado, str):
            env = decode(dado)
            if env.resp is None and env.t in (Tipo.OLA, Tipo.TURNO_FIM):
                self.entrada.put_nowait(encode(responder(env, Tipo.ACK, Ack(), "ayanami")))

    async def receber(self) -> str | bytes:
        return await self.entrada.get()

    async def fechar(self) -> None:
        return None

    def envs(self, t: Tipo) -> list[Envelope]:
        return [e for d in self.recebidos if isinstance(d, str) and (e := decode(d)).t is t]


async def test_nopc_turno_pela_ws_falsa_ida_e_volta() -> None:
    con = ConexaoAyanami()

    async def conectar(url: str, cab: Any) -> ConexaoAyanami:
        return con

    async def dormir(s: float) -> None:
        await asyncio.sleep(0)

    def fabrica(ola: Any, custos: Any) -> EloCliente:
        return EloCliente("https://ayanami.exemplo.ts.net", "ayn_pc_falso", "pc", ola, custos=custos,
                          relogio=lambda: 0.0, dormir=dormir, rng=random.Random(1), conectar=conectar)

    stt, agente = SttFalso(), AgenteFalso()
    service = CoreService(TurnDeps(stt=stt, agent=agente, speaker=SpeakerFalso()), NullHud(), port=0)
    no = NoPc(fabrica, None)
    no.iniciar(service)
    await _ate(lambda: bool(con.envs(Tipo.OLA)))
    assert con.envs(Tipo.OLA)[0].corpo.caps == ("turno", "acao", "evento", "resumo")
    t = novo_id()
    env = Envelope(t=Tipo.TURNO, corpo=Turno(turno=t, audio=True), de="ayanami", para="pc")
    con.entrada.put_nowait(encode(env))
    for _ in range(3):
        con.entrada.put_nowait(encode_quadro(Quadro(QuadroTipo.AUDIO_IN, t, bytes(2560))))
    con.entrada.put_nowait(encode_quadro(Quadro(QuadroTipo.AUDIO_FIM, t)))
    await _ate(lambda: bool(con.envs(Tipo.TURNO_FIM)))
    acks = [e for e in con.envs(Tipo.ACK) if e.resp == env.id]
    assert len(acks) == 1  # o turno foi aceito
    [fim] = con.envs(Tipo.TURNO_FIM)
    assert fim.corpo.turno == t and fim.corpo.ok and fim.corpo.cards
    await _ate(lambda: any(isinstance(d, bytes) for d in con.recebidos))
    # resumo_nuvem: stub da Y6.5 não grava nada → ack vazio
    resumo = ResumoNuvem(turnos=(TurnoNuvem(uid="u1", ts=datetime.now(UTC), dispositivo="cel",
                                            texto_usuario="oi", texto_resposta="olá"),))
    r = await no.resumo(Envelope(t=Tipo.RESUMO_NUVEM, corpo=resumo, de="ayanami", para="pc"))
    assert r == Ack(ids=())
    await no.aclose()
    await service.stop()


def _core() -> Core:
    return Core(deps=TurnDeps(), budget=SwitchBudget(NullBudget(5.0)))


def test_sem_secao_ayanami_nada_muda(monkeypatch: pytest.MonkeyPatch) -> None:
    def nunca() -> str:
        raise AssertionError("não deveria ler token")

    monkeypatch.setattr(pc_mod, "token_pc", nunca)
    core = _core()
    _wire_ayanami(core, parse_config({}))
    assert core.ayanami is None and core.warnings == []
    assert core.deps.on_turn_done is None


def test_com_ayanami_sem_token_avisa_e_segue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc_mod, "token_pc", lambda: None)
    core = _core()
    _wire_ayanami(core, parse_config({"ayanami": {"url": "https://ayanami.exemplo.ts.net/"}}))
    assert core.ayanami is None
    assert any("sem token" in w for w in core.warnings)


def test_com_ayanami_e_token_monta_o_nopc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc_mod, "token_pc", lambda: "ayn_pc_falso")
    core = _core()
    _wire_ayanami(core, parse_config({"ayanami": {"url": "https://ayanami.exemplo.ts.net/"}}))
    assert isinstance(core.ayanami, NoPc)
    assert core.ayanami.cliente.base_url == "https://ayanami.exemplo.ts.net"
    assert core.ayanami.cliente.nome == "pc"
    assert not any("ayn_pc_falso" in w for w in core.warnings)
