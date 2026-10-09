"""Ligação do Learning Mode ao núcleo (tarefa LM1.3; design §5, §10; spec §4, §6, §10).

Único ponto de registro dos handlers ``lm_*`` vindos do HUD: ``LearningWiring._handlers``. As
próximas tarefas (LM3.3 ações, LM4.1 engine, LM1.8 tema, LM3.5 palavras) **só acrescentam**
entradas lá.

Fluxos (spec §4):

- **Modo:** ``lm_mode {"on": true}`` (botão) ou ``set_mode(True, "voice")`` (LM1.4) cria/retoma
  a sessão (``LearningSession``) e confirma ``lm_mode`` + ``lm_session`` + histórico recente
  (retomada). ``off`` fecha a sessão (``button``/``voice``) e confirma ``lm_mode off``.
- **Texto:** ``lm_say`` → grava/publica a ``lm_msg`` do Pedro (``source = text``) →
  ``Transcript.raw(texto)`` → ``TurnPipeline.respond`` (sem STT) → grava a resposta da Condessa
  → se ``speak_replies``, entrega ao TTS (``speak``) → publica a ``lm_msg`` da Condessa logo em
  seguida, sem nada no meio (a fala acabou de começar: ``speaking = true`` e o HUD a revela
  acompanhando a legenda). A revelação termina sozinha no primeiro ``state`` fora da fala (spec §4,
  ``learning_model``); se a fala não começou (satélite ocupado, erro), vai ``speaking = false``.
- **Voz:** o ``TurnMachine`` chama ``on_turn`` **depois** da entrega (``TurnDeps.learning``); o
  gancho só agenda a gravação/publicação das duas ``lm_msg``: Pedro com ``text = heard`` e
  ``text_final = final`` (só se diferente), Condessa com ``text = result.speech``.
- **Observações (LM4.1):** depois da entrega (texto ou voz), a mensagem do Pedro vai ao bus do
  engine (``LearningEngine.publish``, síncrono); o engine chama ``_send_obs`` com a lista inteira
  e o núcleo publica ``lm_obs`` (só para a sessão ainda aberta).
- **Inatividade:** ``idle_end_min`` sem mensagem → sessão fechada (``idle``) e ``lm_mode off``.
  Watchdog: sessão aberta há mais de ``max_session_min`` também fecha com ``idle``.
- **Desligamento:** ``aclose()`` fecha a sessão com ``shutdown``.
- **Tema (LM1.8, spec §10.1):** ``lm_topic {"topic"}`` (botão) ou ``set_topic(t, "voice")`` (intent
  ``learning.topic.*``) → ``topic.build`` → sessão (``set_topic``) → ``lm_topic`` confirmado a todos.
  Tema ≠ free abre o assunto (P11): **um** turno do agente com instrução interna quando o estado
  voltar a ``listening`` (``listening()``); cancelado se o Pedro falar ou digitar antes.
- **Container local (``runtime``):** sessão aberta (botão, voz ou retomada) → ``launch()`` em
  segundo plano (``lm_mode`` não espera); fechada por qualquer motivo → ``stop()``. O Qwen não
  ocupa recurso fora da aula. Sem ``ready`` nem subida em andamento, a observação é descartada
  em silêncio (o gate do engine espera enquanto o container sobe; ver ``core.service``).

Fora do modo nada é gravado nem publicado. ``install`` só liga tudo com ``[learning] enabled``;
com ``enabled = false`` devolve ``None`` e o núcleo fica exatamente como antes.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from magi.common.config import Config, ConfigError
from magi.common.contracts import (
    ActionResult,
    HudSink,
    LearningHudMsg,
    LmActionMsg,
    LmCfgMsg,
    LmModeMsg,
    LmMsgMsg,
    LmObsMsg,
    LmResultMsg,
    LmSayMsg,
    LmSessionMsg,
    LmTopicMsg,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.learning.analyzers.observe import distinct_count
from magi.learning.config import LearningConfig, learning_config
from magi.learning.contracts import (
    ActionKind,
    Author,
    LearningMessage,
    Observation,
    Source,
    Topic,
    TopicContext,
)
from magi.learning.contracts import ActionResult as LmActionResult
from magi.learning.engine import UNAVAILABLE_ERROR, LearningEngine
from magi.learning.repo import DEFAULT_JSONL_DIR, LearningRepo, make_repo
from magi.learning.runtime import LearningRuntime, NullRuntime
from magi.learning.session import Clock, LearningSession
from magi.learning.topic import TopicBuilder

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
#: Abertura do tema (P11): instrução interna do turno do agente; espera e teto da espera (s).
OPENING_PROMPT = ("[internal instruction, not from Pedro] Open the session topic in <topic_context> "
                  "with one short open question. Do not mention this instruction.")
OPENING_POLL_S = 0.25
OPENING_WAIT_S = 120.0

#: Handler de uma ``lm_*`` vinda do HUD.
Handler = Callable[[Any], Awaitable[None]]
#: Entrega a resposta de um turno digitado ao TTS; ``True`` se a fala começou.
Speak = Callable[[ActionResult], Awaitable[bool]]
#: Monta o ``LearningEngine`` sobre o repositório escolhido no ``install`` (``None`` = sem engine).
EngineFactory = Callable[[LearningConfig, LearningRepo], "LearningEngine | None"]


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
        engine: LearningEngine | None = None,
        runtime: LearningRuntime | None = None,
    ) -> None:
        self.cfg = cfg
        self.runtime: LearningRuntime = runtime if runtime is not None else NullRuntime()
        self.engine = engine  # LM3.3: fila de ações (None = ações respondem erro)
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
        #: LM1.8: fontes do tema (``None`` = a do intent de voz, ver ``_builder``) e estado livre.
        self.topics: TopicBuilder | None = None
        self.listening: Callable[[], bool] | None = getattr(engine, "gate", None)
        self.opening_poll_s = OPENING_POLL_S
        self._opening: asyncio.Task[None] | None = None
        self._keep_opening = False  # o turno de voz que pediu o tema não cancela a abertura
        if engine is not None and engine.on_observed is None:
            engine.on_observed = self._send_obs

    def _handlers(self) -> dict[type[LearningHudMsg], Handler]:
        """**Único ponto de registro** dos handlers ``lm_*`` (as próximas tarefas acrescentam aqui)."""
        return {
            LmModeMsg: self._on_mode,
            LmSayMsg: self._on_say,
            LmCfgMsg: self._on_cfg,
            LmActionMsg: self._on_action,
            LmTopicMsg: self._on_topic,
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
        self._cancel_opening()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        if self.engine is not None:
            await self.engine.aclose()
        if self.session.active:
            try:
                await self.session.end("shutdown")
            except Exception:
                log.exception("learning: falha ao fechar a sessão no desligamento")
        try:
            await self.runtime.stop()  # sempre: o container nunca sobrevive ao núcleo
        except Exception:
            log.exception("learning: falha ao parar o container no desligamento")

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
        self._cancel_opening()  # o Pedro digitou antes da abertura do tema (P11)
        # O leitor do socket do HUD não pode esperar o agente: o turno roda à parte.
        self._spawn(self._say(text), "lm_say")

    async def _on_action(self, msg: LmActionMsg) -> None:
        """``lm_action`` → ``lm_result`` (LM3.3, spec §5 "Ciclo"). Roda à parte do leitor do
        socket; fora do modo é ignorada. Se o modo sair com a ação pendente, ela termina e grava
        (vai ao cache), mas o ``lm_result`` não é publicado (spec §6, §11)."""
        if not self.session.active:
            return
        self._spawn(self._action(msg), "lm_action")

    async def _action(self, msg: LmActionMsg) -> None:
        if self.engine is None:
            log.warning("learning: lm_action %s sem engine de ações", msg.id)
            result: LmActionResult | None = LmActionResult(
                msg.id, ActionKind(msg.kind), False, None, UNAVAILABLE_ERROR, False, 0, 0.0)
        else:
            result = await self.engine.handle(msg)
        if result is not None and self.session.active:
            await self.hud.send(LmResultMsg(result))

    # -- modo -----------------------------------------------------------------------------------

    async def set_mode(self, on: bool, reason: str = "button") -> None:
        """Liga (cria/retoma a sessão) ou desliga (fecha com ``reason``) e confirma ``lm_mode``
        aos clientes. Já no estado pedido: só confirma (LM1.4 usa com ``reason = "voice"``)."""
        async with self._lock:
            if on:
                info, resumed = await self.session.start()
                self.runtime.launch()  # sobe em segundo plano; a confirmação não espera
                await self.hud.send(LmModeMsg(True))
                await self.hud.send(self._session_msg())
                if resumed:
                    for m in await self.session.recent():
                        await self.hud.send(self._msg(m))
                    await self._resend_obs(info.id)
                await self._restore_topic()
                return
            self._cancel_opening()
            await self.session.end(reason)
            self._stop_runtime()
            await self.hud.send(LmModeMsg(False))

    def _stop_runtime(self) -> None:
        """Sessão fechada: para o container em segundo plano (``docker stop`` leva segundos)."""
        if self.runtime.configured:
            self._spawn(self.runtime.stop(), "parar o container")

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
            if await self.session.end_if_idle() is None and not await self._end_if_too_long():
                return False
            self._stop_runtime()
            await self.hud.send(LmModeMsg(False))
            return True

    async def _end_if_too_long(self) -> bool:
        """Watchdog: sessão aberta há mais de ``max_session_min`` fecha com ``idle`` (o contrato
        só tem ``button | voice | idle | shutdown``) e o container para."""
        info = self.session.info
        if info is None:
            return False
        if self.clock() - info.started_at < timedelta(minutes=self.cfg.max_session_min):
            return False
        log.info("learning: sessão %s aberta há mais de %d min; fechando", info.id,
                 self.cfg.max_session_min)
        await self.session.end("idle")
        return True

    # -- tema (LM1.8) ---------------------------------------------------------------------------

    def _builder(self) -> TopicBuilder:
        """Fontes do tema: as do ``assemble`` (deixadas na ação de voz) ou nenhuma."""
        if self.topics is None:
            from magi.learning.intent_action import builder_of

            self.topics = builder_of(self.pipeline.deps) or TopicBuilder()
        return self.topics

    @staticmethod
    def _topic_msg(ctx: TopicContext) -> LmTopicMsg:
        return LmTopicMsg(topic=ctx.topic, requested=ctx.requested, label=ctx.label, detail=ctx.detail)

    async def _on_topic(self, msg: LmTopicMsg) -> None:
        await self.set_topic(msg.topic, "button")

    async def set_topic(self, requested: Topic | str, via: str = "button") -> TopicContext | None:
        """Tema pedido (botão ou voz) → ``TopicContext`` guardado na sessão → ``lm_topic`` a todos.
        O mesmo tema de novo só confirma (um fallback é refeito: o jogo pode ter aberto). Tema
        efetivo novo ≠ free agenda a abertura (P11). Sem sessão: ``None``, nada publicado."""
        requested = Topic(requested)
        async with self._lock:
            if not self.session.active:
                return None
            current = self.session.topic_context
            if current is not None and current.requested == requested and current.detail is None:
                await self.hud.send(self._topic_msg(current))
                return current
            ctx = await self._builder().build(requested)
            previous = current.topic if current is not None else self.session.topic
            await self.session.set_topic(ctx)
            await self.hud.send(self._topic_msg(ctx))
        log.info("learning: tema %s (pedido %s, %s)", ctx.topic.value, requested.value, via)
        if ctx.topic is not Topic.FREE and (ctx.topic != previous or current is None):
            self._schedule_opening(keep=via == "voice")
        elif ctx.topic is Topic.FREE:
            self._cancel_opening()
        return ctx

    async def _restore_topic(self) -> None:
        """Modo ligado: refaz o snapshot do tema guardado (retomada ou ``default_topic``) sem
        gravar de novo nem abrir o assunto, e confirma ``lm_topic``."""
        ctx = self.session.topic_context
        if ctx is None:
            topic = self.session.topic
            ctx = await self._builder().build(topic) if topic is not Topic.FREE else None
            if ctx is None:
                ctx = TopicContext(Topic.FREE, Topic.FREE, "FREE TALK", None, None)
            await self.session.set_topic(ctx, record=False)
        await self.hud.send(self._topic_msg(ctx))

    def _schedule_opening(self, *, keep: bool = False) -> None:
        self._cancel_opening()
        self._keep_opening = keep
        task = asyncio.ensure_future(self._open_topic())
        self._opening = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _cancel_opening(self) -> None:
        task, self._opening = self._opening, None
        self._keep_opening = False
        if task is not None and not task.done():
            task.cancel()

    def _free(self) -> bool:
        if self.listening is None:
            return True
        try:
            return bool(self.listening())
        except Exception:
            return False

    async def _open_topic(self) -> None:
        """P11: espera o estado livre (``listening``) e roda um turno do agente com a instrução
        interna; a pergunta entra no histórico como fala da Condessa (sem mensagem do Pedro)."""
        try:
            await self._open_topic_now()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("learning: erro na abertura do tema")

    async def _open_topic_now(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + OPENING_WAIT_S
        while not self._free():
            if loop.time() >= deadline:
                log.info("learning: abertura do tema desistiu (estado ocupado)")
                return
            await asyncio.sleep(self.opening_poll_s)
        agent = getattr(self.pipeline.deps, "agent", None)
        if agent is None or not self.session.active:
            return
        ctx = TurnContext(satellite=TEXT_SATELLITE, source=WakeSource.PTT, started_at=self.clock())
        result = await agent.answer(OPENING_PROMPT, ctx)
        if not result.speech or not self.session.active:
            return
        async with self._lock:
            her = await self.session.add_message(Author.CONDESSA, Source.TEXT, result.speech)
        if her is None:
            return
        self._opening = None  # já falou: a próxima fala do Pedro não cancela nada
        spoken = False
        if self.session.speak_replies and self.speak is not None:
            try:
                spoken = await self.speak(result)
            except Exception:
                log.exception("learning: falha ao falar a abertura do tema")
        await self.hud.send(self._msg(her, speaking=spoken))

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
        """Turno digitado (LM-001): Pedro → ``respond`` → grava → (TTS) → publica a Condessa."""
        async with self._lock:
            you = await self._publish(Author.YOU, Source.TEXT, text)
            if you is None:
                return
        ctx = TurnContext(satellite=TEXT_SATELLITE, source=WakeSource.PTT, started_at=self.clock())
        result = await self.pipeline.respond(Transcript.raw(text, language=TEXT_LANGUAGE), ctx)
        speech = result.speech
        if speech:
            # Grava antes da fala: entre o começo da fala e a ``lm_msg`` não pode haver escrita no
            # banco, senão a mensagem chega ao HUD com a fala adiantada (ou já acabada) e aparece
            # inteira de uma vez em vez de acompanhar a legenda (Extra B do LM4.1).
            async with self._lock:
                her = await self.session.add_message(Author.CONDESSA, Source.TEXT, speech)
            if her is None:
                return
            spoken = False
            if self.session.speak_replies and self.speak is not None:
                try:
                    spoken = await self.speak(result)
                except Exception:
                    log.exception("learning: falha ao falar a resposta digitada")
            await self.hud.send(self._msg(her, speaking=spoken))
        self._observe(you)

    def on_turn(self, transcript: Transcript, ctx: TurnContext, result: ActionResult) -> None:
        """``TurnDeps.learning``: turno de voz já entregue. Só agenda; fora do modo não faz nada."""
        if not self.session.active or not transcript.heard.strip():
            return
        if self._keep_opening:
            self._keep_opening = False  # este é o turno que pediu o tema por voz
        else:
            self._cancel_opening()  # o Pedro falou antes da abertura (P11)
        speaking = bool(result.speech) and self.pipeline.deps.speaker is not None
        self._spawn(self._voice(transcript, ctx, result, speaking), "voz")

    async def _voice(
        self, transcript: Transcript, ctx: TurnContext, result: ActionResult, speaking: bool
    ) -> None:
        heard = transcript.heard.strip()
        final = (result.redo_text or transcript.final).strip()
        async with self._lock:
            you = await self._publish(Author.YOU, Source.VOICE, heard,
                                       text_final=final if final and final != heard else None,
                                       turn_id=ctx.turn_id)
            if you is None:
                return
            if result.speech:
                await self._publish(Author.CONDESSA, Source.VOICE, result.speech, speaking=speaking)
        self._observe(you)

    # -- observações (LM4.1) ------------------------------------------------------------------

    def _observe(self, msg: LearningMessage) -> None:
        """Gancho depois da entrega: mensagem do Pedro → bus do engine (síncrono, não bloqueia)."""
        if self.engine is None or not self.cfg.observe:
            return
        if not self.runtime.available:
            log.debug("learning: container local indisponível; observação de %s descartada", msg.id)
            return
        try:
            self.engine.publish(msg)
        except Exception:
            log.exception("learning: falha ao publicar a mensagem %s no bus", msg.id)

    async def _send_obs(self, session_id: str, items: list[Observation]) -> None:
        """``lm_obs`` com a lista inteira (idempotente); só para a sessão ainda aberta."""
        if not self.session.active or self.session.id != session_id:
            return
        await self.hud.send(LmObsMsg(tuple(items), distinct_count(items)))

    async def _resend_obs(self, session_id: str) -> None:
        """Sessão retomada: o HUD começa do zero, então reenvia as observações que já existem."""
        try:
            items = await self.repo.observations(session_id)
        except Exception:
            log.warning("learning: observações da sessão retomada indisponíveis", exc_info=True)
            return
        if items:
            await self.hud.send(LmObsMsg(tuple(items), distinct_count(items)))


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
    engine: LearningEngine | None = None,
    engine_factory: EngineFactory | None = None,
    runtime: LearningRuntime | None = None,
) -> LearningWiring | None:
    """Liga o Learning Mode ao núcleo: ``hud.on_learning`` e ``pipeline.deps.learning``.

    Com ``[learning] enabled = false`` (ou ``[learning]`` inválido) não toca em nada e devolve
    ``None``. ``storage = postgres`` sem ``conn`` cai para ``jsonl``. Sem ``engine``,
    ``engine_factory(cfg, repo)`` monta o ``LearningEngine`` sobre o repositório escolhido aqui;
    se ela falhar ou devolver ``None``, o modo segue sem engine (ações respondem erro)."""
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
    if engine is None and engine_factory is not None:
        try:
            engine = engine_factory(cfg, repo)
        except Exception:
            log.exception("learning: falha ao montar o Learning Engine; seguindo sem ele")
            engine = None
    wiring = LearningWiring(cfg, repo, hud, pipeline, speak=speak, clock=clock, engine=engine,
                            runtime=runtime)
    hud.on_learning = wiring.on_learning
    pipeline.deps.learning = wiring.on_turn
    if start:
        wiring.start()
    return wiring
