"""Turnos do celular em andamento e o áudio temporário da resposta (dono: Y6.4; spec §6.1, §6.2).

:class:`Turnos` (um por processo, ``turnos_de(ctx)`` → ``ctx.extras["turnos"]``):

- :meth:`Turnos.modo`: ``"pc"`` se o ``pc`` bateu há menos de ``[rede] offline_apos_s``
  (``hub.online("pc")``), senão ``"nuvem"``. A decisão é tomada no ``POST`` e fica no turno.
- Modo ``pc``: ``Turno`` pelo hub; áudio → PCM 16 kHz (:class:`Conversor`, ``ffmpeg`` em ≤ 2 s)
  em quadros ``AUDIO_IN`` de 80 ms + ``AUDIO_FIM`` pela WS do PC. Espera o ``turno_fim``
  (``hub.ao_receber(TURNO_FIM)``); a conexão do PC que recebeu o turno caiu (ou foi trocada) →
  ``TurnoFim(ok=False, erro="pc_caiu")`` sem refazer; sem resposta em ``prazo_pc_s`` →
  ``erro="tempo"``. ``AUDIO_OUT`` (PCM 24 kHz) que o PC manda → ogg/opus no arquivo do turno.
- Modo ``nuvem``: áudio → texto pela :class:`~ayanami.voz_nuvem.EscutaNuvem`; ``nuvem.atender``;
  a fala sai pela :class:`~ayanami.voz_nuvem.FalaNuvem` (opus pronto ou PCM do Kokoro → ogg).
- ``turno.texto`` e ``turno.fim`` vão ao SSE do dispositivo dono assim que o ``TurnoFim`` chega.
- Áudio: arquivo em ``dir_audio``, lido em streaming enquanto gera; 60 s depois de fechado o
  arquivo é apagado e o ``GET …/audio`` dá ``410`` (varredura a cada chamada + ``call_later``).

Quadros binários vindos do PC entram por :meth:`Turnos.receber_quadro` (quem lê a WS chama).
Relógio, conversor (``ffmpeg``), STT/TTS e ``atender`` são injetados.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from ayanami.api.auth import Dispositivo
from ayanami.api.limites import Janela
from magi.elo.ids import novo_id
from magi.elo.mensagens import EloError, Envelope, Tipo, Turno, TurnoFim
from magi.elo.quadros import Quadro, QuadroTipo, decode_quadro, encode_quadro

log = logging.getLogger("ayanami.turnos")

TURNOS_POR_MINUTO: Final = 20
AUDIO_MAX_BYTES: Final = 1024 * 1024
AUDIO_MAX_S: Final = 15.0
PCM_IN_HZ: Final = 16000
PCM_OUT_HZ: Final = 24000
QUADRO_IN_BYTES: Final = 2560  # 80 ms de s16le mono 16 kHz
PRAZO_TRANSCODE_S: Final = 2.0
PRAZO_PC_S: Final = 50.0  # 45 s do agente no PC (§6.2) + folga do fio
AUDIO_TTL_S: Final = 60.0
OCIOSO_APOS_FIM_S: Final = 5.0  # sem AUDIO_OUT depois do TurnoFim → fecha o áudio
GUARDA_S: Final = 600.0  # o registro do turno some 10 min depois do fim
CHECA_S: Final = 0.05  # passo da espera (tempo real) para notar a queda do PC


class AudioInvalido(ValueError):
    """O webm não decodificou (``415``)."""


class AudioLongo(ValueError):
    """Mais de 15 s (``413``)."""


class AudioExpirado(Exception):
    """Áudio apagado (``410``)."""


# --------------------------------------------------------------------------- conversor


class Conversor(Protocol):
    async def webm_para_pcm(self, webm: bytes) -> bytes: ...  # PCM s16le mono 16 kHz
    def ogg_de(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[bytes]: ...  # PCM 24 kHz → ogg/opus


WEBM_PARA_PCM: Final = ("ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                        "-f", "s16le", "-ac", "1", "-ar", str(PCM_IN_HZ), "pipe:1")
PCM_PARA_OGG: Final = ("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le",
                       "-ar", str(PCM_OUT_HZ), "-ac", "1", "-i", "pipe:0", "-c:a", "libopus",
                       "-b:a", "32k", "-flush_packets", "1", "-page_duration", "20000",
                       "-f", "ogg", "pipe:1")


class FfmpegConversor:
    """``ffmpeg`` por ``pipe:`` (S6: webm 15 s → PCM p90 119 ms; ogg exige ``-flush_packets 1
    -page_duration 20000``). ``criar`` = ``asyncio.create_subprocess_exec`` (injetável)."""

    def __init__(self, criar: Callable[..., Awaitable[Any]] | None = None, *,
                 prazo_s: float = PRAZO_TRANSCODE_S) -> None:
        self.criar = criar or asyncio.create_subprocess_exec
        self.prazo_s = prazo_s

    async def webm_para_pcm(self, webm: bytes) -> bytes:
        p = await self.criar(*WEBM_PARA_PCM, stdin=asyncio.subprocess.PIPE,
                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            saida, _ = await asyncio.wait_for(p.communicate(webm), self.prazo_s)
        except TimeoutError as e:
            with contextlib.suppress(ProcessLookupError):
                p.kill()
            raise AudioInvalido("ffmpeg passou do prazo") from e
        if p.returncode != 0 or not saida:
            raise AudioInvalido("webm não decodificou")
        return saida

    async def ogg_de(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        p = await self.criar(*PCM_PARA_OGG, stdin=asyncio.subprocess.PIPE,
                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

        async def alimentar() -> None:
            try:
                async for bloco in pcm:
                    p.stdin.write(bloco)
                    await p.stdin.drain()
            finally:
                with contextlib.suppress(Exception):
                    p.stdin.close()

        tarefa = asyncio.ensure_future(alimentar())
        try:
            while bloco := await p.stdout.read(4096):
                yield bloco
            await tarefa
        finally:
            tarefa.cancel()
            if p.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    p.kill()
            with contextlib.suppress(Exception):
                await p.wait()


# --------------------------------------------------------------------------- áudio temporário


@dataclass(eq=False)
class AudioTurno:
    """Arquivo ogg do turno: escrito enquanto chega, lido em streaming, apagado no fim do TTL."""

    caminho: Path
    tamanho: int = 0
    fechado: bool = False
    expirado: bool = False
    fechado_em: float | None = None
    novo: asyncio.Event = field(default_factory=asyncio.Event)

    def escrever(self, dados: bytes) -> None:
        if self.fechado or not dados:
            return
        with self.caminho.open("ab") as f:
            f.write(dados)
        self.tamanho += len(dados)
        self.novo.set()

    def fechar(self, agora: float) -> None:
        if not self.fechado:
            self.fechado, self.fechado_em = True, agora
            self.caminho.touch(exist_ok=True)
            self.novo.set()

    def apagar(self) -> None:
        self.expirado = True
        self.caminho.unlink(missing_ok=True)

    async def ler(self) -> AsyncIterator[bytes]:
        pos = 0
        while True:
            if self.expirado:
                return
            if pos < self.tamanho:
                with self.caminho.open("rb") as f:
                    f.seek(pos)
                    bloco = f.read(self.tamanho - pos)
                pos += len(bloco)
                yield bloco
                continue
            if self.fechado:
                return
            self.novo.clear()
            if pos < self.tamanho or self.fechado:
                continue
            await self.novo.wait()


class _PcmParaOgg:
    """Fila de PCM 24 kHz → ``Conversor.ogg_de`` → :class:`AudioTurno` (uma tarefa por turno)."""

    def __init__(self, conversor: Conversor, audio: AudioTurno) -> None:
        self.fila: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.tarefa = asyncio.ensure_future(self._rodar(conversor, audio))

    async def _pcm(self) -> AsyncIterator[bytes]:
        while (b := await self.fila.get()) is not None:
            yield b

    async def _rodar(self, conversor: Conversor, audio: AudioTurno) -> None:
        try:
            async for bloco in conversor.ogg_de(self._pcm()):
                audio.escrever(bloco)
        except Exception as e:  # noqa: BLE001 - sem áudio a resposta em texto segue valendo
            log.warning("turno_ogg_falhou (%s)", type(e).__name__)

    def por(self, pcm: bytes) -> None:
        self.fila.put_nowait(pcm)

    async def terminar(self) -> None:
        self.fila.put_nowait(None)
        await asyncio.gather(self.tarefa, return_exceptions=True)


# --------------------------------------------------------------------------- turno


@dataclass(eq=False)
class TurnoAndamento:
    id: str
    dono: int
    dono_nome: str
    modo: str  # "pc" | "nuvem"
    criado: float
    audio: AudioTurno
    fim: TurnoFim | None = None
    fim_em: float | None = None
    no_pc: Any = None
    feito: asyncio.Event = field(default_factory=asyncio.Event)
    ogg: _PcmParaOgg | None = None
    ultimo_out: float | None = None
    tarefa: asyncio.Task[Any] | None = None

    @property
    def estado(self) -> str:
        return "fim" if self.fim is not None else "andando"

    def para_json(self) -> dict[str, Any]:
        return {"turno": self.id, "modo": self.modo, "estado": self.estado,
                "fim": dataclasses.asdict(self.fim) if self.fim is not None else None}


Atender = Callable[..., Awaitable[TurnoFim]]


class Turnos:
    def __init__(
        self,
        hub: Any,
        relogio: Any,
        *,
        publicar: Callable[..., Any] | None = None,
        conversor: Conversor | None = None,
        nuvem: Callable[[], Any] | Any = None,
        atender: Atender | None = None,
        escuta: Any = None,
        fala: Any = None,
        frases: dict[str, str] | None = None,
        dir_audio: Path | None = None,
        prazo_pc_s: float = PRAZO_PC_S,
        audio_ttl_s: float = AUDIO_TTL_S,
        por_minuto: int = TURNOS_POR_MINUTO,
    ) -> None:
        self.hub = hub
        self.relogio = relogio
        self.publicar = publicar
        self.conversor: Conversor = conversor or FfmpegConversor()
        self._nuvem = nuvem
        self._atender = atender
        self.escuta = escuta
        self.fala = fala
        if frases is None:
            from ayanami.nuvem import carregar_frases

            frases = carregar_frases()
        self.frases = frases
        self._dir = dir_audio
        self.prazo_pc_s = prazo_pc_s
        self.audio_ttl_s = audio_ttl_s
        self.limite = Janela(relogio, por_minuto)
        self._turnos: dict[str, TurnoAndamento] = {}
        hub.ao_receber(Tipo.TURNO_FIM, self.ao_turno_fim)

    # --- decisão e entrada --------------------------------------------------------------------

    def modo(self) -> str:
        return "pc" if self.hub.online("pc") and self.hub.destino("pc") is not None else "nuvem"

    def contar(self, disp: Dispositivo) -> None:
        """``429`` com mais de 20 turnos por minuto do mesmo dispositivo."""
        self.limite.contar(disp.id)

    def _pasta(self) -> Path:
        if self._dir is None:
            self._dir = Path(tempfile.mkdtemp(prefix="ayanami-turnos-"))
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    async def preparar_audio(self, webm: bytes) -> bytes:
        """webm/opus → PCM 16 kHz; ``AudioLongo`` acima de 15 s, ``AudioInvalido`` se não decodifica."""
        if len(webm) > AUDIO_MAX_BYTES:
            raise AudioLongo("mais de 1 MiB")
        pcm = await self.conversor.webm_para_pcm(webm)
        if len(pcm) > int(AUDIO_MAX_S * PCM_IN_HZ * 2):
            raise AudioLongo("mais de 15 s")
        return pcm

    async def iniciar(self, disp: Dispositivo, *, texto: str | None = None,
                      webm: bytes | None = None, pcm: bytes | None = None,
                      mime: str = "audio/webm") -> TurnoAndamento:
        """Cria o turno (modo fixo daqui em diante) e o roda em segundo plano."""
        self.varrer()
        modo = self.modo()
        tid = novo_id()
        t = TurnoAndamento(tid, disp.id, disp.nome, modo, self.relogio.monotonico(),
                           AudioTurno(self._pasta() / f"{tid}.ogg"))
        self._turnos[tid] = t
        if modo == "pc":
            coro = self._rodar_pc(t, texto, webm, pcm, mime)
        else:
            coro = self._rodar_nuvem(t, texto, webm, mime)
        t.tarefa = asyncio.ensure_future(coro)
        return t

    # --- leitura ------------------------------------------------------------------------------

    def obter(self, tid: str, disp: Dispositivo) -> TurnoAndamento | None:
        """Só o dono vê o turno (outro dispositivo → ``None`` → ``404``)."""
        self.varrer()
        t = self._turnos.get(tid)
        return t if t is not None and t.dono == disp.id else None

    def audio(self, tid: str, disp: Dispositivo) -> AsyncIterator[bytes] | None:
        t = self.obter(tid, disp)
        if t is None:
            return None
        if t.audio.expirado:
            raise AudioExpirado(tid)
        return t.audio.ler()

    def varrer(self) -> None:
        agora = self.relogio.monotonico()
        for tid, t in list(self._turnos.items()):
            a = t.audio
            if a.fechado and not a.expirado and agora - (a.fechado_em or agora) >= self.audio_ttl_s:
                a.apagar()
            if t.fim_em is not None and agora - t.fim_em >= GUARDA_S:
                a.apagar()
                del self._turnos[tid]

    def _agendar_varredura(self) -> None:
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().call_later(self.audio_ttl_s + 1, self.varrer)

    # --- fim ----------------------------------------------------------------------------------

    def _frase_fim(self, t: TurnoAndamento, erro: str, chave: str) -> TurnoFim:
        frase = self.frases.get(chave, "")
        return TurnoFim(turno=t.id, ok=False, texto=frase, fala=frase, erro=erro)

    def _fechar(self, t: TurnoAndamento, fim: TurnoFim, *, audio: bool | None = None) -> bool:
        """Grava o ``TurnoFim`` e avisa o SSE. ``audio`` (padrão: há fala) diz ao PWA se vale
        pedir ``GET …/audio`` — o ``TurnoFim`` do PC sai antes da fala."""
        if t.fim is not None:
            return False
        if audio is None:
            audio = fim.audio or (bool(fim.fala) and fim.erro is None)
        if audio != fim.audio:
            fim = dataclasses.replace(fim, audio=audio)
        t.fim, t.fim_em = fim, self.relogio.monotonico()
        t.feito.set()
        if self.publicar is not None:
            try:
                self.publicar(t.dono, "turno.texto", {"turno": t.id, "texto": fim.texto})
                self.publicar(t.dono, "turno.fim", fim)
            except Exception as e:  # noqa: BLE001 - SSE fora não derruba o turno
                log.warning("turno_sse_falhou (%s)", type(e).__name__)
        return True

    async def _fechar_audio(self, t: TurnoAndamento) -> None:
        if t.ogg is not None:
            ogg, t.ogg = t.ogg, None
            await ogg.terminar()
        t.audio.fechar(self.relogio.monotonico())
        self._agendar_varredura()

    # --- modo pc ------------------------------------------------------------------------------

    def _pc_caiu(self, t: TurnoAndamento) -> bool:
        no = t.no_pc
        return no is None or no.fechado or self.hub.ativo(no.disp.id) is not no

    async def _rodar_pc(self, t: TurnoAndamento, texto: str | None, webm: bytes | None,
                        pcm: bytes | None, mime: str) -> None:
        try:
            await self._pc(t, texto, webm, pcm, mime)
        except Exception:  # noqa: BLE001 - o turno sempre fecha
            log.exception("turno_pc_falhou")
            self._fechar(t, self._frase_fim(t, "interno", "erro_generico"))
        finally:
            if t.fim is not None and (t.fim.erro or not t.fim.fala):
                await self._fechar_audio(t)
            elif t.fim is not None:
                await self._esperar_fala(t)

    async def _pc(self, t: TurnoAndamento, texto: str | None, webm: bytes | None,
                  pcm: bytes | None, mime: str) -> None:
        no = self.hub.destino("pc")
        t.no_pc = no
        if no is None:
            self._fechar(t, self._frase_fim(t, "pc_caiu", "pc_caiu"))
            return
        if pcm is None and webm is not None:
            pcm = await self.conversor.webm_para_pcm(webm)
        binario = pcm is not None and _pode_binario(no.canal)
        if pcm is not None and not binario:  # long-poll não leva quadros: STT da nuvem e vai texto
            if self.escuta is None or webm is None:
                self._fechar(t, self._frase_fim(t, "sem_audio", "erro_generico"))
                return
            texto, pcm = await self.escuta.transcrever(webm, mime), None
        corpo = Turno(turno=t.id, texto=texto if pcm is None else None, audio=pcm is not None,
                      dispositivo=t.dono_nome)
        env = Envelope(Tipo.TURNO, corpo, "ayanami", no.disp.nome)
        if not await self.hub.enviar(env) or self._pc_caiu(t):
            self._fechar(t, self._frase_fim(t, "pc_caiu", "pc_caiu"))
            return
        if pcm is not None:
            for i in range(0, len(pcm), QUADRO_IN_BYTES):
                bloco = pcm[i:i + QUADRO_IN_BYTES]
                await _mandar_binario(no.canal, encode_quadro(Quadro(QuadroTipo.AUDIO_IN, t.id, bloco)))
            await _mandar_binario(no.canal, encode_quadro(Quadro(QuadroTipo.AUDIO_FIM, t.id)))
        await self._esperar_fim(t)

    async def _esperar_fim(self, t: TurnoAndamento) -> None:
        limite = t.criado + self.prazo_pc_s
        while t.fim is None:
            if self._pc_caiu(t):
                log.info("turno_pc_caiu", extra={"turno": t.id})
                self._fechar(t, self._frase_fim(t, "pc_caiu", "pc_caiu"))
                return
            if self.relogio.monotonico() >= limite:
                self._fechar(t, self._frase_fim(t, "tempo", "erro_generico"))
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(t.feito.wait(), CHECA_S)

    async def _esperar_fala(self, t: TurnoAndamento) -> None:
        """Depois do ``TurnoFim`` com fala: o ``AUDIO_FIM`` seguinte (ou ``OCIOSO_APOS_FIM_S``
        sem ``AUDIO_OUT``, ou o PC cair) fecha o áudio."""
        while not t.audio.fechado:
            base = t.ultimo_out if t.ultimo_out is not None else t.fim_em or 0.0
            if self._pc_caiu(t) or self.relogio.monotonico() - base >= OCIOSO_APOS_FIM_S:
                await self._fechar_audio(t)
                return
            await asyncio.sleep(CHECA_S)

    def ao_turno_fim(self, disp: Dispositivo, env: Envelope) -> None:
        """Gancho ``hub.ao_receber(TURNO_FIM)``: só o PC fecha turno ``pc`` (o hub responde ``ack``)."""
        fim = env.corpo
        if disp.tipo != "pc" or not isinstance(fim, TurnoFim):
            return
        t = self._turnos.get(fim.turno)
        if t is None or t.modo != "pc":
            return
        self._fechar(t, fim)

    async def receber_quadro(self, raw: bytes, disp: Dispositivo | None = None) -> None:
        """Quadro binário do PC: ``AUDIO_OUT`` → ogg do turno; ``AUDIO_FIM`` depois do fim fecha."""
        if disp is not None and disp.tipo != "pc":
            return
        try:
            q = decode_quadro(raw)
        except EloError:
            log.info("turno_quadro_invalido")
            return
        t = self._turnos.get(q.turno)
        if t is None or t.modo != "pc" or t.audio.fechado:
            return
        if q.tipo is QuadroTipo.AUDIO_OUT and q.pcm:
            if t.ogg is None:
                t.ogg = _PcmParaOgg(self.conversor, t.audio)
            t.ogg.por(q.pcm)
            t.ultimo_out = self.relogio.monotonico()
        elif q.tipo is QuadroTipo.AUDIO_FIM:
            t.ultimo_out = self.relogio.monotonico()
            if t.fim is not None:
                await self._fechar_audio(t)

    # --- modo nuvem ---------------------------------------------------------------------------

    def _deps_nuvem(self) -> Any:
        if callable(self._nuvem) and not hasattr(self._nuvem, "hub"):
            self._nuvem = self._nuvem()
        return self._nuvem

    async def _rodar_nuvem(self, t: TurnoAndamento, texto: str | None, webm: bytes | None,
                           mime: str) -> None:
        try:
            if texto is None:
                if self.escuta is None or webm is None:
                    self._fechar(t, self._frase_fim(t, "stt", "erro_generico"))
                    return
                texto = await self.escuta.transcrever(webm, mime)
            atender = self._atender
            if atender is None:
                from ayanami.nuvem import atender
            fim = await atender(texto, t.dono_nome, self._deps_nuvem(), turno=t.id)
            falar = self.fala is not None and bool(fim.fala)
            self._fechar(t, fim, audio=falar)
            if falar:
                await self._falar_nuvem(t, fim.fala)
        except Exception:  # noqa: BLE001 - o turno sempre fecha
            log.exception("turno_nuvem_falhou")
            self._fechar(t, self._frase_fim(t, "interno", "erro_generico"))
        finally:
            await self._fechar_audio(t)

    async def _falar_nuvem(self, t: TurnoAndamento, fala: str) -> None:
        try:
            audio = await self.fala.sintetizar(fala)
        except Exception as e:  # noqa: BLE001 - VozIndisponivel etc.: fica só o texto
            log.info("turno_nuvem_sem_voz (%s)", type(e).__name__)
            return
        if audio.formato == "opus":
            t.audio.escrever(audio.dados)
            return
        t.ogg = _PcmParaOgg(self.conversor, t.audio)
        t.ogg.por(audio.dados)


def _pode_binario(canal: Any) -> bool:
    return callable(getattr(canal, "enviar_bytes", None)) or getattr(canal, "ws", None) is not None


async def _mandar_binario(canal: Any, dados: bytes) -> None:
    """Quadro binário pela WS do nó (o ``Canal`` do hub só manda texto)."""
    enviar = getattr(canal, "enviar_bytes", None)
    if callable(enviar):
        await enviar(dados)
        return
    trava = getattr(canal, "_trava", None) or contextlib.nullcontext()
    async with trava:
        await canal.ws.send_bytes(dados)


def turnos_de(ctx: Any) -> Turnos:
    """O serviço da app (``ctx.extras["turnos"]``), ligado ao hub e ao SSE na 1ª vez.

    Usa de ``ctx.extras`` (se houver): ``conversor``, ``escuta``/``fala`` (STT/TTS da nuvem),
    ``nuvem`` (``NuvemDeps`` pronta); sem ``nuvem``, monta ``NuvemDeps.de_deps`` com o ``Deps``
    da API (sem ``registry``: o agente da nuvem cai em ``erro_generico`` até alguém montá-lo).
    """
    svc = ctx.extras.get("turnos")
    if svc is not None:
        return svc
    from ayanami.api.eventos import sse_de
    from ayanami.hub import hub_de

    hub = hub_de(ctx)
    sse = sse_de(ctx)

    def nuvem_padrao() -> Any:
        from ayanami.confirmacoes import confirmacoes_de
        from ayanami.deps import Deps
        from ayanami.nuvem import NuvemDeps

        deps = Deps(db=ctx.db, cfg=ctx.cfg, relogio=ctx.relogio, hub=hub)
        return NuvemDeps.de_deps(deps, hub, confirmacoes=confirmacoes_de(ctx))

    svc = Turnos(hub, ctx.relogio, publicar=sse.publicar, conversor=ctx.extras.get("conversor"),
                 nuvem=ctx.extras.get("nuvem") or nuvem_padrao, escuta=ctx.extras.get("escuta"),
                 fala=ctx.extras.get("fala"), dir_audio=ctx.extras.get("dir_turnos"))
    ctx.extras["turnos"] = svc
    return svc


__all__ = ["AudioExpirado", "AudioInvalido", "AudioLongo", "Conversor", "FfmpegConversor",
           "TurnoAndamento", "Turnos", "turnos_de"]
