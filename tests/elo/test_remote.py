"""``RemoteLink`` (Y6.2): AUDIO_IN → ``entrada`` (fila ≤ 400), ``play`` → AUDIO_OUT 24 kHz +
AUDIO_FIM + ``PlaybackDone`` injetado, ``StopPlayback`` → AUDIO_FIM. Sem rede: cliente falso."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np

from magi.common.contracts import ListenRequest, PcmFormat, PlaybackDone, StopPlayback
from magi.elo.cliente import ConexaoFechada
from magi.elo.ids import novo_id
from magi.elo.quadros import Quadro, QuadroTipo
from magi.elo.remote import MAX_QUADROS_ENTRADA, SAIDA_FMT, Reamostrador, RemoteLink


class ClienteFalso:
    def __init__(self, *, fechado: bool = False) -> None:
        self.quadros: list[Quadro] = []
        self.fechado = fechado

    async def enviar_quadro(self, q: Quadro) -> None:
        if self.fechado:
            raise ConexaoFechada
        self.quadros.append(q)


class MaquinaFalsa:
    def __init__(self) -> None:
        self.msgs: list[object] = []

    async def handle(self, msg: object) -> None:
        self.msgs.append(msg)


async def _blocos(*bs: bytes) -> AsyncIterator[bytes]:
    for b in bs:
        yield b


def _tipos(c: ClienteFalso) -> list[QuadroTipo]:
    return [q.tipo for q in c.quadros]


def test_hello_do_celular() -> None:
    link = RemoteLink(ClienteFalso())
    assert link.hello.satellite == "celular"
    assert link.hello.capabilities == ("ptt", "playback")


async def test_entrada_ate_audio_fim_e_ignora_outro_turno() -> None:
    t = novo_id()
    link = RemoteLink(ClienteFalso(), t)
    link.receber_quadro(Quadro(QuadroTipo.AUDIO_IN, t, b"\x01\x00" * 4))
    link.receber_quadro(Quadro(QuadroTipo.AUDIO_IN, novo_id(), b"\x09\x00"))  # outro turno
    link.receber_quadro(Quadro(QuadroTipo.AUDIO_IN, t, b"\x02\x00"))
    link.receber_quadro(Quadro(QuadroTipo.AUDIO_FIM, t))
    assert [p async for p in link.entrada()] == [b"\x01\x00" * 4, b"\x02\x00"]


async def test_fila_de_entrada_limitada_a_400_quadros() -> None:
    t = novo_id()
    link = RemoteLink(ClienteFalso(), t)
    for _ in range(MAX_QUADROS_ENTRADA + 25):
        link.receber_quadro(Quadro(QuadroTipo.AUDIO_IN, t, b"\x00\x00"))
    link.receber_quadro(Quadro(QuadroTipo.AUDIO_FIM, t))
    assert len([p async for p in link.entrada()]) == MAX_QUADROS_ENTRADA


async def test_play_24k_em_quadros_de_80ms_fim_e_playback_done() -> None:
    t = novo_id()
    c = ClienteFalso()
    link = RemoteLink(c, t)
    link.machine = m = MaquinaFalsa()
    um_s = bytes(SAIDA_FMT.bytes_for_ms(1000))
    await link.play(_blocos(um_s[:1000], um_s[1000:]), SAIDA_FMT)
    await asyncio.sleep(0)
    assert _tipos(c) == [QuadroTipo.AUDIO_OUT] * 13 + [QuadroTipo.AUDIO_FIM]
    assert sum(len(q.pcm) for q in c.quadros) == len(um_s)
    assert all(q.turno == t for q in c.quadros)
    assert link.quadros_out == 13
    assert m.msgs == [PlaybackDone("celular")]


async def test_play_reamostra_16k_para_24k() -> None:
    c = ClienteFalso()
    link = RemoteLink(c, novo_id())
    f16 = PcmFormat(rate=16000, width=2, channels=1)
    await link.play(_blocos(bytes(f16.bytes_for_ms(500))), f16)
    total = sum(len(q.pcm) for q in c.quadros)
    assert abs(total - SAIDA_FMT.bytes_for_ms(500)) <= 4


def test_reamostrador_por_blocos_igual_ao_inteiro() -> None:
    f = PcmFormat(rate=22050, width=2, channels=1)
    x = (8000 * np.sin(np.arange(22050) * 2 * np.pi * 440 / 22050)).astype("<i2").tobytes()
    inteiro = Reamostrador(f)(x)
    r = Reamostrador(f)
    por_blocos = b"".join(r(x[i : i + 333]) for i in range(0, len(x), 333))  # blocos ímpares
    a, b = np.frombuffer(por_blocos, "<i2"), np.frombuffer(inteiro, "<i2")
    assert len(a) == len(b) and int(np.abs(a.astype(int) - b).max()) <= 1  # sem emenda
    assert abs(len(inteiro) // 2 - 24000) <= 2


def test_reamostrador_estereo_vira_mono() -> None:
    f = PcmFormat(rate=24000, width=2, channels=2)
    par = np.array([100, 300] * 10, dtype="<i2").tobytes()
    out = np.frombuffer(Reamostrador(f)(par), dtype="<i2")
    assert len(out) >= 9 and set(out.tolist()) == {200}


async def test_stop_playback_manda_fim_e_listen_request_ignorado() -> None:
    c = ClienteFalso()
    link = RemoteLink(c, novo_id())
    await link.send(ListenRequest(timeout_ms=8000, reason="confirm"))
    await link.send(StopPlayback())
    assert _tipos(c) == [QuadroTipo.AUDIO_FIM]


async def test_sem_turno_nada_vai_ao_celular_mas_playback_done_sai() -> None:
    c = ClienteFalso()
    link = RemoteLink(c)
    link.machine = m = MaquinaFalsa()
    await link.play(_blocos(bytes(3840)), SAIDA_FMT)
    await asyncio.sleep(0)
    assert c.quadros == [] and m.msgs == [PlaybackDone("celular")]


async def test_ws_fora_nao_derruba_o_play() -> None:
    link = RemoteLink(ClienteFalso(fechado=True), novo_id())
    link.machine = m = MaquinaFalsa()
    await link.play(_blocos(bytes(3840)), SAIDA_FMT)
    await asyncio.sleep(0)
    assert link.quadros_out == 0 and m.msgs == [PlaybackDone("celular")]
