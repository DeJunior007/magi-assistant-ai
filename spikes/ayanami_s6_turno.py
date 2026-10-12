"""Spike S6 — turno remoto, parte local (tarefa Y0.6 de ``specs/ayanami-central``).

No PC, sem Ayanami e sem rede: mede o ``ffmpeg`` dos dois lados do turno do celular e roda um
protótipo de ``RemoteLink`` falso contra o ``TurnMachine`` real, para achar o gancho
``on_turn_done`` [DS6] e o jeito de registrar um segundo satélite no ``CoreService``.

  transcode   webm/opus (15 s, como o MediaRecorder) → PCM s16le 16 kHz mono por pipe; p50/p90
  opus        PCM 24 kHz em quadros de 80 ms → ogg/opus 32k em streaming; 1º byte e total
  turno       protótipo: Turno de áudio (PTT) e de texto pelo TurnMachine com STT/TTS falsos;
              tempo do fim do áudio ao gancho e ao 1º AUDIO_OUT
  all         tudo acima (padrão)

Uso:  uv run python spikes/ayanami_s6_turno.py all --rodadas 20
Requer ``ffmpeg`` com ``libopus`` no PATH. Nada vai para fora do diretório temporário.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import statistics
import sys
import tempfile
import time
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from typing import Any

from wyoming.audio import AudioChunk, AudioStart

import magi.core.turn as turn_mod
from magi.common.contracts import (
    ActionResult,
    AudioEnd,
    AudioEndReason,
    CoreToSatellite,
    PcmFormat,
    PlaybackDone,
    SatelliteHello,
    StopPlayback,
    Transcript,
    TurnContext,
    WakeEvent,
    WakeSource,
)
from magi.core.hud_client import NullHud
from magi.core.service import CoreService
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline
from magi.elo.ids import novo_id
from magi.elo.quadros import MAX_CARGA, Quadro, QuadroTipo, decode_quadro, encode_quadro

SEGUNDOS = 15.0
IN_FMT = PcmFormat(rate=16000, width=2, channels=1)
OUT_FMT = PcmFormat(rate=24000, width=2, channels=1)
QUADRO_MS = 80
PRAZO_TRANSCODE_S = 2.0

CMD_DECODE = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
              "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"]
CMD_OPUS = ["ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
            "-c:a", "libopus", "-b:a", "32k", "-application", "voip", "-frame_duration", "20",
            "-flush_packets", "1", "-page_duration", "20000", "-f", "ogg", "pipe:1"]


def _pct(xs: list[float]) -> tuple[float, float, float]:
    """(p50, p90, máx) em ms."""
    s = sorted(xs)
    p90 = s[min(len(s) - 1, max(0, round(0.9 * len(s)) - 1))]
    return statistics.median(s) * 1000, p90 * 1000, s[-1] * 1000


def _linha(nome: str, xs: list[float]) -> str:
    p50, p90, mx = _pct(xs)
    return f"| {nome} | {len(xs)} | {p50:.0f} | {p90:.0f} | {mx:.0f} |"


def _gera_webm(dest: Path) -> bytes:
    """15 s de voz sintética (tons e ruído) em webm/opus 48 kHz, como o ``MediaRecorder``."""
    import subprocess

    src = (f"sine=frequency=220:duration={SEGUNDOS}[a];anoisesrc=d={SEGUNDOS}:a=0.05[b];"
           "[a][b]amix=inputs=2")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", src,
                    "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "24k", "-f", "webm",
                    str(dest)], check=True)
    return dest.read_bytes()


async def _pipe(cmd: list[str], data: bytes) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(data)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg saiu {proc.returncode}: {err.decode(errors='replace')[:200]}")
    return out


async def webm_para_pcm(webm: bytes) -> bytes:
    """O que a API faz na §6.2 passo 1."""
    return await asyncio.wait_for(_pipe(CMD_DECODE, webm), PRAZO_TRANSCODE_S * 5)


async def medir_transcode(webm: bytes, rodadas: int) -> list[float]:
    tempos: list[float] = []
    esperado = int(SEGUNDOS * IN_FMT.rate * IN_FMT.width)
    for _ in range(rodadas):
        t0 = time.perf_counter()
        pcm = await webm_para_pcm(webm)
        tempos.append(time.perf_counter() - t0)
        if abs(len(pcm) - esperado) > IN_FMT.bytes_for_ms(100):
            raise RuntimeError(f"PCM com {len(pcm)} bytes, esperado ~{esperado}")
    return tempos


async def opus_streaming(pcm: bytes) -> tuple[float, float, int]:
    """Alimenta o encoder em quadros de 80 ms e lê o ogg em paralelo.
    Devolve (1º byte com áudio após o 1º quadro, total, bytes de ogg)."""
    proc = await asyncio.create_subprocess_exec(
        *CMD_OPUS, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    assert proc.stdin is not None and proc.stdout is not None
    passo = OUT_FMT.bytes_for_ms(QUADRO_MS)
    t0 = time.perf_counter()
    primeiro: float | None = None
    total = 0
    cabecalhos = 0  # páginas OpusHead/OpusTags saem antes do 1º áudio

    async def ler() -> None:
        nonlocal primeiro, total, cabecalhos
        while chunk := await proc.stdout.read(4096):
            total += len(chunk)
            if primeiro is None:
                cabecalhos += chunk.count(b"OggS")
                if cabecalhos > 2 or total > 512:
                    primeiro = time.perf_counter() - t0

    leitor = asyncio.create_task(ler())
    for i in range(0, len(pcm), passo):
        proc.stdin.write(pcm[i : i + passo])
        await proc.stdin.drain()
    proc.stdin.close()
    await leitor
    await proc.wait()
    return (primeiro if primeiro is not None else float("nan")), time.perf_counter() - t0, total


async def medir_opus(rodadas: int) -> tuple[list[float], list[float], int]:
    import math

    n = int(SEGUNDOS * OUT_FMT.rate)
    amostras = (int(8000 * math.sin(2 * math.pi * 330 * i / OUT_FMT.rate)) for i in range(n))
    pcm = b"".join(a.to_bytes(2, "little", signed=True) for a in amostras)
    firsts: list[float] = []
    totais: list[float] = []
    tam = 0
    for _ in range(rodadas):
        f, t, tam = await opus_streaming(pcm)
        firsts.append(f)
        totais.append(t)
    return firsts, totais, tam


# ---------------------------------------------------------------------------------------------
# Protótipo do turno remoto (o que a Y6.2 escreve em magi/elo/remote.py e ponte.py)


class RemoteLinkFalso:
    """``SatelliteLink`` do celular: quadros AUDIO_OUT em vez de Wyoming; sem WS real.

    Achados que a Y6.2 precisa copiar:
    - o celular não manda ``playback-done``: o link o injeta no ``TurnMachine`` ao fim do
      ``play`` (senão o turno fica preso em ``speaking``);
    - ``ListenRequest`` (confirmação/continuação) é ignorado; ``StopPlayback`` → AUDIO_FIM.
    """

    def __init__(self) -> None:
        self.hello = SatelliteHello("celular", name="Celular", capabilities=("ptt", "playback"))
        self.machine: TurnMachine | None = None
        self.turno = novo_id()
        self.saida: list[bytes] = []  # quadros codificados, como iriam pela WS
        self.enviados: list[CoreToSatellite] = []
        self.primeiro_out: float | None = None

    async def send(self, msg: CoreToSatellite) -> None:
        self.enviados.append(msg)
        if isinstance(msg, StopPlayback):
            self.saida.append(encode_quadro(Quadro(QuadroTipo.AUDIO_FIM, self.turno)))

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        if fmt.rate != OUT_FMT.rate:
            raise RuntimeError(f"protótipo só cobre 24 kHz (veio {fmt.rate})")
        async for bloco in audio:
            for i in range(0, len(bloco), MAX_CARGA):
                if self.primeiro_out is None:
                    self.primeiro_out = time.perf_counter()
                self.saida.append(encode_quadro(Quadro(QuadroTipo.AUDIO_OUT, self.turno,
                                                       bloco[i : i + MAX_CARGA])))
        self.saida.append(encode_quadro(Quadro(QuadroTipo.AUDIO_FIM, self.turno)))
        if self.machine is not None:  # o celular não confirma o fim da reprodução
            asyncio.get_running_loop().create_task(self.machine.handle(PlaybackDone("celular")))


class PipelineCelular(TurnPipeline):
    """Mesmas deps do PC; turno de texto entra como transcrição pronta, sem STT."""

    def __init__(self, base: TurnPipeline) -> None:
        super().__init__(base.deps)
        self.texto_pronto: str | None = None

    async def transcribe(self, audio: bytes, fmt: PcmFormat, ctx: TurnContext, *,
                         stream: Any = None) -> Transcript:
        texto, self.texto_pronto = self.texto_pronto, None
        if texto is not None:
            if stream is not None:
                await stream.cancel()
            return Transcript.raw(texto)
        return await super().transcribe(audio, fmt, ctx, stream=stream)


def anexar(service: CoreService, link: RemoteLinkFalso) -> tuple[TurnMachine, PipelineCelular]:
    """Registro do satélite sem conexão TCP: espelha ``CoreService._serve`` (criação do
    ``TurnMachine`` e ``_machines[hello.satellite]``). A Y6.2 vira isto num método público."""
    pipe = PipelineCelular(service.pipeline)
    machine = TurnMachine(link, NullHud(), pipe, confirm_timeout_ms=service.confirm_timeout_ms,
                          confirm_grace_ms=service.confirm_grace_ms, followup_ms=None)
    service._machines[link.hello.satellite] = machine  # noqa: SLF001 - protótipo
    link.machine = machine
    return machine, pipe


class SttFalso:
    name = "stt-falso"

    async def transcribe(self, audio: bytes, fmt: PcmFormat, *, hint: str = "",
                         language: str = "pt", personal: bool) -> Transcript:
        return Transcript.raw("que horas são")


class SpeakerFalso:
    """TTS instantâneo: 1 s de silêncio a 24 kHz em blocos de 80 ms."""

    def __init__(self) -> None:
        self.chamado_em: float | None = None

    async def say(self, text: str, link: Any, *, personal: bool) -> None:
        self.chamado_em = time.perf_counter()

        async def blocos() -> AsyncIterator[bytes]:
            for _ in range(1000 // QUADRO_MS):
                yield bytes(OUT_FMT.bytes_for_ms(QUADRO_MS))

        await link.play(blocos(), OUT_FMT)


class Gancho:
    """Simula ``TurnDeps.on_turn_done``: embrulha o ``compose`` importado em ``magi.core.turn``
    (chamado em ``TurnMachine._deliver`` logo antes de cards/legenda/fala)."""

    def __init__(self) -> None:
        self.em: float | None = None
        self.resultado: ActionResult | None = None
        self._orig = turn_mod.compose

    def __enter__(self) -> Gancho:
        def compose(result: ActionResult) -> ActionResult:
            out = self._orig(result)
            self.em, self.resultado = time.perf_counter(), out
            return out

        turn_mod.compose = compose
        return self

    def __exit__(self, *_: object) -> None:
        turn_mod.compose = self._orig


async def _espera(cond: Any, limite_s: float = 2.0) -> None:
    t0 = time.perf_counter()
    while not cond():
        if time.perf_counter() - t0 > limite_s:
            raise TimeoutError("turno não terminou")
        await asyncio.sleep(0.001)


async def turno_remoto(pcm16: bytes | None, texto: str | None) -> tuple[float, float, int]:
    """Um turno de áudio (``pcm16``) ou texto pelo protótipo.
    Devolve (fim → gancho, fim → 1º AUDIO_OUT, nº de quadros de saída)."""
    speaker = SpeakerFalso()
    service = CoreService(TurnDeps(stt=SttFalso(), speaker=speaker), NullHud(), port=0)
    link = RemoteLinkFalso()
    machine, pipe = anexar(service, link)
    assert service.satellites["celular"] is machine
    with Gancho() as g:
        await machine.handle(WakeEvent(WakeSource.PTT, "celular"))
        await machine.handle(AudioStart(rate=IN_FMT.rate, width=IN_FMT.width,
                                        channels=IN_FMT.channels))
        if texto is not None:
            pipe.texto_pronto = texto
            pcm16 = bytes(IN_FMT.bytes_for_ms(QUADRO_MS))  # um quadro mudo: não é "silencioso"
        assert pcm16 is not None
        passo = IN_FMT.bytes_for_ms(QUADRO_MS)
        for i in range(0, len(pcm16), passo):
            q = decode_quadro(encode_quadro(Quadro(QuadroTipo.AUDIO_IN, link.turno,
                                                   pcm16[i : i + passo])))
            await machine.handle(AudioChunk(rate=IN_FMT.rate, width=IN_FMT.width,
                                            channels=IN_FMT.channels, audio=q.pcm))
        t0 = time.perf_counter()
        await machine.handle(AudioEnd(reason=AudioEndReason.PTT_RELEASE))
        await _espera(lambda: machine.state.value == "sleeping" and link.primeiro_out is not None)
    if g.em is None or speaker.chamado_em is None or link.primeiro_out is None:
        raise RuntimeError("gancho ou fala não aconteceram")
    if not g.em < speaker.chamado_em:
        raise RuntimeError("gancho depois da fala")
    await machine.close()
    return g.em - t0, link.primeiro_out - t0, len(link.saida)


async def medir_turno(pcm16: bytes, rodadas: int) -> dict[str, list[float]]:
    r: dict[str, list[float]] = {"audio_gancho": [], "audio_out": [], "texto_gancho": [],
                                 "texto_out": []}
    for _ in range(rodadas):
        a, b, _ = await turno_remoto(pcm16, None)
        r["audio_gancho"].append(a)
        r["audio_out"].append(b)
        a, b, _ = await turno_remoto(None, "que horas são")
        r["texto_gancho"].append(a)
        r["texto_out"].append(b)
    return r


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("modo", nargs="?", default="all", choices=["transcode", "opus", "turno", "all"])
    ap.add_argument("--rodadas", type=int, default=20)
    a = ap.parse_args(argv)
    if shutil.which("ffmpeg") is None:
        print("ffmpeg não encontrado no PATH", file=sys.stderr)
        return 2
    print("| medida | n | p50 ms | p90 ms | máx ms |\n| --- | --- | --- | --- | --- |")
    ok = True
    with tempfile.TemporaryDirectory(prefix="ayanami-s6-") as tmp:
        webm = _gera_webm(Path(tmp) / "fala.webm")
        pcm16 = await webm_para_pcm(webm)
        if a.modo in ("transcode", "all"):
            t = await medir_transcode(webm, a.rodadas)
            print(_linha(f"webm/opus {SEGUNDOS:.0f} s ({len(webm) // 1024} KiB) → PCM 16 kHz", t))
            ok &= _pct(t)[1] / 1000 <= PRAZO_TRANSCODE_S
        if a.modo in ("opus", "all"):
            f, tot, tam = await medir_opus(a.rodadas)
            print(_linha("PCM 24 kHz → ogg/opus 32k: 1º byte de áudio", f))
            print(_linha(f"PCM 24 kHz → ogg/opus 32k: total ({tam // 1024} KiB)", tot))
        if a.modo in ("turno", "all"):
            r = await medir_turno(pcm16, a.rodadas)
            print(_linha("turno áudio: AUDIO_FIM → gancho", r["audio_gancho"]))
            print(_linha("turno áudio: AUDIO_FIM → 1º AUDIO_OUT", r["audio_out"]))
            print(_linha("turno texto: fim → gancho", r["texto_gancho"]))
            print(_linha("turno texto: fim → 1º AUDIO_OUT", r["texto_out"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
