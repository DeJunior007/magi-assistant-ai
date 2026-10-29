"""``PonteTurnos``: ``Turno`` da Ayanami → ``TurnMachine`` do satélite ``celular`` (spec §6.3).

- Um ``TurnMachine`` do ``celular`` criado na 1ª vez (``CoreService.anexar``) e reusado, com o
  ``RemoteLink``, ``NullHud`` (o turno do celular não mexe no rosto do PC) e sem janela de
  continuação.
- Áudio entra como PTT: ``WakeEvent(PTT)`` → ``AudioStart(16 kHz)`` → um ``AudioChunk`` por
  ``AUDIO_IN`` → ``AudioEnd(ptt_release)`` no ``AUDIO_FIM``. Texto entra pelo mesmo caminho com um
  quadro mudo de 80 ms e um ``TurnPipeline`` do celular cujo ``transcribe`` devolve o texto pronto
  (sem STT; achado do S6).
- [DS6] ``TurnDeps.on_turn_done``: para ``ctx.satellite == "celular"`` manda **um** ``TurnoFim``
  por ``Turno`` (``resultado_de_action`` + ``card_de_cardmsg``); outros satélites: nada. O envio
  roda em segundo plano (o gancho não atrasa a fala).
- Prazo de 45 s do ``Turno`` ao gancho → ``TurnoFim(ok=False, erro="tempo")``; resposta que chegar
  depois é descartada. ``Turno`` novo com outro em andamento → ``TurnoFim(erro="ocupado")``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Final

from wyoming.audio import AudioChunk, AudioStart

from magi.common.contracts import (
    ActionResult,
    AudioEnd,
    AudioEndReason,
    PcmFormat,
    Transcript,
    TurnContext,
    WakeEvent,
    WakeSource,
)
from magi.core.hud_client import NullHud
from magi.core.turn import TurnMachine, TurnPipeline
from magi.elo.converte import card_de_cardmsg
from magi.elo.mensagens import MAX_TURNO_FIM_OUVIDO, MAX_TURNO_FIM_TEXTO, Envelope, Tipo, Turno, TurnoFim
from magi.elo.quadros import Quadro
from magi.elo.remote import ENTRADA_FMT, QUADRO_MS, SATELITE, RemoteLink

log = logging.getLogger(__name__)

PRAZO_S: Final = 45.0


class PipelineCelular(TurnPipeline):
    """Mesmas ``deps`` do PC; turno de texto vira transcrição pronta, sem STT."""

    def __init__(self, base: TurnPipeline) -> None:
        super().__init__(base.deps)
        self.texto_pronto: str | None = None
        self.ouvido = ""  # texto do STT do turno de áudio → ``TurnoFim.ouvido`` (turno de texto: vazio)

    async def transcribe(  # type: ignore[override]
        self, audio: bytes, fmt: PcmFormat, ctx: TurnContext, *, stream: Any = None
    ) -> Transcript:
        texto, self.texto_pronto = self.texto_pronto, None
        if texto is not None:
            if stream is not None:
                await stream.cancel()
            return Transcript.raw(texto)
        tr = await super().transcribe(audio, fmt, ctx, stream=stream)
        self.ouvido = (tr.final or tr.heard).strip()[:MAX_TURNO_FIM_OUVIDO]
        return tr


@dataclass
class _Ativo:
    turno: str
    feito: asyncio.Event = field(default_factory=asyncio.Event)


class PonteTurnos:
    def __init__(self, core: Any, cliente: Any, *, prazo_s: float = PRAZO_S) -> None:
        """``core``: ``CoreService`` (``anexar``, ``pipeline``); ``cliente``: ``EloCliente``."""
        self.core = core
        self.cliente = cliente
        self.prazo_s = prazo_s
        self.link = RemoteLink(cliente)
        self.machine: TurnMachine | None = None
        self.pipeline: PipelineCelular | None = None
        self._ativo: _Ativo | None = None
        self._tarefas: set[asyncio.Task[Any]] = set()
        core.pipeline.deps.on_turn_done = self.on_turn_done

    # --- entrada --------------------------------------------------------------------------------

    async def receber(self, env: Envelope) -> None:
        """Handler de ``turno`` do ``EloCliente``: volta já (o cliente responde ``ack``) e roda o
        turno em segundo plano."""
        t = env.corpo
        if not isinstance(t, Turno):
            return
        if self._ativo is not None and not self._ativo.feito.is_set():
            log.info("celular: turno %s recusado, outro em andamento", t.turno)
            self._manda(TurnoFim(turno=t.turno, ok=False, erro="ocupado"))
            return
        ativo = self._ativo = _Ativo(t.turno)
        self.link.novo_turno(t.turno)
        self._tarefa(self._rodar(t, ativo))

    def receber_quadro(self, q: Quadro) -> None:
        """Handler de quadros binários do ``EloCliente``."""
        self.link.receber_quadro(q)

    async def _maquina(self) -> TurnMachine:
        if self.machine is None:
            self.pipeline = PipelineCelular(self.core.pipeline)
            self.machine = await self.core.anexar(
                self.link, pipeline=self.pipeline, hud=NullHud(), followup_ms=None
            )
            self.link.machine = self.machine
        return self.machine

    async def _rodar(self, t: Turno, ativo: _Ativo) -> None:
        try:
            await asyncio.wait_for(self._alimenta(t, ativo), self.prazo_s)
        except TimeoutError:
            pass
        except Exception:
            log.exception("celular: turno %s falhou", t.turno)
            self._fecha(ativo, TurnoFim(turno=t.turno, ok=False, erro="interno"))
            return
        if not ativo.feito.is_set():
            log.info("celular: turno %s passou de %.0f s", t.turno, self.prazo_s)
            self._fecha(ativo, TurnoFim(turno=t.turno, ok=False, erro="tempo"))

    async def _alimenta(self, t: Turno, ativo: _Ativo) -> None:
        machine = await self._maquina()
        f = ENTRADA_FMT
        await machine.handle(WakeEvent(WakeSource.PTT, SATELITE))
        assert self.pipeline is not None
        self.pipeline.ouvido = ""
        await machine.handle(AudioStart(rate=f.rate, width=f.width, channels=f.channels))
        try:
            if t.texto is not None:
                self.pipeline.texto_pronto = t.texto
                mudo = bytes(f.bytes_for_ms(QUADRO_MS))  # não conta como "silencioso"
                await machine.handle(
                    AudioChunk(rate=f.rate, width=f.width, channels=f.channels, audio=mudo)
                )
            else:
                async for pcm in self.link.entrada():
                    await machine.handle(
                        AudioChunk(rate=f.rate, width=f.width, channels=f.channels, audio=pcm)
                    )
        finally:  # prazo estourado no meio do áudio: fecha a gravação mesmo assim
            await asyncio.shield(machine.handle(AudioEnd(reason=AudioEndReason.PTT_RELEASE)))
        await ativo.feito.wait()

    # --- gancho [DS6] ---------------------------------------------------------------------------

    async def on_turn_done(self, ctx: TurnContext, result: ActionResult) -> None:
        if ctx.satellite != SATELITE:
            return  # headset e outros: nada (a resposta deles nunca vai ao celular)
        ativo = self._ativo
        if ativo is None or ativo.feito.is_set():
            log.info("celular: resposta fora de turno descartada")
            return
        texto = result.full_text or result.speech or ""
        fim = TurnoFim(
            turno=ativo.turno,
            ok=result.ok,
            texto=texto[:MAX_TURNO_FIM_TEXTO],
            fala=result.speech,
            cards=tuple(card_de_cardmsg(c) for c in result.cards),
            expressao=result.expression.value if result.expression is not None else None,
            audio=self.link.quadros_out > 0,
            ouvido=self.pipeline.ouvido if self.pipeline is not None else "",
        )
        self._fecha(ativo, fim)

    # --- envio ----------------------------------------------------------------------------------

    def _fecha(self, ativo: _Ativo, fim: TurnoFim) -> None:
        if ativo.feito.is_set():
            return
        ativo.feito.set()
        if fim.erro is not None and self.link.turno == ativo.turno:
            self.link.novo_turno("")  # fala atrasada do turno vencido não vai ao celular
        self._manda(fim)

    def _manda(self, fim: TurnoFim) -> None:
        self._tarefa(self._envia(fim))

    async def _envia(self, fim: TurnoFim) -> None:
        try:
            await self.cliente.enviar(Tipo.TURNO_FIM, fim)
        except Exception as e:  # sem conexão ou sem ack: a Ayanami fecha o turno (pc_caiu)
            log.info("celular: turno_fim %s não entregue (%s)", fim.turno, type(e).__name__)

    def _tarefa(self, coro: Any) -> None:
        t = asyncio.get_running_loop().create_task(coro)
        self._tarefas.add(t)
        t.add_done_callback(self._tarefas.discard)

    async def aclose(self) -> None:
        for t in list(self._tarefas):
            t.cancel()
        if self._tarefas:
            await asyncio.gather(*self._tarefas, return_exceptions=True)
