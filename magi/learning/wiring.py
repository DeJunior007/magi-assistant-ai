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
- **Entrevista pela vaga (LI1.4, design §4–§5 do learning-imersivo):** ``lm_job`` → ``preparing``
  na hora → extração em tarefa (reuso por hash, R2.6) → roteiro → run gravada → ``lm_topic``
  ``INTERVIEW // <CARGO>`` + ``lm_interview ready`` → abertura P11 com a etapa 1. Com run viva o
  ``<topic_context>`` é ``run.block(now)`` (``_topic_block``); depois de cada turno ``run.observe``
  (+ ``lm_interview`` e gravação). Comandos: ``lm_interview {"cmd"}`` (botão), texto que casa com
  ``run.command_of`` e intents ``learning.interview.*`` (voz). Troca de tema pausa a run; sessão
  retomada volta à run (R5.3); fim (``end``/WRAP) chama ``_finish_interview``,
  que agenda o retorno (LI2.3, ``debrief``) sem segurar o turno.

Fora do modo nada é gravado nem publicado. ``install`` só liga tudo com ``[learning] enabled``;
com ``enabled = false`` devolve ``None`` e o núcleo fica exatamente como antes.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import re
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
    LmDebriefMsg,
    LmInterviewMsg,
    LmJobMsg,
    LmJobRef,
    LmJobReqMsg,
    LmModeMsg,
    LmMsgMsg,
    LmObsMsg,
    LmResultMsg,
    LmSavedMsg,
    LmSaveMsg,
    LmSayMsg,
    LmScenarioRef,
    LmSessionMsg,
    LmTopicMsg,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core.i18n import tr_result
from magi.learning.analyzers.observe import distinct_count
from magi.learning.config import LearningConfig, learning_config
from magi.learning.contracts import (
    ActionKind,
    Author,
    LearningMessage,
    Observation,
    SavedWord,
    Source,
    Topic,
    TopicContext,
)
from magi.learning.contracts import ActionResult as LmActionResult
from magi.learning.engine import UNAVAILABLE_ERROR, LearningEngine
from magi.learning.interview import debrief as iv_debrief
from magi.learning.interview import extract as iv_extract
from magi.learning.interview import jobtext
from magi.learning.interview import plan as iv_plan
from magi.learning.interview import run as iv_run
from magi.learning.interview.contracts import (
    InterviewDebrief,
    InterviewRun,
    JobPost,
    RunState,
    make_run_id,
)
from magi.learning.interview.store import InterviewStore
from magi.learning.model import LearningModel, ModelError, ModelFailure
from magi.learning.repo import DEFAULT_JSONL_DIR, LearningRepo, make_repo, normalize_term
from magi.learning.runtime import LearningRuntime, NullRuntime
from magi.learning.session import Clock, LearningSession
from magi.learning.topic import LABELS, TopicBuilder

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
#: Entrevista pela vaga (LI1.4): abertura com a etapa 1 (R3.2) e a próxima pergunta pedida.
INTERVIEW_OPENING_PROMPT = (
    "[internal instruction, not from Pedro] Start the mock interview in <topic_context>: greet him "
    "as the interviewer in one sentence and ask the first question of the current stage. Do not "
    "mention this instruction.")
INTERVIEW_NEXT_PROMPT = (
    "[internal instruction, not from Pedro] He asked to move on. Ask the next question of the "
    "current stage in <topic_context>, with a short transition if the stage changed. Do not "
    "mention this instruction.")
#: Linhas curtas do ``lm_interview.error`` (spec §10).
STILL_PREPARING = "still preparing the last one"
UNKNOWN_JOB = "unknown job"
#: Rótulo do tema com vaga (R2.4) e teto do cargo nele.
INTERVIEW_LABEL = "INTERVIEW // {title}"
LABEL_TITLE_MAX = 60
_RUN_LIVE = (RunState.READY, RunState.RUNNING, RunState.PAUSED)
OPENING_WAIT_S = 120.0
#: Retorno da entrevista (LI2.3, R4.2/R4.4, spec §10): falas curtas e título sem perfil conhecido.
DEBRIEF_READY = "Your interview feedback is on the screen. Take a look when you're ready."
DEBRIEF_TOO_SHORT = "No feedback this time: I need at least {n} answers from you to judge."
DEBRIEF_FAILED = "feedback not generated — {code}"
DEBRIEF_TITLE = "MOCK INTERVIEW"
#: Mensagens lidas para montar a transcrição da run (a sessão tem bem menos que isso).
DEBRIEF_MESSAGES_MAX = 2000

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
        job_model: LearningModel | None = None,
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
        self.session = LearningSession(repo, cfg, clock=clock, send=hud.send)  # lm_summary (LM4.5)
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
        self._opening_prompt = OPENING_PROMPT
        #: LI1.4: entrevista pela vaga (modelo da extração, gravação, run ativa e vaga em preparo).
        self.job_model = job_model
        self.interviews = InterviewStore(repo, clock=clock)
        self.run: InterviewRun | None = None
        self._preparing: str | None = None
        self._jobs: tuple[LmJobRef, ...] = ()
        self._run_n: tuple[str, int] = ("", 0)
        self._cmd_turn = False  # o turno de voz foi um comando da entrevista: não conta resposta
        #: LI2.3: título/empresa/hora de cada retorno gerado neste processo (o repo não guarda).
        self._debrief_meta: dict[str, tuple[str, str | None, datetime]] = {}
        #: LI4.2: cenário de roleplay atual de cada sessão (só em memória: o repo ainda não grava o
        #: id com o tema; retomada depois de reiniciar cai em free) e a lista do seletor (lida 1×).
        self._scenario_of: dict[str, str] = {}
        self._scenario_refs: tuple[LmScenarioRef, ...] | None = None

    def _handlers(self) -> dict[type[LearningHudMsg], Handler]:
        """**Único ponto de registro** dos handlers ``lm_*`` (as próximas tarefas acrescentam aqui)."""
        return {
            LmModeMsg: self._on_mode,
            LmSayMsg: self._on_say,
            LmCfgMsg: self._on_cfg,
            LmActionMsg: self._on_action,
            LmTopicMsg: self._on_topic,
            LmSaveMsg: self._on_save,
            LmJobMsg: self._on_job,
            LmInterviewMsg: self._on_interview,
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
        await self._close_run("shutdown")
        await self.wait_idle()  # LI2.3: o retorno em segundo plano grava antes de desligar
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
        cmd = iv_run.command_of(text) if self.live_run() is not None else None
        if cmd is not None and cmd != "repeat":  # comando digitado da entrevista: sem LLM
            self._spawn(self._say_command(text, cmd), "comando da entrevista")
            return
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
            saved = await self.engine.saved_state(result) if self.engine is not None else None
            if saved is not None:  # LM3.5: estrela do Vocabulary abre no estado certo
                await self.hud.send(saved)

    # -- palavras salvas (LM3.5, spec §10.3) ----------------------------------------------------

    async def _on_save(self, msg: LmSaveMsg) -> None:
        """``lm_save {"action_id","on"}`` → ``save_word``/``unsave_word`` → ``lm_saved``. Tudo vem
        do ``action_id`` (só Vocabulary ``ok``; outro é recusado sem resposta). Banco fora →
        ``lm_saved`` com o estado contrário ao pedido (a UI desfaz a marca, "not saved")."""
        if not self.session.active or self.engine is None:
            return
        stored = await self.engine.resolve_vocab(msg.action_id)
        if stored is None:
            log.info("learning: lm_save %s recusado (não é vocabulary ok)", msg.action_id)
            return
        data = stored.result.data or {}
        term = str(data.get("term") or "")
        norm = normalize_term(term)
        now = self.clock()
        try:
            if msg.on:
                source = await self.repo.get_message(stored.message_id)
                if source is None:
                    raise LookupError(f"mensagem {stored.message_id} desconhecida")
                word = await self.repo.save_word(SavedWord(
                    None, norm, term, str(data.get("meaning") or ""), data.get("pos"),
                    data.get("cefr"), source_sentence(source.text, stored.sel_start, stored.sel_end),
                    source.session_id, stored.message_id, stored.result.id, now, None))
                reply = LmSavedMsg(norm, True, word.id)
            else:
                await self.repo.unsave_word(norm, now)
                reply = LmSavedMsg(norm, False)
        except Exception:
            log.warning("learning: lm_save %s não gravado", msg.action_id, exc_info=True)
            reply = LmSavedMsg(norm, not msg.on)
        await self.hud.send(reply)

    # -- modo -----------------------------------------------------------------------------------

    async def set_mode(self, on: bool, reason: str = "button") -> None:
        """Liga (cria/retoma a sessão) ou desliga (fecha com ``reason``) e confirma ``lm_mode``
        aos clientes. Já no estado pedido: só confirma (LM1.4 usa com ``reason = "voice"``)."""
        async with self._lock:
            if on:
                info, resumed = await self.session.start()
                self.runtime.launch()  # sobe em segundo plano; a confirmação não espera
                await self._refresh_jobs()
                if resumed:
                    await self._resume_run(info.id)
                unseen = await self._unseen_debrief()
                await self.hud.send(LmModeMsg(True))
                await self.hud.send(dataclasses.replace(self._session_msg(),
                                                        debrief_unseen=unseen is not None))
                if resumed:
                    for m in await self.session.recent():
                        await self.hud.send(self._msg(m))
                    await self._resend_obs(info.id)
                await self._restore_topic()
                if (run := self.live_run()) is not None:
                    await self.hud.send(self._iv_msg(run))
                if unseen is not None:
                    await self._send_debrief(unseen)  # R5.2: uma vez, na abertura
                return
            self._cancel_opening()
            await self._close_run(reason)
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
            jobs=self._jobs,
            scenarios=self._scenario_list(),
        )

    def _scenario_list(self) -> tuple[LmScenarioRef, ...]:
        """Cenários de roleplay do seletor (``lm_session.scenarios``, spec §12); erro = nenhum."""
        if self._scenario_refs is None:
            from magi.learning import roleplay

            builder = self.topics if self.pipeline is None else self._builder()  # sem pipeline
            try:
                found = roleplay.scenarios((builder.scenarios_dir if builder is not None else None)
                                           or roleplay.SCENARIOS_DIR)
            except (OSError, ValueError):
                log.exception("learning: cenários de roleplay ilegíveis")
                found = ()
            self._scenario_refs = tuple(LmScenarioRef(s.id, s.title) for s in found)
        return self._scenario_refs

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
            await self._close_run("idle")
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
        await self.set_topic(msg.topic, "button", scenario=msg.scenario)

    async def set_topic(self, requested: Topic | str, via: str = "button", *,
                        scenario: str | None = None) -> TopicContext | None:
        """Tema pedido (botão ou voz) → ``TopicContext`` guardado na sessão → ``lm_topic`` a todos.
        O mesmo tema de novo só confirma (um fallback é refeito: o jogo pode ter aberto). Tema
        efetivo novo ≠ free agenda a abertura (P11). Sem sessão: ``None``, nada publicado.
        ``scenario``: id do roleplay (LI4.2); outro cenário = tema novo (refaz e abre a cena)."""
        requested = Topic(requested)
        scenario = scenario if requested is Topic.ROLEPLAY else None
        async with self._lock:
            if not self.session.active:
                return None
            sid = self.session.id or ""
            current = self.session.topic_context
            same_scene = requested is not Topic.ROLEPLAY or scenario == self._scenario_of.get(sid)
            if (current is not None and current.requested == requested and current.detail is None
                    and same_scene):
                await self.hud.send(self._topic_msg(current))
                return current
            run = self.live_run()
            if run is not None and requested is Topic.INTERVIEW:
                ctx = self._run_ctx(run)  # volta à vaga da run pausada (spec §10)
            else:
                ctx = await self._builder().build(requested, scenario)
                if run is not None and iv_run.apply(run, "pause", self._now()):
                    await self._push_run(run)  # troca de tema no meio: PAUSED e grava
            previous = current.topic if current is not None else self.session.topic
            if ctx.topic is Topic.ROLEPLAY and scenario:
                self._scenario_of[sid] = scenario
            else:
                self._scenario_of.pop(sid, None)
            await self.session.set_topic(ctx)
            await self.hud.send(self._topic_msg(ctx))
        log.info("learning: tema %s (pedido %s, %s)", ctx.topic.value, requested.value, via)
        if ctx.topic is not Topic.FREE and (ctx.topic != previous or current is None
                                            or not same_scene):
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
            scenario = self._scenario_of.get(self.session.id or "")  # roleplay: mesmo cenário
            ctx = await self._builder().build(topic, scenario) if topic is not Topic.FREE else None
            if ctx is None:
                ctx = TopicContext(Topic.FREE, Topic.FREE, "FREE TALK", None, None)
            await self.session.set_topic(ctx, record=False)
        await self.hud.send(self._topic_msg(ctx))

    def _schedule_opening(self, *, keep: bool = False, prompt: str = OPENING_PROMPT) -> None:
        self._cancel_opening()
        self._keep_opening = keep
        self._opening_prompt = prompt
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
        result = tr_result(await agent.answer(self._opening_prompt, ctx))
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
        await self._after_turn(None, her)

    # -- entrevista pela vaga (LI1.4) -----------------------------------------------------------

    def _now(self) -> float:
        return self.clock().timestamp()

    def live_run(self) -> InterviewRun | None:
        run = self.run
        return run if run is not None and run.state in _RUN_LIVE else None

    def _in_interview(self) -> bool:
        ctx = self.session.topic_context
        return ctx is not None and ctx.topic is Topic.INTERVIEW

    def _iv_msg(self, run: InterviewRun) -> LmInterviewMsg:
        return LmInterviewMsg(**iv_run.progress(run, self._now()))

    def _run_ctx(self, run: InterviewRun) -> TopicContext:
        title = run.profile.title.upper()[:LABEL_TITLE_MAX]
        return TopicContext(Topic.INTERVIEW, Topic.INTERVIEW, INTERVIEW_LABEL.format(title=title),
                            iv_run.block(run, self._now()), None)

    def _run_id(self) -> str:
        """``IV-AAAAMMDD-NN`` com ``NN`` = segundos do dia + 1 (sem contador no repositório);
        sobe 1 se repetir no mesmo dia."""
        now = self.clock()
        day = f"{now:%Y%m%d}"
        n = now.hour * 3600 + now.minute * 60 + now.second + 1
        last_day, last_n = self._run_n
        if day == last_day and n <= last_n:
            n = last_n + 1
        self._run_n = (day, n)
        return make_run_id(now, n)

    def _topic_block(self) -> str | None:
        """Bloco ``<topic_context>`` do turno: com run viva no tema interview é ``run.block(now)``
        (o avanço por tempo entra aqui, ``run.tick``); senão o bloco fixo do tema."""
        run = self.live_run()
        if run is None or not self._in_interview():
            return self.session.topic_block
        now = self._now()
        if iv_run.tick(run, now):
            self._spawn(self._push_run(run), "etapa por tempo")
        return iv_run.block(run, now)

    async def _push_run(self, run: InterviewRun, end_reason: str | None = None) -> None:
        """Grava a run e manda o ``lm_interview`` (só com sessão aberta)."""
        try:
            await self.interviews.save_run(run, end_reason)
        except Exception:
            log.warning("learning: simulação %s não gravada", run.id, exc_info=True)
        if self.session.active:
            await self.hud.send(self._iv_msg(run))

    async def _refresh_jobs(self) -> None:
        """Vagas recentes para ``lm_session.jobs`` (≤ 3)."""
        try:
            recent = await self.interviews.recent(3)
        except Exception:
            log.warning("learning: vagas recentes indisponíveis", exc_info=True)
            return
        self._jobs = tuple(LmJobRef(jid, p.title, p.company) for jid, p in recent[:3])

    async def _resume_run(self, session_id: str) -> None:
        """Sessão retomada com simulação viva volta à mesma etapa e contagem (R5.3)."""
        if self.run is not None:
            return
        try:
            run = await self.interviews.load_active(session_id)
        except Exception:
            log.warning("learning: simulação da sessão retomada indisponível", exc_info=True)
            return
        if run is None or run.state not in _RUN_LIVE:
            return
        self.run = run
        await self.session.set_topic(self._run_ctx(run), record=False)

    async def _on_job(self, msg: LmJobMsg, *, keep: bool = False) -> None:
        """``lm_job``: ``preparing`` na hora (≤ 100 ms, R2.1) e o preparo em tarefa própria."""
        if not self.session.active:
            return
        if self._preparing is not None:
            await self.hud.send(LmInterviewMsg(state=RunState.PREPARING, job_id=self._preparing,
                                               error=STILL_PREPARING))
            return
        post: JobPost | None = None
        if msg.text is not None:
            checked = jobtext.check(msg.text)
            if not checked.ok:
                await self.hud.send(LmInterviewMsg(state=RunState.ERROR, error=checked.line))
                return
            jid = jobtext.job_id(checked.text)
            post = JobPost(id=jid, text=checked.text, source=msg.source or "clipboard",
                           created_at=self.clock())
        else:
            assert msg.job_id is not None
            jid = msg.job_id
        self._preparing = jid
        await self.hud.send(LmInterviewMsg(state=RunState.PREPARING, job_id=jid))
        self._spawn(self._prepare(jid, post, keep=keep), "preparar a vaga")

    async def _prepare(self, jid: str, post: JobPost | None, *, keep: bool = False) -> None:
        try:
            await self._prepare_now(jid, post, keep=keep)
        except Exception:
            log.exception("learning: falha ao preparar a vaga %s", jid)
            await self.hud.send(LmInterviewMsg(state=RunState.ERROR, job_id=jid, error="model"))
        finally:
            self._preparing = None

    async def _prepare_now(self, jid: str, post: JobPost | None, *, keep: bool) -> None:
        """Design §4: grava a vaga → perfil (reuso por hash ou extração) → roteiro → run → tema."""
        if post is not None:
            await self.interviews.save_post(post)
        profile = await self.interviews.profile_of(jid)
        if profile is None:
            post = post or await self.interviews.post_of(jid)
            if post is None:
                await self.hud.send(LmInterviewMsg(state=RunState.ERROR, job_id=jid, error=UNKNOWN_JOB))
                return
            model = self.job_model
            try:
                if model is None:
                    raise ModelFailure("sem modelo para a vaga")
                profile = await iv_extract.extract(post, model)
            except ModelError as e:  # R2.5: tema anterior fica, vaga gravada não se perde
                log.info("learning: extração da vaga %s falhou (%s)", jid, e.code)
                await self.hud.send(LmInterviewMsg(state=RunState.ERROR, job_id=jid, error=e.code))
                return
            await self.interviews.set_profile(jid, profile, model=getattr(model, "model", None))
        plan = iv_plan.build_plan(profile, self.cfg.interview_minutes, job_id=jid)
        async with self._lock:
            if not self.session.active or self.session.id is None:
                return
            now = self._now()
            old = self.live_run()
            if old is not None and old.job_id == jid:
                run = old  # mesma vaga: retoma a run (spec §10)
            else:
                if old is not None:
                    iv_run.finish(old, "replaced", now)
                    await self.interviews.save_run(old, "replaced")
                run = iv_run.start(plan, profile, self.session.id, now, run_id=self._run_id())
                self.run = run
                await self.interviews.save_run(run)
            ctx = self._run_ctx(run)
            await self.session.set_topic(ctx)
            await self.hud.send(self._topic_msg(ctx))
            await self.hud.send(self._iv_msg(run))
        await self._refresh_jobs()
        log.info("learning: entrevista %s pronta (vaga %s)", run.id, jid)
        if run is not old:
            self._schedule_opening(keep=keep, prompt=INTERVIEW_OPENING_PROMPT)

    async def request_job(self) -> bool:
        """Voz (D1): pede ao HUD o clipboard como ``lm_job`` (``lm_job_req``)."""
        if not self.session.active:
            return False
        self._cmd_turn = True
        await self.hud.send(LmJobReqMsg())
        return True

    async def last_job(self) -> bool:
        """Voz: recarrega a última vaga usada (``lm_job {"job_id"}``); ``False`` sem vaga."""
        if not self.session.active:
            return False
        await self._refresh_jobs()
        if not self._jobs:
            return False
        self._cmd_turn = True
        await self._on_job(LmJobMsg(job_id=self._jobs[0].job_id), keep=True)
        return True

    async def _on_interview(self, msg: LmInterviewMsg) -> None:
        if msg.cmd is not None:
            await self.interview_command(msg.cmd, "button")

    async def _say_command(self, text: str, cmd: str) -> None:
        async with self._lock:
            if await self._publish(Author.YOU, Source.TEXT, text) is None:
                return
        await self.interview_command(cmd, "text")

    async def interview_command(self, cmd: str, via: str) -> bool:
        """Comando da spec §5.3 (``next|skip_stage|pause|end``; ``via`` = ``button|voice|text``).
        ``next``/``skip_stage`` pedem a pergunta seguinte num turno do agente. Sem run: ``False``."""
        run = self.live_run()
        if run is None:
            return False
        if via == "voice":
            self._cmd_turn = True
        if cmd == "end":
            await self._finish_interview(via)
            return True
        changed = iv_run.apply(run, cmd, self._now())  # type: ignore[arg-type]
        if changed:
            await self._push_run(run)
            if cmd in ("next", "skip_stage") and self._in_interview():
                self._schedule_opening(keep=via == "voice", prompt=INTERVIEW_NEXT_PROMPT)
        return changed

    async def _after_turn(self, you: LearningMessage | None, her: LearningMessage | None) -> None:
        """Design §5.3: depois do turno, ``run.observe`` → ``lm_interview`` e gravação; WRAP
        fechado → ``_finish_interview("done")``."""
        run = self.live_run()
        if run is None or not self._in_interview() or (you is None and her is None):
            return
        first = you if you is not None else her
        assert first is not None
        if run.first_message_id is None:
            run.first_message_id = first.id
        run.last_message_id = (her or first).id
        changed = iv_run.observe(run, her.text if her is not None else "", you is not None,
                                 self._now())
        if run.state not in _RUN_LIVE:
            await self._finish_interview("done")
            return
        if changed:
            await self._push_run(run)
        else:
            try:
                await self.interviews.save_run(run)
            except Exception:
                log.warning("learning: simulação %s não gravada", run.id, exc_info=True)

    async def _close_run(self, reason: str) -> None:
        """Sessão fechando (``button|voice|idle|shutdown``) com run viva: fecha e grava; com
        ≥ 3 respostas o retorno sai em segundo plano, gravado e não publicado (R4.5)."""
        run, self.run = self.live_run(), None
        if run is None:
            return
        iv_run.finish(run, reason, self._now())
        try:
            await self.interviews.save_run(run, reason)
        except Exception:
            log.warning("learning: simulação %s não gravada no fechamento", run.id, exc_info=True)
        if run.answers >= iv_debrief.MIN_ANSWERS:  # R4.5: gera e grava, não publica
            self._spawn(self._debrief_run(run, publish=False), "retorno da entrevista")

    async def _finish_interview(self, reason: str) -> None:
        """Fim da simulação (``end`` ou WRAP): fecha a run, manda o ``lm_interview`` final, volta
        o tema a ``free`` (design §6) e agenda o retorno (LI2.3) — o turno não espera por ele.
        Com < 3 respostas do Pedro não há retorno, só uma linha (R4.4)."""
        run, self.run = self.run, None
        if run is None:
            return
        self._cancel_opening()
        iv_run.finish(run, reason, self._now())  # WRAP já fechou: não faz nada
        await self._push_run(run, reason)
        async with self._lock:
            active = self.session.active
            if active:
                ctx = TopicContext(Topic.FREE, Topic.FREE, LABELS[Topic.FREE], None, None)
                await self.session.set_topic(ctx)
                await self.hud.send(self._topic_msg(ctx))
        log.info("learning: entrevista %s encerrada (%s)", run.id, reason)
        if run.answers < iv_debrief.MIN_ANSWERS:
            if active:
                await self._line(DEBRIEF_TOO_SHORT.format(n=iv_debrief.MIN_ANSWERS))
            return
        self._spawn(self._debrief_run(run, publish=active), "retorno da entrevista")

    async def _debrief_run(self, run: InterviewRun, *, publish: bool) -> None:
        """Gera o retorno (uma chamada, spec §6), grava e, com ``publish`` e a mesma sessão
        aberta, manda ``lm_debrief`` + a linha curta da Condessa (R4.2). Falha: só a linha
        ``feedback not generated — <código>`` (spec §10)."""
        try:
            if self.job_model is None:
                raise ModelFailure("sem modelo para o retorno da entrevista")
            msgs = await self.repo.recent_messages(run.session_id, DEBRIEF_MESSAGES_MAX)
            obs = await self.repo.observations(run.session_id)
            result = await iv_debrief.debrief(run, msgs, obs, self.job_model,
                                              explain_language=self.cfg.explain_language)
        except ModelError as e:
            log.warning("learning: retorno da entrevista %s não gerado (%s): %s", run.id, e.code, e)
            await self._run_done(run, publish)
            if publish and self._same_session(run):
                await self._line(DEBRIEF_FAILED.format(code=e.code), speak=False)
            return
        self._debrief_meta[run.id] = (run.profile.title, run.profile.company, self.clock())
        await self.interviews.save_debrief(result)
        await self._run_done(run, publish)
        if publish and self._same_session(run):
            await self._send_debrief(result)
            await self._line(DEBRIEF_READY)

    async def _run_done(self, run: InterviewRun, publish: bool) -> None:
        """``DEBRIEFING`` → ``DONE`` gravado; ``lm_interview`` só com a mesma sessão aberta."""
        if run.state is RunState.DEBRIEFING:
            run.state = RunState.DONE
        try:
            await self.interviews.save_run(run)
        except Exception:
            log.warning("learning: simulação %s não gravada após o retorno", run.id, exc_info=True)
        if publish and self._same_session(run):
            await self.hud.send(self._iv_msg(run))

    def _same_session(self, run: InterviewRun) -> bool:
        info = self.session.info
        return info is not None and info.id == run.session_id

    async def _unseen_debrief(self) -> InterviewDebrief | None:
        try:
            return await self.interviews.unseen()
        except Exception:
            log.warning("learning: retorno pendente indisponível", exc_info=True)
            return None

    async def _send_debrief(self, result: InterviewDebrief) -> None:
        """``lm_debrief`` e marca como visto (a tela mostra uma vez, R5.2)."""
        title, company, at = self._debrief_meta.get(
            result.run_id, (DEBRIEF_TITLE, None, self.clock()))
        await self.hud.send(LmDebriefMsg(debrief=result, title=title, company=company, at=at))
        try:
            await self.interviews.mark_seen(result.run_id)
        except Exception:
            log.warning("learning: retorno %s não marcado como visto", result.run_id, exc_info=True)

    async def _line(self, text: str, *, speak: bool = True) -> None:
        """Linha curta da Condessa no histórico (falada se ``speak_replies``)."""
        async with self._lock:
            if not self.session.active:
                return
            her = await self.session.add_message(Author.CONDESSA, Source.TEXT, text)
        if her is None:
            return
        spoken = False
        if speak and self.session.speak_replies and self.speak is not None:
            try:
                spoken = await self.speak(ActionResult(ok=True, speech=text))
            except Exception:
                log.exception("learning: falha ao falar a linha do retorno")
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
        # frases fixas ("Modo aula ligado…") no idioma da fala, como no turno de voz (``_deliver``)
        result = tr_result(await self.pipeline.respond(Transcript.raw(text, language=TEXT_LANGUAGE), ctx))
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
            await self._after_turn(you, her)
        else:
            await self._after_turn(you, None)
        self._observe(you)

    def on_turn(self, transcript: Transcript, ctx: TurnContext, result: ActionResult) -> None:
        """``TurnDeps.learning``: turno de voz já entregue. Só agenda; fora do modo não faz nada."""
        if not self.session.active or not transcript.heard.strip():
            return
        if self._keep_opening:
            self._keep_opening = False  # este é o turno que pediu o tema por voz
        else:
            self._cancel_opening()  # o Pedro falou antes da abertura (P11)
        command, self._cmd_turn = self._cmd_turn, False
        result = tr_result(result)  # o chat mostra o que ela falou (a voz já sai traduzida)
        speaking = bool(result.speech) and self.pipeline.deps.speaker is not None
        self._spawn(self._voice(transcript, ctx, result, speaking, command=command), "voz")

    async def _voice(
        self, transcript: Transcript, ctx: TurnContext, result: ActionResult, speaking: bool,
        *, command: bool = False,
    ) -> None:
        heard = transcript.heard.strip()
        final = (result.redo_text or transcript.final).strip()
        async with self._lock:
            you = await self._publish(Author.YOU, Source.VOICE, heard,
                                       text_final=final if final and final != heard else None,
                                       turn_id=ctx.turn_id)
            if you is None:
                return
            her = None
            if result.speech:
                her = await self._publish(Author.CONDESSA, Source.VOICE, result.speech,
                                          speaking=speaking)
        if not command:
            await self._after_turn(you, her)
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


#: Fim de frase para o ``example`` de uma palavra salva (spec §10.3 item 2).
_SENTENCE_END = re.compile(r"[.!?]")
EXAMPLE_MAX = 240


def source_sentence(text: str, start: int, end: int) -> str:
    """A frase de ``text`` que contém a seleção ``[start, end)``, cortada por ``.``/``!``/``?``
    e limitada a ``EXAMPLE_MAX`` caracteres (spec §10.3 item 2)."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    head = max((m.end() for m in _SENTENCE_END.finditer(text, 0, start)), default=0)
    tail = _SENTENCE_END.search(text, end)
    out = " ".join(text[head:tail.end() if tail else len(text)].split())
    return out[:EXAMPLE_MAX]


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
    job_model: LearningModel | None = None,
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
    if job_model is None and isinstance(config, Config):
        job_model = _job_model(config, engine)
    wiring = LearningWiring(cfg, repo, hud, pipeline, speak=speak, clock=clock, engine=engine,
                            runtime=runtime, job_model=job_model)
    hud.on_learning = wiring.on_learning
    pipeline.deps.learning = wiring.on_turn
    if start:
        wiring.start()
    return wiring


def _job_model(config: Config, engine: LearningEngine | None) -> LearningModel | None:
    """Modelo da extração da vaga (LI1.1, D8): ``build_job_model`` sobre o orçamento do engine;
    sem registro de provedores (provedor real) cai no modelo de ações do engine."""
    budget = getattr(engine, "budget", None)
    if budget is not None:
        try:
            return iv_extract.build_job_model(config, budget=budget)
        except Exception as e:  # noqa: BLE001 - sem modelo a vaga responde error = "model"
            log.debug("learning: modelo da vaga pelo config indisponível (%s)", e)
    return getattr(engine, "model", None)
