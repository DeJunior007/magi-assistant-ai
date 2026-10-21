"""Rota do turno (Y6.4; spec §2.2 ``/v1/turno*``, §6.1, §6.2; CA-Y20).

Sem rede, sem ``ffmpeg`` e sem LLM: hub de verdade com canais falsos, conversor/STT/TTS falsos,
relógio falso (o ``dormir`` não anda o relógio: a varredura do hub fica parada). Os testes de
rota usam o ``ayanami-pg-teste`` (``pg``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from ayanami.api.auth import Dispositivo
from ayanami.hub import Hub, hub_de
from ayanami.nuvem import NuvemDeps, atender, carregar_frases
from ayanami.nuvem_tools import PortaTarefas
from ayanami.relogio import RelogioFalso
from ayanami.turnos import (
    WEBM_PARA_PCM,
    AudioExpirado,
    AudioInvalido,
    AudioLongo,
    FfmpegConversor,
    Turnos,
)
from ayanami.voz_nuvem import FalaNuvem
from magi.common.contracts import BudgetExceeded
from magi.elo.mensagens import Envelope, Ola, Tipo, TipoDispositivo, TurnoFim, decode, encode
from magi.elo.quadros import Quadro, QuadroTipo, decode_quadro, encode_quadro

FRASES = carregar_frases()
PC = Dispositivo(1, "pc-pedro", "pc", frozenset({"conversa"}))
CEL = Dispositivo(2, "celular-pedro", "celular", frozenset({"conversa"}))
OUTRO = Dispositivo(3, "celular-ana", "celular", frozenset({"conversa"}))


class Relogio(RelogioFalso):
    """``dormir`` não anda o relógio (só ``avancar`` anda)."""

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
    fechado_com: int | None = None

    async def enviar(self, texto: str) -> None:
        self.textos.append(texto)

    async def enviar_bytes(self, dados: bytes) -> None:
        self.binarios.append(dados)

    async def fechar(self, codigo: int) -> None:
        self.fechado_com = codigo

    def envelopes(self, t: Tipo) -> list[Envelope]:
        return [e for e in map(decode, self.textos) if e.t is t]


class ConversorFalso:
    def __init__(self, pcm: bytes = b"\x01\x00" * 16000, falha: bool = False) -> None:
        self.pcm, self.falha, self.webms = pcm, falha, []

    async def webm_para_pcm(self, webm: bytes) -> bytes:
        self.webms.append(webm)
        if self.falha:
            raise AudioInvalido("x")
        return self.pcm

    async def ogg_de(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        yield b"OggS"
        async for b in pcm:
            yield b"<" + b + b">"


class EscutaFalsa:
    async def transcrever(self, audio: bytes, mime: str) -> str:
        return "que horas são"


class OpusFalso:
    formato = "opus"

    def __init__(self) -> None:
        self.chamadas = 0

    async def sintetizar(self, texto: str) -> bytes:
        self.chamadas += 1
        return b"OggS:" + texto.encode()


@dataclass
class Sse:
    itens: list[tuple[Any, str, Any]] = field(default_factory=list)

    def __call__(self, alvo: Any, nome: str, corpo: Any, **_: Any) -> int:
        self.itens.append((alvo, nome, corpo))
        return 1


async def _pc_online(hub: Hub, relogio: Relogio) -> tuple[Any, CanalFalso]:
    canal = CanalFalso()
    no = await hub.registrar(PC, canal, "ws")
    ola = Envelope(Tipo.OLA, Ola(tipo=TipoDispositivo.PC, versao="0.0.0"), "pc-pedro", "ayanami")
    await hub.receber(no, encode(ola))
    canal.textos.clear()
    return no, canal


async def _ate(cond: Any, n: int = 400) -> None:
    for _ in range(n):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condição não chegou")


def _servico(relogio: Relogio, tmp_path: Any, **kw: Any) -> tuple[Turnos, Hub, Sse]:
    hub = Hub(DbNada(), relogio, offline_apos_s=30.0)
    sse = Sse()
    kw.setdefault("conversor", ConversorFalso())
    svc = Turnos(hub, relogio, publicar=sse, dir_audio=tmp_path, **kw)
    return svc, hub, sse


async def _fim_do_pc(hub: Hub, no: Any, fim: TurnoFim) -> list[str]:
    respostas, _ = await hub.receber(no, encode(Envelope(Tipo.TURNO_FIM, fim, "pc-pedro", "ayanami")))
    return respostas


# --------------------------------------------------------------------------- §6.1 (CA-Y20)


async def test_matriz_29_s_pc_31_s_nuvem(tmp_path) -> None:
    rel = Relogio()
    svc, hub, _ = _servico(rel, tmp_path)
    assert svc.modo() == "nuvem"
    await _pc_online(hub, rel)
    rel.avancar(29)
    assert svc.modo() == "pc"
    rel.avancar(2)
    assert svc.modo() == "nuvem"


async def test_modo_fica_fixo_no_turno(tmp_path) -> None:
    rel = Relogio()
    svc, hub, _ = _servico(rel, tmp_path)
    no, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, texto="oi")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    rel.avancar(31)  # o pc "some" do online, mas o turno segue pc
    assert svc.modo() == "nuvem" and t.modo == "pc"
    await _fim_do_pc(hub, no, TurnoFim(turno=t.id, ok=True, texto="Oi!", fala=""))
    await _ate(lambda: t.fim is not None)
    assert t.fim.ok and t.modo == "pc"


# --------------------------------------------------------------------------- modo pc


async def test_pc_texto_vai_ao_pc_e_fim_vai_ao_sse(tmp_path) -> None:
    rel = Relogio()
    svc, hub, sse = _servico(rel, tmp_path)
    no, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, texto="liga a TV")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    env = canal.envelopes(Tipo.TURNO)[0]
    assert env.para == "pc-pedro" and env.corpo.turno == t.id
    assert env.corpo.texto == "liga a TV" and not env.corpo.audio and env.corpo.dispositivo == "celular-pedro"
    assert canal.binarios == []
    respostas = await _fim_do_pc(hub, no, TurnoFim(turno=t.id, ok=True, texto="Ligada.", fala=""))
    assert decode(respostas[0]).t is Tipo.ACK
    await _ate(lambda: t.audio.fechado)
    assert [(a, n) for a, n, _ in sse.itens] == [(CEL.id, "turno.texto"), (CEL.id, "turno.fim")]
    assert sse.itens[0][2] == {"turno": t.id, "texto": "Ligada."}
    assert t.para_json()["estado"] == "fim" and t.para_json()["fim"]["texto"] == "Ligada."


async def test_pc_audio_em_quadros_de_80ms_e_fala_volta_em_ogg(tmp_path) -> None:
    rel = Relogio()
    pcm = bytes(range(256)) * 35  # 8960 bytes = 3 quadros cheios + 1 parcial
    svc, hub, _ = _servico(rel, tmp_path, conversor=ConversorFalso(pcm))
    no, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, webm=b"webm", pcm=await svc.preparar_audio(b"webm"))
    await _ate(lambda: len(canal.binarios) == 5)
    turno = canal.envelopes(Tipo.TURNO)[0].corpo
    assert turno.audio and turno.texto is None
    quadros = [decode_quadro(b) for b in canal.binarios]
    assert [q.tipo for q in quadros] == [QuadroTipo.AUDIO_IN] * 4 + [QuadroTipo.AUDIO_FIM]
    assert [len(q.pcm) for q in quadros] == [2560, 2560, 2560, 1280, 0]
    assert b"".join(q.pcm for q in quadros) == pcm and {q.turno for q in quadros} == {t.id}
    # o TurnoFim sai antes da fala (Y6.2); o áudio vem depois e o AUDIO_FIM fecha
    await _fim_do_pc(hub, no, TurnoFim(turno=t.id, ok=True, texto="Feito.", fala="Feito."))
    await _ate(lambda: t.fim is not None)
    assert t.fim.audio  # o PWA sabe que vale pedir o áudio
    fluxo = svc.audio(t.id, CEL)
    lido = asyncio.ensure_future(_ler(fluxo))
    for parte in (b"ab", b"cd"):
        await svc.receber_quadro(encode_quadro(Quadro(QuadroTipo.AUDIO_OUT, t.id, parte)), PC)
    await svc.receber_quadro(encode_quadro(Quadro(QuadroTipo.AUDIO_FIM, t.id)), PC)
    assert await asyncio.wait_for(lido, 2) == b"OggS<ab><cd>"
    assert t.audio.fechado


async def _ler(fluxo: AsyncIterator[bytes]) -> bytes:
    return b"".join([b async for b in fluxo])


async def test_pc_caiu_no_meio_fecha_sem_refazer(tmp_path) -> None:
    rel = Relogio()
    svc, hub, sse = _servico(rel, tmp_path)
    no, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, texto="pesquisa algo")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    hub.remover(no)  # a WS do PC caiu
    await _ate(lambda: t.fim is not None)
    assert t.fim.erro == "pc_caiu" and not t.fim.ok and t.fim.texto == FRASES["pc_caiu"]
    assert not t.fim.audio
    # o PC volta e manda a resposta atrasada: ignorada; nada foi reenviado
    no2, canal2 = await _pc_online(hub, rel)
    await _fim_do_pc(hub, no2, TurnoFim(turno=t.id, ok=True, texto="tarde"))
    assert t.fim.erro == "pc_caiu" and canal2.envelopes(Tipo.TURNO) == []
    assert len(canal.envelopes(Tipo.TURNO)) == 1
    assert [n for _, n, _ in sse.itens] == ["turno.texto", "turno.fim"]


async def test_pc_trocou_de_conexao_tambem_e_pc_caiu(tmp_path) -> None:
    rel = Relogio()
    svc, hub, _ = _servico(rel, tmp_path)
    _, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, texto="oi")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    await _pc_online(hub, rel)  # nova conexão do mesmo PC fecha a antiga com 4002
    await _ate(lambda: t.fim is not None)
    assert t.fim.erro == "pc_caiu" and canal.fechado_com == 4002


async def test_pc_sem_resposta_da_tempo(tmp_path) -> None:
    rel = Relogio()
    svc, hub, _ = _servico(rel, tmp_path)
    _, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, texto="oi")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    await asyncio.sleep(0.02)
    assert t.fim is None
    rel.avancar(51)
    await _ate(lambda: t.fim is not None)
    assert t.fim.erro == "tempo"


async def test_turno_fim_de_quem_nao_e_pc_e_ignorado(tmp_path) -> None:
    rel = Relogio()
    svc, hub, _ = _servico(rel, tmp_path)
    _, canal = await _pc_online(hub, rel)
    t = await svc.iniciar(CEL, texto="oi")
    await _ate(lambda: canal.envelopes(Tipo.TURNO))
    casa = Dispositivo(9, "casa", "casa", frozenset())
    env = Envelope(Tipo.TURNO_FIM, TurnoFim(turno=t.id, ok=True, texto="x"), "casa", "ayanami")
    svc.ao_turno_fim(casa, env)
    await svc.receber_quadro(encode_quadro(Quadro(QuadroTipo.AUDIO_OUT, t.id, b"zz")), casa)
    assert t.fim is None and t.ogg is None


# --------------------------------------------------------------------------- modo nuvem


async def test_nuvem_audio_stt_atender_tts_e_some_em_60_s(tmp_path) -> None:
    rel = Relogio()
    pedidos: list[tuple[str, str, str]] = []

    async def atender_falso(texto: str, dispositivo: str, deps: Any, *, turno: str) -> TurnoFim:
        pedidos.append((texto, dispositivo, turno))
        return TurnoFim(turno=turno, ok=True, texto="Sao 12h.", fala="Sao 12h.")

    fala = FalaNuvem(OpusFalso(), None, rel)
    svc, _, sse = _servico(rel, tmp_path, atender=atender_falso, nuvem=object(),
                           escuta=EscutaFalsa(), fala=fala)
    t = await svc.iniciar(CEL, webm=b"webm", pcm=await svc.preparar_audio(b"webm"))
    assert t.modo == "nuvem"
    await _ate(lambda: t.audio.fechado)
    assert pedidos == [("que horas são", "celular-pedro", t.id)]
    assert t.fim.audio and sse.itens[-1][1] == "turno.fim"
    assert await _ler(svc.audio(t.id, CEL)) == b"OggS:Sao 12h."
    arquivo = tmp_path / f"{t.id}.ogg"
    assert arquivo.exists()
    rel.avancar(59)
    assert await _ler(svc.audio(t.id, CEL)) == b"OggS:Sao 12h."
    rel.avancar(2)
    with pytest.raises(AudioExpirado):
        svc.audio(t.id, CEL)
    assert not arquivo.exists()
    assert svc.obter(t.id, CEL) is not None  # o registro fica; só o áudio some


async def test_nuvem_kokoro_pcm_vira_ogg(tmp_path) -> None:
    rel = Relogio()

    class Kokoro:
        formato = "pcm16"

        async def sintetizar(self, texto: str) -> bytes:
            return b"pcm"

    async def atender_falso(texto: str, dispositivo: str, deps: Any, *, turno: str) -> TurnoFim:
        return TurnoFim(turno=turno, ok=True, texto="Oi.", fala="Oi.")

    svc, _, _ = _servico(rel, tmp_path, atender=atender_falso, nuvem=object(),
                         fala=FalaNuvem(None, Kokoro(), rel))
    t = await svc.iniciar(CEL, texto="oi")
    await _ate(lambda: t.audio.fechado)
    assert await _ler(svc.audio(t.id, CEL)) == b"OggS<pcm>"


class BudgetBloqueado:
    async def ensure_allowed(self, task: Any) -> None:
        raise BudgetExceeded("teto")

    async def gasto(self) -> Any:
        return self


@dataclass
class TurnosNuvemFalsos:
    linhas: list[Any] = field(default_factory=list)

    async def ultimos(self, dispositivo: str, n: int) -> list[tuple[str, str]]:
        return []

    async def gravar(self, dispositivo: str, usuario: str, resposta: str, ferramentas: Any) -> None:
        self.linhas.append((dispositivo, usuario, resposta))

    async def id_de(self, dispositivo: str) -> int | None:
        return CEL.id


async def test_nuvem_casa_offline_frase_em_cache(tmp_path) -> None:
    """CA-Y20 (parte nuvem): PC e casa fora → ``atender`` de verdade dá ``casa_offline`` e a fala
    sai do cache da ``FalaNuvem`` (sem nova síntese)."""
    rel = Relogio()

    async def nada(*_: Any) -> Any:
        return []

    hub = Hub(DbNada(), rel)
    tts = OpusFalso()
    fala = FalaNuvem(tts, None, rel)
    await fala.aquecer(FRASES.values())
    antes = tts.chamadas
    deps = NuvemDeps(hub=hub, budget=BudgetBloqueado(), turnos=TurnosNuvemFalsos(),
                     tarefas=PortaTarefas(nada, nada, nada), noticias=nada, relogio=rel)
    svc = Turnos(hub, rel, publicar=Sse(), conversor=ConversorFalso(), nuvem=deps,
                 atender=atender, fala=fala, dir_audio=tmp_path)
    t = await svc.iniciar(CEL, texto="liga a TV da sala")
    await _ate(lambda: t.audio.fechado)
    assert t.modo == "nuvem" and t.fim.fala == FRASES["casa_offline"]
    assert tts.chamadas == antes
    assert await _ler(svc.audio(t.id, CEL)) == b"OggS:" + FRASES["casa_offline"].encode()


# --------------------------------------------------------------------------- dono, áudio, ffmpeg


async def test_outro_dispositivo_nao_ve_o_turno(tmp_path) -> None:
    rel = Relogio()

    async def atender_falso(texto: str, dispositivo: str, deps: Any, *, turno: str) -> TurnoFim:
        return TurnoFim(turno=turno, ok=True, texto="ok")

    svc, _, _ = _servico(rel, tmp_path, atender=atender_falso, nuvem=object())
    t = await svc.iniciar(CEL, texto="oi")
    assert svc.obter(t.id, OUTRO) is None and svc.audio(t.id, OUTRO) is None
    assert svc.obter(t.id, CEL) is t


async def test_preparar_audio_limites(tmp_path) -> None:
    rel = Relogio()
    svc, _, _ = _servico(rel, tmp_path, conversor=ConversorFalso(b"\x00" * (15 * 32000)))
    assert len(await svc.preparar_audio(b"w")) == 15 * 32000
    svc.conversor = ConversorFalso(b"\x00" * (15 * 32000 + 2))
    with pytest.raises(AudioLongo):
        await svc.preparar_audio(b"w")
    with pytest.raises(AudioLongo):
        await svc.preparar_audio(b"w" * (1024 * 1024 + 1))
    svc.conversor = ConversorFalso(falha=True)
    with pytest.raises(AudioInvalido):
        await svc.preparar_audio(b"w")


class ProcFalso:
    def __init__(self, saida: bytes = b"pcm", rc: int = 0, demora: float = 0.0) -> None:
        self.saida, self.returncode, self.demora, self.morto = saida, None, demora, False
        self._rc = rc

    async def communicate(self, dados: bytes) -> tuple[bytes, bytes]:
        if self.demora:
            await asyncio.sleep(self.demora)
        self.returncode = self._rc
        return self.saida, b""

    def kill(self) -> None:
        self.morto = True


async def test_ffmpeg_args_e_prazo() -> None:
    chamadas: list[tuple[Any, ...]] = []
    proc = ProcFalso()

    async def criar(*args: Any, **_: Any) -> ProcFalso:
        chamadas.append(args)
        return proc

    conv = FfmpegConversor(criar, prazo_s=0.02)
    assert await conv.webm_para_pcm(b"w") == b"pcm"
    assert chamadas[0] == WEBM_PARA_PCM and "16000" in chamadas[0] and "s16le" in chamadas[0]
    proc.saida, proc._rc = b"", 1
    with pytest.raises(AudioInvalido):
        await conv.webm_para_pcm(b"w")
    lento = ProcFalso(demora=0.04)

    async def criar_lento(*_: Any, **__: Any) -> ProcFalso:
        return lento

    with pytest.raises(AudioInvalido):
        await FfmpegConversor(criar_lento, prazo_s=0.01).webm_para_pcm(b"w")
    assert lento.morto


# --------------------------------------------------------------------------- rotas (pg)


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


def _turnos_na_app(app: Any, tmp_path: Any, **kw: Any) -> Turnos:
    ctx = app.state.ctx

    async def atender_falso(texto: str, dispositivo: str, deps: Any, *, turno: str) -> TurnoFim:
        return TurnoFim(turno=turno, ok=True, texto=f"eco: {texto}", fala="eco")

    kw.setdefault("atender", atender_falso)
    kw.setdefault("fala", FalaNuvem(OpusFalso(), None, ctx.relogio))
    svc = Turnos(hub_de(ctx), ctx.relogio, publicar=Sse(), conversor=ConversorFalso(),
                 nuvem=object(), escuta=EscutaFalsa(), dir_audio=tmp_path, **kw)
    ctx.extras["turnos"] = svc
    return svc


@pytest.mark.pg
async def test_rotas_turno_texto_audio_e_dono(app, cliente, novo_token, relogio, tmp_path) -> None:
    svc = _turnos_na_app(app, tmp_path)
    tok, tok_outro = novo_token("celular-pedro", "celular"), novo_token("celular-ana", "celular")
    async with cliente(app, tok) as c, cliente(app, tok_outro) as c2:
        r = await c.post("/v1/turno", json={"texto": "oi"})
        assert r.status_code == 202 and r.json()["modo"] == "nuvem"
        tid = r.json()["turno"]
        await _ate(lambda: svc._turnos[tid].audio.fechado)
        r = await c.get(f"/v1/turno/{tid}")
        assert r.status_code == 200
        corpo = r.json()
        assert corpo["estado"] == "fim" and corpo["fim"]["texto"] == "eco: oi" and corpo["fim"]["audio"]
        assert (await c2.get(f"/v1/turno/{tid}")).status_code == 404
        assert (await c2.get(f"/v1/turno/{tid}/audio")).status_code == 404
        r = await c.get(f"/v1/turno/{tid}/audio")
        assert r.status_code == 200 and r.headers["content-type"].startswith("audio/ogg")
        assert r.content == b"OggS:eco"
        relogio.avancar(61)
        r = await c.get(f"/v1/turno/{tid}/audio")
        assert r.status_code == 410 and r.json()["erro"] == "expirado"
        r = await c.post("/v1/turno", files={"audio": ("a.webm", b"webm", "audio/webm;codecs=opus")})
        assert r.status_code == 202
        tid2 = r.json()["turno"]
        await _ate(lambda: svc._turnos[tid2].fim is not None)
        assert svc._turnos[tid2].fim.texto == "eco: que horas são"


@pytest.mark.pg
async def test_rotas_415_413_429(app, cliente, novo_token, tmp_path) -> None:
    svc = _turnos_na_app(app, tmp_path)
    tok = novo_token("celular-pedro", "celular")
    async with cliente(app, tok) as c:
        r = await c.post("/v1/turno", content=b"oi", headers={"content-type": "text/plain"})
        assert r.status_code == 415
        r = await c.post("/v1/turno", files={"audio": ("a.wav", b"RIFF", "audio/wav")})
        assert r.status_code == 415
        svc.conversor = ConversorFalso(b"\x00" * (16 * 32000))
        r = await c.post("/v1/turno", files={"audio": ("a.webm", b"webm", "audio/webm")})
        assert r.status_code == 413
        svc.conversor = ConversorFalso(falha=True)
        r = await c.post("/v1/turno", files={"audio": ("a.webm", b"webm", "audio/webm")})
        assert r.status_code == 415 and r.json()["erro"] == "audio_invalido"
        r = await c.post("/v1/turno", content=json.dumps({"texto": ""}),
                         headers={"content-type": "application/json"})
        assert r.status_code == 422
    tok2 = novo_token("celular-dois", "celular")
    async with cliente(app, tok2) as c:
        for _ in range(20):
            assert (await c.post("/v1/turno", json={"texto": "oi"})).status_code == 202
        r = await c.post("/v1/turno", json={"texto": "oi"})
        assert r.status_code == 429 and "Retry-After" in r.headers


@pytest.mark.pg
async def test_casa_offline_503_no_rest(app, cliente, novo_token) -> None:
    """CA-Y20 (parte REST): com a casa fora, o botão do PWA dá ``503 casa_offline``."""
    tok = novo_token("celular-pedro", "celular")
    async with cliente(app, tok) as c:
        r = await c.post("/v1/casa/acao", json={"tv": None, "pedido": {"intent": "tv.power_on"}})
    assert r.status_code == 503 and r.json()["erro"] == "casa_offline"
