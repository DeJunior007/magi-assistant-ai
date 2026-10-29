"""Turno com Ogg Opus e SSE ``turno.ouvido`` (M1.2; condessa-celular spec §9.4, §9.5; CA-M32, CA-M33).

Sem rede, sem ``ffmpeg`` e sem banco: a rota roda numa app FastAPI mínima com o ``router`` do turno
e o dispositivo injetado; hub de verdade com canais falsos; conversor/STT falsos; relógio falso.
A fixture ``fixtures/turno.ogg`` (seno de 0,5 s) foi gerada uma vez pelo ``ffmpeg``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ayanami.api import auth
from ayanami.api.auth import Dispositivo, ErroApi
from ayanami.api.turno import MIME_AUDIO, router
from ayanami.hub import Hub
from ayanami.relogio import RelogioFalso
from ayanami.turnos import WEBM_PARA_PCM, AudioInvalido, FfmpegConversor, Turnos
from magi.elo.mensagens import (
    MAX_TURNO_FIM_OUVIDO,
    EloError,
    Envelope,
    Ola,
    Tipo,
    TipoDispositivo,
    TurnoFim,
    decode,
    encode,
)

OGG = (Path(__file__).parent / "fixtures" / "turno.ogg").read_bytes()
PC = Dispositivo(1, "pc-pedro", "pc", frozenset({"conversa"}))
CEL = Dispositivo(2, "celular-pedro", "celular", frozenset({"conversa"}))


class Relogio(RelogioFalso):
    async def dormir(self, segundos: float) -> None:
        await asyncio.Event().wait()


class DbNada:
    @contextmanager
    def connection(self):  # noqa: ANN201
        raise RuntimeError("sem banco neste teste")
        yield  # pragma: no cover


@dataclass
class CanalFalso:
    textos: list[str] = field(default_factory=list)
    binarios: list[bytes] = field(default_factory=list)

    async def enviar(self, texto: str) -> None:
        self.textos.append(texto)

    async def enviar_bytes(self, dados: bytes) -> None:
        self.binarios.append(dados)

    async def fechar(self, codigo: int) -> None:
        pass

    def envelopes(self, t: Tipo) -> list[Envelope]:
        return [e for e in map(decode, self.textos) if e.t is t]


@dataclass
class CanalLongPoll:
    """Sem ``enviar_bytes``: o turno de áudio passa pelo STT da nuvem e vai ao PC como texto."""

    textos: list[str] = field(default_factory=list)

    async def enviar(self, texto: str) -> None:
        self.textos.append(texto)

    async def fechar(self, codigo: int) -> None:
        pass

    def envelopes(self, t: Tipo) -> list[Envelope]:
        return [e for e in map(decode, self.textos) if e.t is t]


class ConversorFalso:
    def __init__(self) -> None:
        self.recebidos: list[bytes] = []

    async def audio_para_pcm(self, audio: bytes) -> bytes:
        self.recebidos.append(audio)
        return b"\x01\x00" * 1600

    async def ogg_de(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        yield b"OggS"
        async for b in pcm:
            yield b


class ConversorAntigo:
    """Conversor de antes da M1.2 (só ``webm_para_pcm``): segue valendo."""

    def __init__(self) -> None:
        self.recebidos: list[bytes] = []

    async def webm_para_pcm(self, webm: bytes) -> bytes:
        self.recebidos.append(webm)
        return b"\x00\x00" * 160

    async def ogg_de(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        yield b"OggS"


class EscutaFalsa:
    def __init__(self, texto: str = "que horas são") -> None:
        self.texto = texto
        self.pedidos: list[tuple[bytes, str]] = []

    async def transcrever(self, audio: bytes, mime: str) -> str:
        self.pedidos.append((audio, mime))
        return self.texto


@dataclass
class Sse:
    itens: list[tuple[Any, str, Any]] = field(default_factory=list)

    def __call__(self, alvo: Any, nome: str, corpo: Any, **_: Any) -> int:
        self.itens.append((alvo, nome, corpo))
        return 1

    def nomes(self) -> list[str]:
        return [n for _, n, _ in self.itens]


async def _atender(texto: str, dispositivo: str, deps: Any, *, turno: str) -> TurnoFim:
    return TurnoFim(turno=turno, ok=True, texto=f"eco: {texto}", fala="")


async def _ate(cond: Any, n: int = 400) -> None:
    for _ in range(n):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condição não chegou")


def _servico(tmp_path: Any, **kw: Any) -> tuple[Turnos, Hub, Sse, Relogio]:
    rel = Relogio()
    hub = Hub(DbNada(), rel, offline_apos_s=30.0)
    sse = Sse()
    kw.setdefault("conversor", ConversorFalso())
    kw.setdefault("escuta", EscutaFalsa())
    svc = Turnos(hub, rel, publicar=sse, dir_audio=tmp_path, atender=_atender, nuvem=object(), **kw)
    return svc, hub, sse, rel


async def _pc_online(hub: Hub, canal: Any) -> Any:
    no = await hub.registrar(PC, canal, "ws")
    ola = Envelope(Tipo.OLA, Ola(tipo=TipoDispositivo.PC, versao="0.0.0"), "pc-pedro", "ayanami")
    await hub.receber(no, encode(ola))
    canal.textos.clear()
    return no


async def _fim_do_pc(hub: Hub, no: Any, fim: TurnoFim) -> None:
    await hub.receber(no, encode(Envelope(Tipo.TURNO_FIM, fim, "pc-pedro", "ayanami")))


# --------------------------------------------------------------------------- CA-M32 (rota)


class _Limites:
    def por_dispositivo(self, request: Any, disp: Any) -> None:
        pass


class _Ctx:
    def __init__(self, svc: Turnos) -> None:
        self.extras: dict[str, Any] = {"turnos": svc}
        self.limites = _Limites()


@pytest.fixture(autouse=True)
def _sem_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """O token é da M1.1/Y-auth (testado com ``pg``); aqui o dispositivo é o celular fixo."""
    monkeypatch.setattr(auth, "autenticar", lambda request: CEL)
    monkeypatch.setattr(auth, "checar", lambda disp, exig: None)


def _app(svc: Turnos) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.ctx = _Ctx(svc)

    @app.exception_handler(ErroApi)
    async def _erro(_: Request, e: ErroApi) -> JSONResponse:
        return JSONResponse({"erro": e.codigo, "msg": e.msg}, status_code=e.status)

    return app


def _cliente(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste")


def test_fixture_e_ogg_opus_pequeno() -> None:
    assert OGG[:4] == b"OggS" and b"OpusHead" in OGG and len(OGG) <= 4096


async def test_post_ogg_opus_202_e_conversor_recebe_os_bytes(tmp_path) -> None:
    conv, escuta = ConversorFalso(), EscutaFalsa()
    svc, _, sse, _ = _servico(tmp_path, conversor=conv, escuta=escuta)
    async with _cliente(_app(svc)) as c:
        r = await c.post("/v1/turno", files={"audio": ("fala.ogg", OGG, "audio/ogg;codecs=opus")})
        assert r.status_code == 202 and r.json()["modo"] == "nuvem"
        tid = r.json()["turno"]
        await _ate(lambda: svc._turnos[tid].audio.fechado)  # noqa: SLF001
    assert conv.recebidos == [OGG]
    assert escuta.pedidos == [(OGG, "audio/ogg;codecs=opus")]  # o mime segue até o STT da nuvem
    assert sse.nomes() == ["turno.ouvido", "turno.texto", "turno.fim"]


async def test_post_mp4_415_e_webm_continua(tmp_path) -> None:
    conv = ConversorFalso()
    svc, *_ = _servico(tmp_path, conversor=conv)
    async with _cliente(_app(svc)) as c:
        r = await c.post("/v1/turno", files={"audio": ("fala.m4a", b"....ftyp", "audio/mp4")})
        assert r.status_code == 415 and r.json()["erro"] == "tipo_nao_suportado"
        assert "audio/ogg" in r.json()["msg"]
        r = await c.post("/v1/turno", files={"audio": ("a.webm", b"webm", "audio/webm;codecs=opus")})
        assert r.status_code == 202
        r = await c.post("/v1/turno", content=json.dumps({"texto": "oi"}),
                         headers={"content-type": "application/json"})
        assert r.status_code == 202
    assert conv.recebidos == [b"webm"]
    assert {"audio/webm", "audio/ogg"} == set(MIME_AUDIO)


# --------------------------------------------------------------------------- conversor


class ProcFalso:
    def __init__(self, saida: bytes) -> None:
        self.saida, self.returncode, self.entrada = saida, 0, b""

    async def communicate(self, dados: bytes) -> tuple[bytes, bytes]:
        self.entrada = dados
        return self.saida, b""


async def test_audio_para_pcm_e_alias_webm_para_pcm() -> None:
    chamadas: list[tuple[Any, ...]] = []
    procs: list[ProcFalso] = []

    async def criar(*args: Any, **_: Any) -> ProcFalso:
        chamadas.append(args)
        procs.append(ProcFalso(b"pcm"))
        return procs[-1]

    conv = FfmpegConversor(criar)
    assert await conv.audio_para_pcm(OGG) == b"pcm"
    assert await conv.webm_para_pcm(b"w") == b"pcm"
    assert chamadas == [WEBM_PARA_PCM, WEBM_PARA_PCM]  # "-i pipe:0": o ffmpeg detecta o contêiner
    assert procs[0].entrada == OGG
    assert FfmpegConversor.webm_para_pcm is FfmpegConversor.audio_para_pcm


async def test_conversor_antigo_so_com_webm_para_pcm(tmp_path) -> None:
    conv = ConversorAntigo()
    svc, *_ = _servico(tmp_path, conversor=conv)
    assert await svc.preparar_audio(OGG) == b"\x00\x00" * 160
    assert conv.recebidos == [OGG]


async def test_falha_do_conversor_segue_audio_invalido(tmp_path) -> None:
    class Quebrado(ConversorFalso):
        async def audio_para_pcm(self, audio: bytes) -> bytes:
            raise AudioInvalido("x")

    svc, *_ = _servico(tmp_path, conversor=Quebrado())
    async with _cliente(_app(svc)) as c:
        r = await c.post("/v1/turno", files={"audio": ("f.ogg", OGG, "audio/ogg")})
    assert r.status_code == 415 and r.json()["erro"] == "audio_invalido"


# --------------------------------------------------------------------------- CA-M33 (turno.ouvido)


async def test_nuvem_publica_ouvido_antes_do_texto(tmp_path) -> None:
    svc, _, sse, _ = _servico(tmp_path)
    t = await svc.iniciar(CEL, webm=OGG, pcm=await svc.preparar_audio(OGG), mime="audio/ogg")
    await _ate(lambda: t.audio.fechado)
    assert sse.nomes() == ["turno.ouvido", "turno.texto", "turno.fim"]
    assert sse.itens[0] == (CEL.id, "turno.ouvido", {"turno": t.id, "texto": "que horas são"})


async def test_nuvem_texto_vazio_do_stt_nao_publica(tmp_path) -> None:
    svc, _, sse, _ = _servico(tmp_path, escuta=EscutaFalsa("  "))
    t = await svc.iniciar(CEL, webm=OGG, pcm=await svc.preparar_audio(OGG), mime="audio/ogg")
    await _ate(lambda: t.audio.fechado)
    assert "turno.ouvido" not in sse.nomes()


async def test_turno_de_texto_nao_publica_ouvido(tmp_path) -> None:
    svc, hub, sse, _ = _servico(tmp_path)
    t = await svc.iniciar(CEL, texto="oi")
    await _ate(lambda: t.audio.fechado)
    canal = CanalFalso()
    no = await _pc_online(hub, canal)
    t2 = await svc.iniciar(CEL, texto="liga a TV")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    await _fim_do_pc(hub, no, TurnoFim(turno=t2.id, ok=True, texto="Ligada.", fala=""))
    await _ate(lambda: t2.fim is not None)
    assert t.modo == "nuvem" and t2.modo == "pc"
    assert "turno.ouvido" not in sse.nomes()


async def test_pc_com_ouvido_publica_antes_do_texto(tmp_path) -> None:
    svc, hub, sse, _ = _servico(tmp_path)
    canal = CanalFalso()
    no = await _pc_online(hub, canal)
    t = await svc.iniciar(CEL, webm=OGG, pcm=await svc.preparar_audio(OGG), mime="audio/ogg")
    await _ate(lambda: canal.envelopes(Tipo.TURNO) and canal.binarios)
    assert canal.envelopes(Tipo.TURNO)[0].corpo.audio  # áudio vai ao PC (STT local), sem STT da nuvem
    assert sse.nomes() == []
    await _fim_do_pc(hub, no, TurnoFim(turno=t.id, ok=True, texto="Meio-dia.", fala="",
                                       ouvido="que horas são"))
    await _ate(lambda: t.fim is not None)
    assert sse.nomes() == ["turno.ouvido", "turno.texto", "turno.fim"]
    assert sse.itens[0][2] == {"turno": t.id, "texto": "que horas são"}
    assert sse.itens[2][2].ouvido == "que horas são"


async def test_pc_antigo_sem_ouvido_nao_publica(tmp_path) -> None:
    svc, hub, sse, _ = _servico(tmp_path)
    canal = CanalFalso()
    no = await _pc_online(hub, canal)
    t = await svc.iniciar(CEL, webm=OGG, pcm=await svc.preparar_audio(OGG), mime="audio/ogg")
    await _ate(lambda: canal.binarios)
    env = Envelope(Tipo.TURNO_FIM, TurnoFim(turno=t.id, ok=True, texto="Ok.", fala=""), "pc-pedro", "ayanami")
    cru = json.loads(encode(env))
    del cru["corpo"]["ouvido"]  # PC de antes da M1.2
    await hub.receber(no, json.dumps(cru))
    await _ate(lambda: t.fim is not None)
    assert t.fim.ouvido == "" and sse.nomes() == ["turno.texto", "turno.fim"]


async def test_pc_long_poll_publica_ouvido_depois_do_stt_da_nuvem(tmp_path) -> None:
    escuta = EscutaFalsa()
    svc, hub, sse, _ = _servico(tmp_path, escuta=escuta)
    canal = CanalLongPoll()
    no = await _pc_online(hub, canal)
    t = await svc.iniciar(CEL, webm=OGG, pcm=await svc.preparar_audio(OGG), mime="audio/ogg")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    assert canal.envelopes(Tipo.TURNO)[0].corpo.texto == "que horas são"
    assert escuta.pedidos == [(OGG, "audio/ogg")]
    assert sse.nomes() == ["turno.ouvido"]
    # o PC recebeu texto: devolve ouvido vazio; mesmo se viesse, não repete
    await _fim_do_pc(hub, no, TurnoFim(turno=t.id, ok=True, texto="Meio-dia.", fala="",
                                       ouvido="que horas são"))
    await _ate(lambda: t.fim is not None)
    assert sse.nomes() == ["turno.ouvido", "turno.texto", "turno.fim"]


# --------------------------------------------------------------------------- elo


def test_turno_fim_ouvido_no_elo() -> None:
    fim = TurnoFim(turno="01J00000000000000000000000", ok=True, ouvido="oi")
    env = Envelope(Tipo.TURNO_FIM, fim, "pc-pedro", "ayanami")
    assert decode(encode(env)).corpo.ouvido == "oi"
    cru = json.loads(encode(env))
    del cru["corpo"]["ouvido"]
    assert decode(json.dumps(cru)).corpo.ouvido == ""
    longo = TurnoFim(turno=fim.turno, ok=True, ouvido="a" * (MAX_TURNO_FIM_OUVIDO + 1))
    with pytest.raises(EloError):
        Envelope(Tipo.TURNO_FIM, longo, "pc-pedro", "ayanami")
