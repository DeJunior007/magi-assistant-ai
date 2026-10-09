"""Turno de voz do núcleo: máquina de estados do §3.1 e o pipeline do turno (tarefa 1.4, R12.5).

Duas peças:

- ``TurnPipeline``: o "cérebro" do turno, sem I/O de rede. Transcreve (``SttProvider``), corrige
  (``Corrector``), roteia (``Router``) e executa (``ActionRegistry``/``Agent``), devolvendo um
  ``ActionResult``. As dependências chegam por ``TurnDeps`` e podem faltar: cada tarefa seguinte
  (1.5 stt, 1.6 correções, 1.8 roteador, 1.9-1.11 ações, 1.12 voz, 3.x agente) só preenche o seu
  campo, sem mexer no turno.
- ``TurnMachine``: estados de um satélite (``sleeping → listening → thinking → (confirming) →
  speaking → (followup) → sleeping``), interrupção por nova ativação, escuta curta de confirmação
  com prazo, janela de continuação sem wake word (1.20) e envio de
  ``state``/``subtitle``/``mouth``/``card``/``vote`` ao HUD.

A máquina é dirigida por ``handle(msg)`` com as mensagens já decodificadas do satélite
(``magi.common.events.from_event``). O trabalho longo (transcrição, ação, fala) roda numa tarefa
asyncio separada, para que um ``magi-wake`` possa interromper a qualquer momento.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
import logging
import time
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from wyoming.audio import AudioChunk, AudioStart

from magi.common.contracts import (
    ARG_ALSO_YES,
    ARG_DECLINED,
    ARG_QUIET,
    CONFIRM_TIMEOUT_MS,
    MAX_RECORDING_MS,
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
    SpeechMsg,
    StateMsg,
    StopPlayback,
    SttProvider,
    ToneMetadata,
    Transcript,
    TurnContext,
    TurnRecord,
    TurnsRepo,
    TurnState,
    Verdict,
    VoteMsg,
    WakeEvent,
    WakeSource,
    check_transition,
)
from magi.core.compose import compose, subtitle
from magi.core.early import EARLY_SPEECH, EarlySpeech
from magi.core.i18n import tr_result
from magi.core.utterance import UtteranceSaver, normalize_pcm16

if TYPE_CHECKING:
    from magi.core.proactive.sink import Offer

log = logging.getLogger(__name__)

#: Estados em que o núcleo aceita gravação do satélite.
_RECORDING_STATES = frozenset({TurnState.LISTENING, TurnState.CONFIRMING, TurnState.FOLLOWUP})

#: Falha ou silêncio na transcrição (R3.5).
SAY_NOT_HEARD = "Não peguei, repete?"
#: Confirmação negada ou expirada (R5.4).
SAY_CANCELLED = "Cancelado."
#: Resposta a um "não" para uma pergunta proativa (5.4).
SAY_DECLINED = "Beleza."
#: Nada atende o pedido (ação ou agente ainda não plugados).
SAY_UNAVAILABLE = "Ainda não sei fazer isso."
#: "Você quis dizer X?" quando o roteador não traz a frase pronta (R4.2).
SAY_DID_YOU_MEAN = "Você quis dizer isso?"
#: Por quanto tempo uma confirmação interrompida (nova ativação no meio da pergunta) ou expirada
#: ainda vale para um "sim"/"não" dito no turno seguinte.
STALE_CONFIRM_S = 20.0
#: Respostas soltas que só fazem sentido em resposta a uma pergunta.
_CONFIRM_INTENTS = frozenset({IntentId.CONFIRM_YES, IntentId.CONFIRM_NO})

#: Folga sobre o prazo de confirmação: o satélite encerra a escuta com ``no_speech`` no prazo e
#: o núcleo só cancela sozinho se esse aviso não chegar (satélite travado).
CONFIRM_GRACE_MS = 1_500

#: Janela de continuação padrão (``[conversation] followup_s``, 1.20): prazo para começar a falar
#: depois que a Magui termina a resposta.
FOLLOWUP_S = 3.0
#: Clique no rosto do HUD (``push_to_talk``): prazo para começar a falar depois do clique.
TAP_LISTEN_MS = 6_000
#: Quanto tempo o rosto fica ``happy`` ao ser dispensada, antes de dormir (sem fala, 1.20).
DISMISS_FACE_S = 0.8
#: Frases que dispensam a Magui quando são a fala inteira (normalizadas, 1.20). "pode ir" e
#: "esquece" só valem fora da confirmação (lá são "confirma"/"cancela", R5.4).
DISMISS_PHRASES = frozenset({
    "valeu", "obrigado", "obrigada", "brigado", "brigada", "muito obrigado", "muito obrigada",
    "so isso", "e so isso", "pode ir", "dispensa", "dispensada", "tchau", "nada nao", "nada",
    "esquece", "falou",
})
#: Vocativos ignorados nas frases de dispensa ("valeu, Magui", "valeu, Condessa").
_DISMISS_EXTRA = frozenset({"magui", "magi", "maggie", "condessa", "ei", "hey", "oi", "oh"})

#: Palavras aceitas como "confirma" quando o roteador não decide (R5.4).
_YES_WORDS = frozenset({"confirma", "confirmo", "confirmado", "sim"})
#: Palavras que vetam a confirmação mesmo junto de "confirma" ("não confirma").
_NO_WORDS = frozenset({"nao", "cancela", "cancelar", "para"})
#: Vocativos ignorados ao comparar com ``ARG_ALSO_YES`` ("Condessa, próxima").
_WAKE_WORDS = frozenset({"condessa", "magui", "hey", "oi", "ei"})


@dataclass(slots=True)
class TurnDeps:
    """Pontos de injeção do turno. Campo ``None`` = módulo ainda não existe; o turno degrada.

    - ``stt`` (1.5): sem ele, toda fala vira "não peguei".
    - ``corrector`` (1.6): opcional.
    - ``router`` (1.8): sem ele, todo texto vai ao agente.
    - ``actions`` (1.9-1.11) e ``agent`` (3.x): sem eles, responde ``SAY_UNAVAILABLE``.
    - ``speaker`` (1.12): sem ele, a resposta só aparece na legenda do HUD.
    - ``turns`` (4.1): histórico local de turnos (R11.6), gravado em segundo plano.
    - ``mood`` (4.3): ``magi.memory.mood.MoodTracker``; sem ele, ``ctx.mood`` fica no padrão.
    - ``prewarm`` (1.23): disparado em segundo plano a cada ativação, abre as conexões HTTP dos
      provedores (STT/TTS/agente) enquanto o usuário ainda fala; erro é ignorado.
    - ``save_audio`` (1.26): ``[debug] save_audio``; grava cada fala enviada ao STT em WAV.
    - ``learning`` (Learning Mode, LM1.3): chamado **depois** da entrega de um turno de voz com
      ``(transcript, ctx, result)``; síncrono, só agenda (``magi.learning.wiring``). Só existe com
      ``[learning] enabled``; ``None`` = nada muda.
    - ``revive``: sem STT (ou agente) porque o keyring estava trancado na subida, tenta reler as
      chaves e remontar antes de responder "não peguei" (``Core.revive``, com intervalo mínimo).
    """

    stt: SttProvider | None = None
    corrector: Corrector | None = None
    router: Router | None = None
    actions: ActionRegistry | None = None
    agent: Agent | None = None
    speaker: Speaker | None = None
    turns: TurnsRepo | None = None
    mood: Any = None
    prewarm: Callable[[], Awaitable[Any]] | None = None
    save_audio: UtteranceSaver | None = None
    learning: Callable[[Transcript, TurnContext, ActionResult], None] | None = None
    revive: Callable[[], Awaitable[bool]] | None = None


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if c.isalnum() or c.isspace())


def is_dismissal(text: str) -> bool:
    """A fala inteira é uma dispensa ("valeu", "só isso", "tchau"...)? (1.20)."""
    words = [w for w in _normalize(text).split() if w not in _DISMISS_EXTRA]
    return bool(words) and " ".join(words) in DISMISS_PHRASES


def followup_ms_from_config(raw: Mapping[str, Any] | None) -> int | None:
    """Janela de continuação em ms a partir de ``[conversation]`` (``followup``, ``followup_s``).
    ``None`` = desligada. Sem a seção, liga com ``FOLLOWUP_S``."""
    conv = (raw or {}).get("conversation") or {}
    if not isinstance(conv, Mapping) or not conv.get("followup", True):
        return None
    try:
        secs = float(conv.get("followup_s", FOLLOWUP_S))
    except (TypeError, ValueError):
        log.warning("[conversation] followup_s inválido; usando %.1f s", FOLLOWUP_S)
        secs = FOLLOWUP_S
    return round(secs * 1000) if secs > 0 else None


def _quiet(pending: ActionRequest | None) -> bool:
    return pending is not None and bool(pending.args.get(ARG_QUIET))


class TurnPipeline:
    """Transcrição → correções → roteador → ação/agente (§3, §4.2). Sem estado entre turnos."""

    def __init__(self, deps: TurnDeps | None = None) -> None:
        self.deps = deps if deps is not None else TurnDeps()
        self._tasks: set[asyncio.Task[None]] = set()

    def prewarm(self) -> None:
        """Abre as conexões dos provedores em segundo plano (1.23). Não bloqueia nem levanta."""
        warm = self.deps.prewarm
        if warm is None or any(t.get_name() == "prewarm" for t in self._tasks):
            return
        task = asyncio.create_task(self._prewarm(warm), name="prewarm")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _prewarm(warm: Callable[[], Awaitable[Any]]) -> None:
        try:
            await warm()
        except Exception as e:  # noqa: BLE001 - aquecimento é só otimização
            log.debug("pré-aquecimento falhou: %s", e)

    def open_stream(self, fmt: PcmFormat) -> Any:
        """Transcrição enquanto fala (1.25): ``SttStream`` se o STT a tem ligada, senão ``None``."""
        opener = getattr(self.deps.stt, "open_stream", None)
        if opener is None:
            return None
        try:
            return opener(fmt, personal=True)
        except Exception as e:  # noqa: BLE001 - otimização: o turno segue pelo caminho antigo
            log.debug("transcrição enquanto fala não abriu: %s", e)
            return None

    async def transcribe(
        self, audio: bytes, fmt: PcmFormat, ctx: TurnContext, *, stream: Any = None
    ) -> Transcript:
        """Texto da fala já corrigido. Falha do provedor vira transcrição vazia (R3.5).
        ``stream`` (1.25): sessão aberta na gravação; só espera o texto final e, se ela falhou,
        estourou o tempo ou veio vazia, manda o áudio inteiro como antes."""
        stt = self.deps.stt
        if stt is None and audio and self.deps.revive is not None:
            try:
                await self.deps.revive()  # keyring destravado depois da subida: relê as chaves
            except Exception as e:  # noqa: BLE001 - a fala segue como "não peguei"
                log.warning("releitura das chaves falhou: %s", e)
            stt = self.deps.stt
        if stt is None or not audio:
            if stream is not None:
                await stream.cancel()
            return Transcript.raw("")
        transcript = await stream.finish() if stream is not None else None
        sent, gain_db = (audio, 0.0) if transcript is not None else normalize_pcm16(audio, fmt)
        if self.deps.save_audio is not None:
            self.deps.save_audio.save(sent, fmt)
        seconds = len(audio) / max(1, fmt.rate * fmt.width * fmt.channels)
        if transcript is None:
            try:
                transcript = await stt.transcribe(sent, fmt, personal=True)
            except ProviderError as e:
                log.warning("transcrição falhou (%s): %s", ctx.satellite, e)
                return Transcript.raw("")
        log.info('%s: ouvi "%s" (%.1f s de áudio%s)', ctx.satellite, transcript.heard, seconds,
                 f", ganho +{gain_db:.1f} dB" if gain_db else "")
        if self.deps.corrector is not None and not transcript.is_empty:
            transcript = await self.deps.corrector.apply(transcript)
            if transcript.final != transcript.heard:
                log.info('%s: corrigido para "%s"', ctx.satellite, transcript.final)
        return transcript

    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        """Destino do texto (R4.1-R4.3). Sem roteador, vai ao agente."""
        if self.deps.router is None:
            return RouteResult(RouteKind.AGENT, text)
        return self.deps.router.route(text, ctx)

    async def respond(self, transcript: Transcript, ctx: TurnContext) -> ActionResult:
        """Resposta a uma fala (R3.5, R4.1-R4.3).

        Resposta com ``redo_text`` (correção, R3.3) refaz o turno uma vez com esse texto, sem
        passar de novo pelo ``Corrector``; a fala fica "<fala da correção> <fala refeita>".
        """
        ctx = await self._observe_mood(transcript, ctx)
        result, route = await self._respond(transcript, ctx)
        if result.redo_text:
            redo = transcript.with_final(result.redo_text)
            again, route = await self._respond(redo, ctx)
            speech = " ".join(s for s in (result.speech, again.speech) if s)
            result, transcript = dataclasses.replace(again, speech=speech, redo_text=result.redo_text), redo
        self._log_turn(ctx, route, result)
        self._record(transcript, ctx, result, route)
        return result

    @staticmethod
    def _log_turn(ctx: TurnContext, route: RouteResult | None, result: ActionResult) -> None:
        """Uma linha por turno no INFO: rota/intenção e a fala da resposta (1.26)."""
        if route is None:
            where = "nenhuma (sem texto)"
        elif route.intent is not None:
            where = f"{route.kind.value}:{route.intent.id} ({route.score:.0f})"
        else:
            where = route.kind.value
        log.info('%s: rota %s -> "%s"', ctx.satellite, where, _short(result.speech))

    async def _observe_mood(self, transcript: Transcript, ctx: TurnContext) -> TurnContext:
        """Atualiza o termômetro com os sinais do turno e põe o nível no contexto (R13.3-R13.4)."""
        mood = self.deps.mood
        if mood is None or transcript.is_empty:
            return ctx
        try:
            level = await mood.observe(transcript.final, ctx)
        except Exception:
            log.exception("falha ao atualizar o humor")
            return ctx
        return dataclasses.replace(ctx, mood=level)

    def _record(
        self, transcript: Transcript, ctx: TurnContext, result: ActionResult, route: RouteResult | None
    ) -> None:
        """Grava o turno em ``turns`` sem segurar a resposta (R11.6)."""
        if self.deps.turns is None or transcript.is_empty:
            return
        intent = route.intent.id if route is not None and route.intent is not None else None
        rec = TurnRecord(
            satellite=ctx.satellite,
            text_heard=transcript.heard,
            text_final=transcript.final,
            at=ctx.started_at,
            intent=intent,
            routed_local=route is not None and route.kind is RouteKind.LOCAL,
            reply=result.full_text or result.speech,
            mood=ctx.mood,
        )
        task = asyncio.create_task(self._save_turn(self.deps.turns, rec))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _save_turn(repo: TurnsRepo, rec: TurnRecord) -> None:
        try:
            await repo.add(rec)
        except Exception:
            log.exception("falha ao gravar o turno no histórico")

    async def _respond(
        self, transcript: Transcript, ctx: TurnContext
    ) -> tuple[ActionResult, RouteResult | None]:
        if transcript.is_empty:
            return ActionResult(ok=False, speech=SAY_NOT_HEARD, expression=Expression.CONFUSED), None
        text = transcript.final
        route = self._settle(self.route(text, ctx))
        return await self._dispatch(text, route, ctx), route

    def _settle(self, route: RouteResult) -> RouteResult:
        """Com agente, o "você quis dizer X?" vira pergunta ao agente, que tem as mesmas
        ferramentas e o contexto da conversa; só ação perigosa ainda pergunta (R4.2, R5.3).
        "Sim"/"não" soltos, fora de uma confirmação, também vão ao agente: respondem ao que ele
        perguntou no turno anterior."""
        if self.deps.agent is None or route.intent is None:
            return route
        if route.kind is RouteKind.ASK and not route.intent.danger:
            return RouteResult(RouteKind.AGENT, route.text, route.score)
        if route.intent.id in _CONFIRM_INTENTS:
            actions = self.deps.actions
            if actions is None or not actions.handles(route.intent.id):
                return RouteResult(RouteKind.AGENT, route.text, route.score)
        return route

    def confirm_answer(
        self, transcript: Transcript, ctx: TurnContext, also_yes: Iterable[str] = ()
    ) -> bool | None:
        """``True``/``False`` se a fala é só um "sim"/"não" (roteador local, nota de execução) ou
        uma das ``also_yes`` da pergunta ("próxima" no rádio); ``None`` se é outra coisa."""
        if transcript.is_empty:
            return None
        words = [w for w in _normalize(transcript.final).split() if w not in _WAKE_WORDS]
        if " ".join(words) in also_yes:
            return True
        route = self.route(transcript.final, ctx)
        if route.kind is RouteKind.LOCAL and route.intent is not None and route.intent.id in _CONFIRM_INTENTS:
            return route.intent.id == IntentId.CONFIRM_YES
        return None

    async def _dispatch(self, text: str, route: RouteResult, ctx: TurnContext) -> ActionResult:
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

    def after_delivery(self, transcript: Transcript, ctx: TurnContext, result: ActionResult) -> None:
        """Gancho do Learning Mode (LM1.3) depois da entrega ao TTS/HUD. Nunca levanta."""
        hook = self.deps.learning
        if hook is None:
            return
        try:
            hook(transcript, ctx, result)
        except Exception:
            log.exception("learning: falha no gancho do turno")

    def is_no(self, transcript: Transcript, ctx: TurnContext) -> bool:
        """A resposta é "não"/"cancela"? (pergunta proativa, 5.4)."""
        if transcript.is_empty:
            return False
        route = self.route(transcript.final, ctx)
        if route.intent is not None and route.kind is RouteKind.LOCAL:
            if route.intent.id == IntentId.CONFIRM_NO:
                return True
        return bool(set(_normalize(transcript.final).split()) & _NO_WORDS)

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
    - Janela de continuação (1.20, ``followup_ms``): fim de uma resposta sem confirmação pendente
      → ``followup`` (``magi-listen`` com ``reason="followup"``, sem bip, rosto ``listening``).
      Fala → turno normal, que reabre a janela no fim; silêncio → ``sleeping`` calado. Fora em
      call no Discord e depois de aviso proativo ou de "Cancelado." por silêncio.
    - Pergunta proativa (``announce(..., offer=...)``, 5.4): fim da fala → ``confirming``; "sim"
      → ``offer.accept()`` (resultado falado), "não" → ``offer.decline()`` + "Beleza.", outra
      coisa → turno normal; silêncio ou prazo → ``sleeping`` calado.
    - Dispensa ("valeu", "só isso"... como frase inteira, em qualquer turno normal) → rosto
      ``happy`` por um instante e ``sleeping``, sem fala. Ativação sem fala → ``sleeping`` calado.
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
        followup_ms: int | None = None,
        dismiss_face_s: float = DISMISS_FACE_S,
    ) -> None:
        self.link = link
        self.hud = hud
        self.pipeline = pipeline
        self.confirm_timeout_ms = confirm_timeout_ms
        self.confirm_grace_ms = confirm_grace_ms
        self.followup_ms = followup_ms
        self.dismiss_face_s = dismiss_face_s
        self._followup = False  # a fala em curso abre a janela de continuação ao terminar
        self._state = TurnState.SLEEPING
        self._task: asyncio.Task[None] | None = None
        self._timer: asyncio.Task[None] | None = None
        self._source = WakeSource.WAKE
        self._started_at = datetime.now(UTC)
        self._fmt: PcmFormat | None = None
        self._audio = bytearray()
        self._recording = False
        self._stream: Any = None  # transcrição enquanto fala da gravação atual (1.25)
        self._pending: ActionRequest | None = None
        # confirmação interrompida/expirada e quando (``STALE_CONFIRM_S``)
        self._stale: tuple[ActionRequest, float] | None = None
        self._offer: Offer | None = None  # pergunta proativa esperando resposta (5.4)
        self._ctx: TurnContext | None = None
        self._vote_open = False
        self._in_call = False
        self._last_text: str | None = None
        self._last_at: datetime | None = None
        # legenda sincronizada: avisos de frase de uma fala interrompida não chegam ao HUD
        self._speech_gen = 0
        self._hud_tasks: set[asyncio.Task[None]] = set()

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
                if self._state in _RECORDING_STATES:
                    self._fmt = PcmFormat(rate=msg.rate, width=msg.width, channels=msg.channels)
                    self._audio.clear()
                    self._recording = True
                    await self._open_stream(self._fmt)
            case AudioChunk():
                if self._recording:
                    if self._fmt is None:
                        self._fmt = PcmFormat(rate=msg.rate, width=msg.width, channels=msg.channels)
                    if self._stream is None and not self._audio:
                        await self._open_stream(self._fmt)
                    self._audio += msg.audio
                    if self._stream is not None:
                        self._stream.feed(msg.audio)
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
        self.pipeline.prewarm()
        await self._go(TurnState.LISTENING)

    async def listen_now(self) -> bool:
        """Clique no rosto do HUD (``push_to_talk``): ativa sem wake word. Como o satélite não
        grava sozinho nesse caso (o atalho dele é de segurar), pede uma escuta com ``magi-listen``
        e ela termina pelo VAD, como na janela de continuação. ``False`` = já está ouvindo."""
        if self._state in _RECORDING_STATES:
            return False
        await self.wake(WakeSource.PTT)
        await self.link.send(ListenRequest(timeout_ms=TAP_LISTEN_MS, reason="tap"))
        self._timer = asyncio.create_task(self._tap_deadline())
        return True

    async def _tap_deadline(self) -> None:
        """Rede de segurança da escuta pelo clique: sem gravação no prazo (satélite não respondeu),
        ou passada a gravação máxima, dorme calado."""
        await asyncio.sleep((TAP_LISTEN_MS + self.confirm_grace_ms) / 1000)
        if self._recording:
            await asyncio.sleep(max(0, MAX_RECORDING_MS - TAP_LISTEN_MS) / 1000)
        if self._state is not TurnState.LISTENING:
            return
        self._timer = None
        self._recording = False
        self._audio.clear()
        await self._drop_stream()
        log.info("%s: escuta pelo clique expirou sem resposta do satélite", self.satellite)
        await self._go(TurnState.SLEEPING)

    async def announce(
        self, text: str, expression: Expression | None = None, *, offer: Offer | None = None
    ) -> bool:
        """Fala proativa (R15.1, ``magi.core.proactive``): só começa com o satélite dormindo e
        livre, nunca corta uma fala ou turno. ``False`` = ocupado agora (tente depois). Uma
        ativação durante o aviso interrompe como numa resposta comum. ``offer``: depois da fala,
        escuta curta da resposta (5.4)."""
        if self._state is not TurnState.SLEEPING or self.busy:
            return False
        said = compose(ActionResult(ok=True, speech=text))
        for card in said.cards:
            await self.hud.send(card)
        if (sub := subtitle(said)) is not None:
            await self.hud.send(sub)
        speaker = self.pipeline.deps.speaker
        if speaker is None or not said.speech:
            return True
        self._followup = False  # aviso não abre janela de continuação
        self._offer = offer
        await self._go(TurnState.SPEAKING, expression)
        # A volta a ``sleeping`` vem com ``playback-done`` (ou erro, via ``_guard``).
        self._start(speaker.say(said.speech, self.link, personal=False, **self._captions(speaker.say)))
        return True

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
            previous_text=self._last_text,
            previous_at=self._last_at,
        )

    async def _open_stream(self, fmt: PcmFormat) -> None:
        await self._drop_stream()
        self._stream = self.pipeline.open_stream(fmt)

    async def _drop_stream(self) -> None:
        """Fecha a transcrição enquanto fala (silêncio, interrupção, nova gravação)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            await stream.cancel()

    async def _audio_end(self, end: AudioEnd) -> None:
        if not self._recording or self._state not in _RECORDING_STATES:
            return
        audio, fmt = bytes(self._audio), self._fmt or PcmFormat()
        # Fica em ``_stream`` até a próxima gravação ou ``_cancel_work``: se o turno for
        # interrompido antes de esperar o texto, a sessão ainda é fechada.
        stream = self._stream
        self._audio.clear()
        self._recording = False
        silent = (
            not audio
            or end.reason in (AudioEndReason.NO_SPEECH, AudioEndReason.CANCELLED)
            # apertou o atalho e soltou calado: o VAD do satélite não ouviu voz nenhuma
            or (
                end.reason is AudioEndReason.PTT_RELEASE
                and end.tone is not None
                and end.tone.duration_ms == 0
            )
        )

        if self._state in (TurnState.LISTENING, TurnState.FOLLOWUP):
            followup = self._state is TurnState.FOLLOWUP
            self._cancel_timer()
            if silent:
                await self._drop_stream()
                await self._go(TurnState.SLEEPING)
                return
            self._ctx = ctx = self._make_ctx(end.tone)
            await self._go(TurnState.THINKING)
            self._start(self._think(audio, fmt, ctx, followup=followup, stream=stream))
            return

        # confirming
        self._cancel_timer()
        pending, self._pending = self._pending, None
        offer, self._offer = self._offer, None
        ctx = self._ctx or self._make_ctx(end.tone)
        if offer is not None:
            if silent:
                await self._drop_stream()
                await self._go(TurnState.SLEEPING)
                return
            self._ctx = ctx = self._make_ctx(end.tone)
            await self._go(TurnState.THINKING)
            self._start(self._answer_offer(audio, fmt, offer, ctx, stream=stream))
            return
        if silent or pending is None:
            await self._drop_stream()
            if _quiet(pending):
                await self._go(TurnState.SLEEPING)
                return
            self._start(self._deliver(await self._cancelled(), followup=False))
            return
        await self._go(TurnState.THINKING)
        self._start(self._confirm(audio, fmt, pending, ctx, stream=stream))

    async def _after_speaking(self) -> None:
        """Fim da fala (ou nada a falar): confirma se há pedido pendente; senão abre a janela de
        continuação (se ligada e fora de call) ou dorme."""
        followup, self._followup = self._followup, False
        if self._pending is not None or self._offer is not None:
            await self._go(TurnState.CONFIRMING)
            await self.link.send(ListenRequest(timeout_ms=self.confirm_timeout_ms))
            self._timer = asyncio.create_task(self._confirm_deadline())
            return
        if followup and self.followup_ms and not self._in_call and self._state is not TurnState.CONFIRMING:
            await self._go(TurnState.FOLLOWUP)
            await self.link.send(ListenRequest(timeout_ms=self.followup_ms, reason="followup"))
            self._timer = asyncio.create_task(self._followup_deadline())
            return
        await self._go(TurnState.SLEEPING)

    async def _followup_deadline(self) -> None:
        """Rede de segurança se o satélite não encerrar a escuta: sem gravação no prazo, ou
        passada a gravação máxima, dorme calado."""
        followup_ms = self.followup_ms or 0
        await asyncio.sleep((followup_ms + self.confirm_grace_ms) / 1000)
        if self._recording:
            await asyncio.sleep(max(0, MAX_RECORDING_MS - followup_ms) / 1000)
        if self._state is not TurnState.FOLLOWUP:
            return
        self._timer = None
        self._recording = False
        self._audio.clear()
        await self._drop_stream()
        log.info("%s: janela de continuação expirou sem resposta do satélite", self.satellite)
        await self._go(TurnState.SLEEPING)

    async def _confirm_deadline(self) -> None:
        await asyncio.sleep((self.confirm_timeout_ms + self.confirm_grace_ms) / 1000)
        if self._state is not TurnState.CONFIRMING:
            return
        self._timer = None
        self._recording = False
        self._audio.clear()
        await self._drop_stream()
        pending, self._pending = self._pending, None
        self._keep_stale(pending)
        log.info("%s: confirmação expirou", self.satellite)
        if self._offer is not None or _quiet(pending):  # sem resposta: dorme calado
            self._offer = None
            await self._go(TurnState.SLEEPING)
            return
        self._start(self._deliver(await self._cancelled(), followup=False))

    def _keep_stale(self, pending: ActionRequest | None) -> None:
        """Guarda a confirmação perdida para um "sim" logo depois; ação perigosa não (R5.3)."""
        if pending is not None and not pending.intent.danger:
            self._stale = (pending, time.monotonic())

    def _take_stale(self) -> ActionRequest | None:
        stale, self._stale = self._stale, None
        if stale is None or time.monotonic() - stale[1] > STALE_CONFIRM_S:
            return None
        return stale[0]

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
            self._offer = None
            await self._close_vote(Verdict.DENIED)
            if self._state is not TurnState.SLEEPING:
                await self._go(TurnState.SLEEPING)

    async def _think(
        self, audio: bytes, fmt: PcmFormat, ctx: TurnContext, *, followup: bool = False, stream: Any = None
    ) -> None:
        transcript = await self.pipeline.transcribe(audio, fmt, ctx, stream=stream)
        if is_dismissal(transcript.final):
            await self._dismiss()
            return
        if followup and transcript.is_empty:
            # ruído na janela de continuação: nada de "não peguei", só volta a dormir
            await self._go(TurnState.SLEEPING)
            return
        stale = self._take_stale()
        also = stale.args.get(ARG_ALSO_YES, ()) if stale is not None else ()
        if stale is not None and (yes := self.pipeline.confirm_answer(transcript, ctx, also)) is not None:
            # "sim"/"não" à pergunta que a nova ativação interrompeu (ou que expirou)
            log.info("%s: resposta à confirmação anterior: %s", self.satellite, "sim" if yes else "não")
            if yes:
                await self._deliver(await self.pipeline.run_action(stale))
            else:
                say = str(stale.args.get(ARG_DECLINED) or SAY_CANCELLED)
                await self._deliver(ActionResult(ok=True, speech=say))
            return
        early = self._early_speech()
        token = EARLY_SPEECH.set(early)
        try:
            try:
                result = await self.pipeline.respond(transcript, ctx)
            finally:
                EARLY_SPEECH.reset(token)
            text = result.redo_text or transcript.final
            if text.strip():
                # Texto efetivo deste turno: o próximo turno o recebe em ``ctx.previous_text``.
                self._last_text, self._last_at = text, ctx.started_at
            await self._deliver(result, early=early)
            self.pipeline.after_delivery(transcript, ctx, result)
        finally:
            if early is not None:
                early.cancel()  # interrupção/erro no meio: para o envio (fim normal: já terminou)

    def _early_speech(self) -> EarlySpeech | None:
        """Fala por frase em streaming (1.24): o agente fala a 1ª frase enquanto ainda gera."""
        speaker = self.pipeline.deps.speaker
        say_stream = getattr(speaker, "say_stream", None)
        if say_stream is None:
            return None

        async def play(texts: AsyncIterator[str]) -> None:
            if self._state is not TurnState.SPEAKING:
                await self._go(TurnState.SPEAKING)
            await say_stream(texts, self.link, personal=True, **self._captions(say_stream))

        return EarlySpeech(play)

    async def _dismiss(self) -> None:
        """Dispensada: rosto ``happy`` por um instante e dorme, sem fala (1.20)."""
        log.info("%s: dispensada", self.satellite)
        await self.hud.send(StateMsg(Expression.HAPPY))
        await asyncio.sleep(self.dismiss_face_s)
        await self._go(TurnState.SLEEPING)

    async def _confirm(
        self, audio: bytes, fmt: PcmFormat, pending: ActionRequest, ctx: TurnContext, *, stream: Any = None
    ) -> None:
        transcript = await self.pipeline.transcribe(audio, fmt, ctx, stream=stream)
        answer = self.pipeline.confirm_answer(transcript, ctx, pending.args.get(ARG_ALSO_YES, ()))
        if _quiet(pending) and answer is None and not self.pipeline.is_no(transcript, ctx):
            if transcript.is_empty:  # ruído: como silêncio, dorme calado
                await self._go(TurnState.SLEEPING)
                return
            # Pergunta leve e a resposta é outra coisa ("conta mais dessa"): turno normal.
            result = await self.pipeline.respond(transcript, ctx)
            self._last_text, self._last_at = result.redo_text or transcript.final, ctx.started_at
            await self._deliver(result)
            self.pipeline.after_delivery(transcript, ctx, result)
            return
        if answer is not True and not self.pipeline.is_yes(transcript, ctx):
            if declined := pending.args.get(ARG_DECLINED):
                await self._deliver(ActionResult(ok=True, speech=str(declined)), followup=False)
                return
            await self._deliver(await self._cancelled())
            return
        await self._close_vote(Verdict.APPROVED)
        result = await self.pipeline.run_action(pending)
        await self._deliver(result)

    async def _answer_offer(
        self, audio: bytes, fmt: PcmFormat, offer: Offer, ctx: TurnContext, *, stream: Any = None
    ) -> None:
        transcript = await self.pipeline.transcribe(audio, fmt, ctx, stream=stream)
        if self.pipeline.is_yes(transcript, ctx):
            await self._deliver(await offer.accept())
            return
        if transcript.is_empty:  # ruído: como silêncio, dorme calado
            await self._go(TurnState.SLEEPING)
            return
        if self.pipeline.is_no(transcript, ctx):
            if offer.decline is not None:
                offer.decline()
            await self._deliver(ActionResult(ok=True, speech=SAY_DECLINED), followup=False)
            return
        # Outra coisa ("qual a temperatura da GPU?"): turno normal.
        result = await self.pipeline.respond(transcript, ctx)
        self._last_text, self._last_at = result.redo_text or transcript.final, ctx.started_at
        await self._deliver(result)
        self.pipeline.after_delivery(transcript, ctx, result)

    async def _deliver(
        self, result: ActionResult, *, followup: bool = True, early: EarlySpeech | None = None
    ) -> None:
        """Mostra e fala a resposta. Estado de partida: ``thinking`` ou ``confirming``.
        ``followup``: ao terminar, abre a janela de continuação (1.20). A resposta passa por
        ``compose`` (3.6): fala ≤ 2 frases sem URL, legenda completa e cards de links.
        ``early`` (1.24): se o agente já começou a falar, o que falta da fala entra no mesmo envio.
        Depois do ``compose``, a fala vai para o idioma de ``[speech] language`` (``magi.core.i18n``);
        as frases do agente já vêm no idioma e passam iguais, então ``early.missing`` segue valendo."""
        self._followup = followup
        result = tr_result(compose(result))
        if result.needs_confirmation:
            self._pending = result.on_confirm
            if result.dangerous:
                self._vote_open = True
                await self.hud.send(VoteMsg(Verdict.PENDING))
        for card in result.cards:
            await self.hud.send(card)
        if (sub := subtitle(result)) is not None:
            await self.hud.send(sub)
        speaker = self.pipeline.deps.speaker
        if early is not None and early.started:
            if result.expression is not None:
                await self.hud.send(StateMsg(result.expression))
            await early.finish(early.missing(result.speech))
            return
        if result.speech and speaker is not None:
            await self._go(TurnState.SPEAKING, result.expression)
            # Último passo da tarefa: a continuação vem com ``playback-done`` (ou nova ativação).
            await speaker.say(result.speech, self.link, personal=True, **self._captions(speaker.say))
            return
        await self._after_speaking()

    def _captions(self, speak: Callable[..., Any]) -> dict[str, Any]:
        """``on_sentence`` para o ``say``/``say_stream`` do speaker, se ele aceitar: cada frase,
        ao começar a tocar, vai ao HUD como ``speech`` (texto, duração, índice) e a legenda se
        escreve conforme ela fala. Speaker sem o parâmetro (fakes, antigos): nada muda."""
        try:
            if "on_sentence" not in inspect.signature(speak).parameters:
                return {}
        except (TypeError, ValueError):
            return {}
        gen = self._speech_gen

        def on_sentence(text: str, dur: float | None, index: int) -> None:
            if gen != self._speech_gen:
                return  # fala interrompida: o aviso agendado ficou para trás
            task = asyncio.get_running_loop().create_task(self.hud.send(SpeechMsg(text, dur, index)))
            self._hud_tasks.add(task)
            task.add_done_callback(self._hud_tasks.discard)

        return {"on_sentence": on_sentence}

    def _cancel_timer(self) -> None:
        if self._timer is not None and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None

    async def _cancel_work(self) -> None:
        """Cancela tarefa e prazo em curso e descarta gravação e confirmação pendentes."""
        self._speech_gen += 1
        self._cancel_timer()
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._recording = False
        self._audio.clear()
        await self._drop_stream()
        self._keep_stale(self._pending)
        self._pending = None
        self._offer = None
        await self._close_vote(Verdict.DENIED)
