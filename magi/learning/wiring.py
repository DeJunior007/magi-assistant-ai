"""Ligação do Learning Mode ao núcleo (tarefa LM1.3; design §5, §10; spec §4, §6, §10).

Único ponto de registro dos handlers ``lm_*`` vindos do HUD: ``LearningWiring._handlers``. As
próximas tarefas (LM3.3 ações, LM4.1 engine, LM1.8 tema, LM3.5 palavras) **só acrescentam**
entradas lá.

Fluxos (spec §4):

- **Modo:** ``lm_mode {"on": true}`` (botão) ou ``set_mode(True, "voice")`` (LM1.4) cria/retoma
  a sessão (``LearningSession``) e confirma ``lm_mode`` + ``lm_session`` + histórico recente
  (retomada). ``off`` fecha a sessão (``button``/``voice``) e confirma ``lm_mode off``.
- **Texto:** ``lm_say`` → grava/publica a ``lm_msg`` do Pedro (``source = text``) →
  ``Transcript.raw(texto)`` → ``TurnPipeline.respond`` (sem STT) → se ``speak_replies``, entrega
  ao TTS (``speak``) → grava/publica a ``lm_msg`` da Condessa.
- **Voz:** o ``TurnMachine`` chama ``on_turn`` **depois** da entrega (``TurnDeps.learning``); o
  gancho só agenda a gravação/publicação das duas ``lm_msg``: Pedro com ``text = heard`` e
  ``text_final = final`` (só se diferente), Condessa com ``text = result.speech``.
- **Inatividade:** ``idle_end_min`` sem mensagem → sessão fechada (``idle``) e ``lm_mode off``.
- **Desligamento:** ``aclose()`` fecha a sessão com ``shutdown``.

Fora do modo nada é gravado nem publicado. ``install`` só liga tudo com ``[learning] enabled``;
com ``enabled = false`` devolve ``None`` e o núcleo fica exatamente como antes.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from magi.common.config import Config, ConfigError
from magi.common.contracts import (
    ActionResult,
    HudSink,
    LearningHudMsg,
    LmCfgMsg,
    LmModeMsg,
    LmMsgMsg,
    LmSayMsg,
    LmSessionMsg,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.learning.config import LearningConfig, learning_config
from magi.learning.contracts import Author, LearningMessage, Source
from magi.learning.repo import DEFAULT_JSONL_DIR, LearningRepo, make_repo
from magi.learning.session import Clock, LearningSession

if TYPE_CHECKING:
    from magi.core.turn import TurnPipeline

log = logging.getLogger(__name__)

#: Nome do "satélite" dos turnos digitados (``TurnContext.satellite``).
TEXT_SATELLITE = "learning"
#: Idioma do turno digitado (a aula é em inglês).
TEXT_LANGUAGE = "en"
#: Texto digitado acima disso é recusado (spec §4 item 2; a UI já recusa).
SAY_MAX_CHARS = 2000
#: Intervalo de checagem da inatividade (s).
IDLE_CHECK_S = 30.0

#: Handler de uma ``lm_*`` vinda do HUD.
Handler = Callable[[Any], Awaitable[None]]
#: Entrega a resposta de um turno digitado ao TTS; ``True`` se a fala começou.
Speak = Callable[[ActionResult], Awaitable[bool]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LearningWiring:
    """Handlers ``lm_*`` do núcleo, gancho de voz e fim por inatividade (LM1.3)."""

    def __init__(
        self,
        cfg: LearningConfig,
        repo: LearningRepo,
        hud: HudSink,
        pipeline: TurnPipeline,
        *,
        speak: Speak | None = None,
        clock: Clock = _utcnow,
        idle_check_s: float = IDLE_CHECK_S,
    ) -> None:
        self.cfg = cfg
        self.repo = repo
        self.hud = hud
        self.pipeline = pipeline
        self.speak = speak
        self.clock = clock
        self.idle_check_s = idle_check_s
        self.session = LearningSession(repo, cfg, clock=clock)
        self.handlers: dict[type[LearningHudMsg], Handler] = self._handlers()
        self._lock = asyncio.Lock()  # ordem das mensagens (texto e voz) e do modo
        self._tasks: set[asyncio.Task[Any]] = set()
        self._idle: asyncio.Task[None] | None = None

    def _handlers(self) -> dict[type[LearningHudMsg], Handler]:
        """**Único ponto de registro** dos handlers ``lm_*`` (as próximas tarefas acrescentam aqui)."""
        return {
            LmModeMsg: self._on_mode,
            LmSayMsg: self._on_say,
            LmCfgMsg: self._on_cfg,
        }

    # -- ciclo de vida --------------------------------------------------------------------------

    def start(self) -> None:
        """Começa a checagem de inatividade (precisa de loop rodando)."""
        if self._idle is None:
            self._idle = asyncio.create_task(self._idle_loop(), name="learning-idle")

    async def aclose(self) -> None:
        """Desligamento do núcleo: fecha a sessão aberta com ``shutdown`` (spec §10)."""
        if self._idle is not None:
            self._idle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle
            self._idle = None
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        if self.session.active:
            try:
                await self.session.end("shutdown")
            except Exception:
                log.exception("learning: falha ao fechar a sessão no desligamento")

    async def wait_idle(self) -> None:
        """Espera as gravações/publicações agendadas (testes)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _spawn(self, coro: Awaitable[Any], name: str) -> None:
        task = asyncio.ensure_future(self._guard(coro, name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _guard(coro: Awaitable[Any], name: str) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("learning: erro em %s", name)

    # -- entrada do HUD -------------------------------------------------------------------------

    async def on_learning(self, msg: LearningHudMsg) -> None:
        """``HudServer.on_learning``: despacha pelo tipo; tipo sem handler é ignorado."""
        handler = self.handlers.get(type(msg))
        if handler is None:
            log.debug("learning: %s sem handler", msg.T)
            return
        await handler(msg)

    async def _on_mode(self, msg: LmModeMsg) -> None:
        await self.set_mode(msg.on, "button")

    async def _on_cfg(self, msg: LmCfgMsg) -> None:
        if msg.speak_replies is not None:
            self.session.speak_replies = bool(msg.speak_replies)
            log.info("learning: falar respostas = %s", self.session.speak_replies)

    async def _on_say(self, msg: LmSayMsg) -> None:
        text = msg.text.strip()
        if not self.session.active or not text:
            return
        if len(text) > SAY_MAX_CHARS:
            log.info("learning: lm_say recusado (%d caracteres)", len(text))
            return
        # O leitor do socket do HUD não pode esperar o agente: o turno roda à parte.
        self._spawn(self._say(text), "lm_say")

    # -- modo -----------------------------------------------------------------------------------

    async def set_mode(self, on: bool, reason: str = "button") -> None:
        """Liga (cria/retoma a sessão) ou desliga (fecha com ``reason``) e confirma ``lm_mode``
        aos clientes. Já no estado pedido: só confirma (LM1.4 usa com ``reason = "voice"``)."""
        async with self._lock:
            if on:
                info, resumed = await self.session.start()
                await self.hud.send(LmModeMsg(True))
                await self.hud.send(self._session_msg())
                if resumed:
                    for m in await self.session.recent():
                        await self.hud.send(self._msg(m))
                return
            await self.session.end(reason)
            await self.hud.send(LmModeMsg(False))

    def _session_msg(self) -> LmSessionMsg:
        info = self.session.info
        assert info is not None
        return LmSessionMsg(
            id=info.id,
            started_at=info.started_at,
            level=info.level or self.cfg.level,
            track=info.track or self.cfg.track,
            topic=info.topic,
            n_msgs=self.session.n_msgs,
        )

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(self.idle_check_s)
            await self.check_idle()

    async def check_idle(self) -> bool:
        """Fecha por inatividade se passou de ``idle_end_min`` (``True`` = fechou)."""
        flush = getattr(self.repo, "flush", None)
        if flush is not None and getattr(self.repo, "pending", 0):
            with contextlib.suppress(Exception):
                await flush()
        async with self._lock:
            if await self.session.end_if_idle() is None:
                return False
            await self.hud.send(LmModeMsg(False))
            return True

    # -- conversa -------------------------------------------------------------------------------

    @staticmethod
    def _msg(m: LearningMessage, *, speaking: bool = False, text_final: str | None = None) -> LmMsgMsg:
        return LmMsgMsg(id=m.id, author=m.author, source=m.source, text=m.text, at=m.at,
                        speaking=speaking, text_final=text_final)

    async def _publish(
        self, author: Author, source: Source, text: str, *,
        text_final: str | None = None, speaking: bool = False, turn_id: int | None = None,
    ) -> LearningMessage | None:
        m = await self.session.add_message(author, source, text, text_final=text_final, turn_id=turn_id)
        if m is not None:
            await self.hud.send(self._msg(m, speaking=speaking, text_final=text_final))
        return m

    async def _say(self, text: str) -> None:
        """Turno digitado (LM-001): Pedro → ``respond`` → (TTS) → Condessa."""
        async with self._lock:
            if await self._publish(Author.YOU, Source.TEXT, text) is None:
                return
        ctx = TurnContext(satellite=TEXT_SATELLITE, source=WakeSource.PTT, started_at=self.clock())
        result = await self.pipeline.respond(Transcript.raw(text, language=TEXT_LANGUAGE), ctx)
        speech = result.speech
        if not speech:
            return
        spoken = False
        if self.session.speak_replies and self.speak is not None:
            try:
                spoken = await self.speak(result)
            except Exception:
                log.exception("learning: falha ao falar a resposta digitada")
        async with self._lock:
            await self._publish(Author.CONDESSA, Source.TEXT, speech, speaking=spoken)

    def on_turn(self, transcript: Transcript, ctx: TurnContext, result: ActionResult) -> None:
        """``TurnDeps.learning``: turno de voz já entregue. Só agenda; fora do modo não faz nada."""
        if not self.session.active or not transcript.heard.strip():
            return
        speaking = bool(result.speech) and self.pipeline.deps.speaker is not None
        self._spawn(self._voice(transcript, ctx, result, speaking), "voz")

    async def _voice(
        self, transcript: Transcript, ctx: TurnContext, result: ActionResult, speaking: bool
    ) -> None:
        heard = transcript.heard.strip()
        final = (result.redo_text or transcript.final).strip()
        async with self._lock:
            if await self._publish(Author.YOU, Source.VOICE, heard,
                                   text_final=final if final and final != heard else None,
                                   turn_id=ctx.turn_id) is None:
                return
            if result.speech:
                await self._publish(Author.CONDESSA, Source.VOICE, result.speech, speaking=speaking)


# ---------------------------------------------------------------------------------------------
# Instalação no núcleo
# ---------------------------------------------------------------------------------------------


def speak_via(machines: Callable[[], Iterable[Any]]) -> Speak:
    """``Speak`` que fala pelo primeiro satélite livre (``TurnMachine.announce``); todos
    ocupados ou nenhum conectado = só texto (``False``)."""

    async def speak(result: ActionResult) -> bool:
        for machine in list(machines()):
            if await machine.announce(result.speech, result.expression):
                return True
        return False

    return speak


def install(
    config: Config | LearningConfig,
    hud: Any,
    pipeline: TurnPipeline,
    *,
    repo: LearningRepo | None = None,
    conn: Any = None,
    speak: Speak | None = None,
    jsonl_dir: Path | str = DEFAULT_JSONL_DIR,
    clock: Clock = _utcnow,
    start: bool = True,
) -> LearningWiring | None:
    """Liga o Learning Mode ao núcleo: ``hud.on_learning`` e ``pipeline.deps.learning``.

    Com ``[learning] enabled = false`` (ou ``[learning]`` inválido) não toca em nada e devolve
    ``None``. ``storage = postgres`` sem ``conn`` cai para ``jsonl``."""
    try:
        cfg = config if isinstance(config, LearningConfig) else learning_config(config)
    except ConfigError as e:
        log.warning("learning: config inválida (%s); modo desligado", e)
        return None
    if not cfg.enabled:
        return None
    if repo is None:
        if cfg.storage == "postgres" and conn is None:
            log.warning("learning: sem banco; histórico em jsonl")
            cfg = dataclasses.replace(cfg, storage="jsonl")
        repo = make_repo(cfg, conn=conn, jsonl_dir=jsonl_dir)
    wiring = LearningWiring(cfg, repo, hud, pipeline, speak=speak, clock=clock)
    hud.on_learning = wiring.on_learning
    pipeline.deps.learning = wiring.on_turn
    if start:
        wiring.start()
    return wiring
