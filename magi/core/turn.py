"""Turno de voz do núcleo: máquina de estados do §3.1 e o pipeline do turno (tarefa 1.4, R12.5).

Duas peças:

- ``TurnPipeline``: o "cérebro" do turno, sem I/O de rede. Transcreve (``SttProvider``), corrige
  (``Corrector``), roteia (``Router``) e executa (``ActionRegistry``/``Agent``), devolvendo um
  ``ActionResult``. As dependências chegam por ``TurnDeps`` e podem faltar: cada tarefa seguinte
  (1.5 stt, 1.6 correções, 1.8 roteador, 1.9-1.11 ações, 1.12 voz, 3.x agente) só preenche o seu
  campo, sem mexer no turno.
- ``TurnMachine``: estados de um satélite (``sleeping → listening → thinking → (confirming) →
  speaking → sleeping``), interrupção por nova ativação, escuta curta de confirmação com prazo e
  envio de ``state``/``subtitle``/``mouth``/``card``/``vote`` ao HUD.

A máquina é dirigida por ``handle(msg)`` com as mensagens já decodificadas do satélite
(``magi.common.events.from_event``). O trabalho longo (transcrição, ação, fala) roda numa tarefa
asyncio separada, para que um ``magi-wake`` possa interromper a qualquer momento.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import unicodedata
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from wyoming.audio import AudioChunk, AudioStart

from magi.common.contracts import (
    CONFIRM_TIMEOUT_MS,
    STATE_EXPRESSION,
    ActionRegistry,
    ActionRequest,
    ActionResult,
    Agent,
    AudioEnd,
    AudioEndReason,
    Corrector,
    Expression,
    HudSink,
    IntentId,
    ListenRequest,
    MouthEvent,
    MouthMsg,
    PcmFormat,
    PlaybackDone,
    ProviderError,
    RouteKind,
    Router,
    RouteResult,
    SatelliteHello,
    SatelliteLink,
    SatelliteStatus,
    Speaker,
    StateMsg,
    StopPlayback,
    SttProvider,
    SubtitleMsg,
    ToneMetadata,
    Transcript,
    TurnContext,
    TurnState,
    Verdict,
    VoteMsg,
    WakeEvent,
    WakeSource,
    check_transition,
)

log = logging.getLogger(__name__)

#: Falha ou silêncio na transcrição (R3.5).
SAY_NOT_HEARD = "Não peguei, repete?"
#: Confirmação negada ou expirada (R5.4).
SAY_CANCELLED = "Cancelado."
#: Nada atende o pedido (ação ou agente ainda não plugados).
SAY_UNAVAILABLE = "Ainda não sei fazer isso."
#: "Você quis dizer X?" quando o roteador não traz a frase pronta (R4.2).
SAY_DID_YOU_MEAN = "Você quis dizer isso?"

#: Folga sobre o prazo de confirmação: o satélite encerra a escuta com ``no_speech`` no prazo e
#: o núcleo só cancela sozinho se esse aviso não chegar (satélite travado).
CONFIRM_GRACE_MS = 1_500

#: Palavras aceitas como "confirma" quando o roteador não decide (R5.4).
_YES_WORDS = frozenset({"confirma", "confirmo", "confirmado", "sim"})
#: Palavras que vetam a confirmação mesmo junto de "confirma" ("não confirma").
_NO_WORDS = frozenset({"nao", "cancela", "cancelar", "para"})


@dataclass(slots=True)
class TurnDeps:
    """Pontos de injeção do turno. Campo ``None`` = módulo ainda não existe; o turno degrada.

    - ``stt`` (1.5): sem ele, toda fala vira "não peguei".
    - ``corrector`` (1.6): opcional.
    - ``router`` (1.8): sem ele, todo texto vai ao agente.
    - ``actions`` (1.9-1.11) e ``agent`` (3.x): sem eles, responde ``SAY_UNAVAILABLE``.
    - ``speaker`` (1.12): sem ele, a resposta só aparece na legenda do HUD.
    """

    stt: SttProvider | None = None
    corrector: Corrector | None = None
    router: Router | None = None
    actions: ActionRegistry | None = None
    agent: Agent | None = None
    speaker: Speaker | None = None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if c.isalnum() or c.isspace())


class TurnPipeline:
    """Transcrição → correções → roteador → ação/agente (§3, §4.2). Sem estado entre turnos."""

    def __init__(self, deps: TurnDeps | None = None) -> None:
        self.deps = deps if deps is not None else TurnDeps()

    async def transcribe(self, audio: bytes, fmt: PcmFormat, ctx: TurnContext) -> Transcript:
        """Texto da fala já corrigido. Falha do provedor vira transcrição vazia (R3.5)."""
        stt = self.deps.stt
        if stt is None or not audio:
            return Transcript.raw("")
        try:
            transcript = await stt.transcribe(audio, fmt, personal=True)
        except ProviderError as e:
            log.warning("transcrição falhou (%s): %s", ctx.satellite, e)
            return Transcript.raw("")
        if self.deps.corrector is not None and not transcript.is_empty:
            transcript = await self.deps.corrector.apply(transcript)
        return transcript

    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        """Destino do texto (R4.1-R4.3). Sem roteador, vai ao agente."""
        if self.deps.router is None:
            return RouteResult(RouteKind.AGENT, text)
        return self.deps.router.route(text, ctx)

    async def respond(self, transcript: Transcript, ctx: TurnContext) -> ActionResult:
        """Resposta a uma fala (R3.5, R4.1-R4.3)."""
        if transcript.is_empty:
            return ActionResult(ok=False, speech=SAY_NOT_HEARD, expression=Expression.CONFUSED)
        text = transcript.final
        route = self.route(text, ctx)
        if route.kind is RouteKind.LOCAL:
            assert route.intent is not None
            return await self.run_action(ActionRequest(intent=route.intent, ctx=ctx, text=text))
        if route.kind is RouteKind.ASK:
            assert route.intent is not None
            return ActionResult(
                ok=True,
                speech=route.suggestion or SAY_DID_YOU_MEAN,
                needs_confirmation=True,
                on_confirm=ActionRequest(intent=route.intent, ctx=ctx, text=text),
                expression=Expression.CONFUSED,
            )
        if self.deps.agent is None:
            return ActionResult(ok=False, speech=SAY_UNAVAILABLE, expression=Expression.CONFUSED)
        return await self.deps.agent.answer(text, ctx)

    async def run_action(self, req: ActionRequest) -> ActionResult:
        """Despacha para o ``ActionRegistry``; intenção sem handler responde ``SAY_UNAVAILABLE``."""
        actions = self.deps.actions
        if actions is None or not actions.handles(req.intent.id):
            return ActionResult(ok=False, speech=SAY_UNAVAILABLE, expression=Expression.CONFUSED)
        return await actions.run(req)

    def is_yes(self, transcript: Transcript, ctx: TurnContext) -> bool:
        """A resposta da escuta curta é "confirma"? (R5.4). Roteador primeiro, palavras depois."""
        if transcript.is_empty:
            return False
        route = self.route(transcript.final, ctx)
        if route.intent is not None and route.kind is RouteKind.LOCAL:
            if route.intent.id == IntentId.CONFIRM_YES:
                return True
            if route.intent.id == IntentId.CONFIRM_NO:
                return False
        words = set(_normalize(transcript.final).split())
        return bool(words & _YES_WORDS) and not words & _NO_WORDS


class TurnMachine:
    """Estados do turno de um satélite (§3.1, R5.4, R12.5).

    - ``magi-wake`` em ``sleeping``/``thinking``/``confirming`` → ``listening`` (cancela o que
      estava em curso); em ``speaking`` manda ``magi-stop`` antes (interrupção, R12.5); em
      ``listening`` é ignorado.
    - ``audio-stop`` em ``listening`` → ``thinking`` (ou ``sleeping`` se não houve fala).
    - Resposta com fala → ``speaking``; ``playback-done`` → ``sleeping`` ou, se a resposta pediu
      confirmação, ``confirming`` (manda ``magi-listen`` e arma o prazo). ``playback-done`` fora
      de ``speaking`` é ignorado.
    - Em ``confirming``: fala → ``thinking`` → ação confirmada ou "Cancelado."; silêncio
      (``no_speech``) ou prazo estourado → ``speaking`` com "Cancelado.".
    - Erro inesperado ou satélite desconectado → ``sleeping`` (§9).
    """

    def __init__(
        self,
        link: SatelliteLink,
        hud: HudSink,
        pipeline: TurnPipeline,
        *,
        confirm_timeout_ms: int = CONFIRM_TIMEOUT_MS,
        confirm_grace_ms: int = CONFIRM_GRACE_MS,
    ) -> None:
        self.link = link
        self.hud = hud
        self.pipeline = pipeline
        self.confirm_timeout_ms = confirm_timeout_ms
        self.confirm_grace_ms = confirm_grace_ms
        self._state = TurnState.SLEEPING
        self._task: asyncio.Task[None] | None = None
        self._timer: asyncio.Task[None] | None = None
        self._source = WakeSource.WAKE
        self._started_at = datetime.now(UTC)
        self._fmt: PcmFormat | None = None
        self._audio = bytearray()
        self._recording = False
        self._pending: ActionRequest | None = None
        self._ctx: TurnContext | None = None
        self._vote_open = False
        self._in_call = False

    # -- consulta ------------------------------------------------------------------------------

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def satellite(self) -> str:
        return self.link.hello.satellite

    @property
    def in_call(self) -> bool:
        return self._in_call

    @property
    def busy(self) -> bool:
        """Há trabalho em curso (transcrição, ação ou envio de fala)."""
        return self._task is not None and not self._task.done()

    # -- entrada -------------------------------------------------------------------------------

    async def handle(self, msg: Any) -> None:
        """Processa uma mensagem do satélite (saída de ``from_event``)."""
        match msg:
            case WakeEvent():
                await self.wake(msg.source)
            case AudioStart():
                if self._state in (TurnState.LISTENING, TurnState.CONFIRMING):
                    self._fmt = PcmFormat(rate=msg.rate, width=msg.width, channels=msg.channels)
                    self._audio.clear()
                    self._recording = True
            case AudioChunk():
                if self._recording:
                    if self._fmt is None:
                        self._fmt = PcmFormat(rate=msg.rate, width=msg.width, channels=msg.channels)
                    self._audio += msg.audio
            case AudioEnd():
                await self._audio_end(msg)
            case PlaybackDone():
                if self._state is TurnState.SPEAKING:
                    await self._after_speaking()
                else:
                    log.debug("%s: playback-done em %s ignorado", self.satellite, self._state)
            case MouthEvent():
                await self.hud.send(MouthMsg(msg.level))
            case SatelliteStatus():
                self._in_call = msg.in_call
            case SatelliteHello():
                pass
            case _:
                log.debug("%s: mensagem ignorada: %r", self.satellite, msg)

    async def wake(self, source: WakeSource = WakeSource.WAKE) -> None:
        """Nova ativação: começa a ouvir, interrompendo o que estiver em curso (R1.2, R12.5)."""
        if self._state is TurnState.LISTENING:
            return
        speaking = self._state is TurnState.SPEAKING
        await self._cancel_work()
        if speaking:
            await self.link.send(StopPlayback())
        self._source = source
        self._started_at = datetime.now(UTC)
        await self._go(TurnState.LISTENING)

    async def close(self) -> None:
        """Satélite desconectado: cancela tudo e dorme (§9)."""
        await self._cancel_work()
        if self._state is not TurnState.SLEEPING:
            await self._go(TurnState.SLEEPING)

    # -- transições ----------------------------------------------------------------------------

    async def _go(self, state: TurnState, expression: Expression | None = None) -> None:
        self._state = check_transition(self._state, state)
        log.debug("%s: -> %s", self.satellite, state)
        await self.hud.send(StateMsg(expression or STATE_EXPRESSION[state]))

    def _make_ctx(self, tone: ToneMetadata | None) -> TurnContext:
        return TurnContext(
            satellite=self.satellite,
            source=self._source,
            started_at=self._started_at,
            tone=tone,
            in_call=self._in_call,
        )

    async def _audio_end(self, end: AudioEnd) -> None:
        if not self._recording or self._state not in (TurnState.LISTENING, TurnState.CONFIRMING):
            return
        audio, fmt = bytes(self._audio), self._fmt or PcmFormat()
        self._audio.clear()
        self._recording = False
        silent = not audio or end.reason in (AudioEndReason.NO_SPEECH, AudioEndReason.CANCELLED)

        if self._state is TurnState.LISTENING:
            if silent:
                await self._go(TurnState.SLEEPING)
                return
            self._ctx = ctx = self._make_ctx(end.tone)
            await self._go(TurnState.THINKING)
            self._start(self._think(audio, fmt, ctx))
            return

        # confirming
        self._cancel_timer()
        pending, self._pending = self._pending, None
        ctx = self._ctx or self._make_ctx(end.tone)
        if silent or pending is None:
            self._start(self._deliver(await self._cancelled()))
            return
        await self._go(TurnState.THINKING)
        self._start(self._confirm(audio, fmt, pending, ctx))

    async def _after_speaking(self) -> None:
        """Fim da fala (ou nada a falar): confirma se há pedido pendente, senão dorme."""
        if self._pending is None:
            await self._go(TurnState.SLEEPING)
            return
        await self._go(TurnState.CONFIRMING)
        await self.link.send(ListenRequest(timeout_ms=self.confirm_timeout_ms))
        self._timer = asyncio.create_task(self._confirm_deadline())

    async def _confirm_deadline(self) -> None:
        await asyncio.sleep((self.confirm_timeout_ms + self.confirm_grace_ms) / 1000)
        if self._state is not TurnState.CONFIRMING:
            return
        self._timer = None
        self._recording = False
        self._audio.clear()
        self._pending = None
        log.info("%s: confirmação expirou", self.satellite)
        self._start(self._deliver(await self._cancelled()))

    async def _cancelled(self) -> ActionResult:
        await self._close_vote(Verdict.DENIED)
        return ActionResult(ok=True, speech=SAY_CANCELLED)

    async def _close_vote(self, verdict: Verdict) -> None:
        if self._vote_open:
            self._vote_open = False
            await self.hud.send(VoteMsg(verdict))

    # -- trabalho em tarefa --------------------------------------------------------------------

    def _start(self, coro: Coroutine[Any, Any, None]) -> None:
        self._task = asyncio.create_task(self._guard(coro))

    async def _guard(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s: erro no turno", self.satellite)
            self._pending = None
            await self._close_vote(Verdict.DENIED)
            if self._state is not TurnState.SLEEPING:
                await self._go(TurnState.SLEEPING)

    async def _think(self, audio: bytes, fmt: PcmFormat, ctx: TurnContext) -> None:
        transcript = await self.pipeline.transcribe(audio, fmt, ctx)
        result = await self.pipeline.respond(transcript, ctx)
        await self._deliver(result)

    async def _confirm(self, audio: bytes, fmt: PcmFormat, pending: ActionRequest, ctx: TurnContext) -> None:
        transcript = await self.pipeline.transcribe(audio, fmt, ctx)
        if not self.pipeline.is_yes(transcript, ctx):
            await self._deliver(await self._cancelled())
            return
        await self._close_vote(Verdict.APPROVED)
        result = await self.pipeline.run_action(pending)
        await self._deliver(result)

    async def _deliver(self, result: ActionResult) -> None:
        """Mostra e fala a resposta. Estado de partida: ``thinking`` ou ``confirming``."""
        if result.needs_confirmation:
            self._pending = result.on_confirm
            if result.dangerous:
                self._vote_open = True
                await self.hud.send(VoteMsg(Verdict.PENDING))
        for card in result.cards:
            await self.hud.send(card)
        if result.speech or result.full_text:
            await self.hud.send(SubtitleMsg(result.speech, result.full_text))
        speaker = self.pipeline.deps.speaker
        if result.speech and speaker is not None:
            await self._go(TurnState.SPEAKING, result.expression)
            # Último passo da tarefa: a continuação vem com ``playback-done`` (ou nova ativação).
            await speaker.say(result.speech, self.link, personal=True)
            return
        await self._after_speaking()

    def _cancel_timer(self) -> None:
        if self._timer is not None and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None

    async def _cancel_work(self) -> None:
        """Cancela tarefa e prazo em curso e descarta gravação e confirmação pendentes."""
        self._cancel_timer()
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._recording = False
        self._audio.clear()
        self._pending = None
        await self._close_vote(Verdict.DENIED)
