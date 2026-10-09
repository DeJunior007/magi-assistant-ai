"""Learning Engine — fila de ações (tarefa LM3.3; design §6, spec §5 "Ciclo", ENG-001, LM-006, LM-007).

Ciclo de uma ação (spec §5)::

    lm_action → disponível? → cache? (cached = true) → orçamento? → fila de ações
              → Semaphore(1) → analisador (LearningModel, timeout) → schema ok
              → grava learning_action_results → lm_result

- **Disponibilidade:** pedido que o menu não deveria ter oferecido (``ActionUnavailable``:
  mensagem desconhecida, recorte fora do texto, Improve em mensagem da Condessa, Vocabulary > 4
  palavras, Translate > 400 caracteres) volta na hora com ``ok = false, error = "model"``
  (``UNAVAILABLE_ERROR``), **sem** nova tentativa, sem modelo e sem cache. ``ACTION_ERRORS`` não
  tem código próprio para isso; ``invalid`` dispararia nova tentativa e ``model`` já é a falha
  genérica "o modelo não deu resposta útil" do balão (design §12). Responder (em vez de calar)
  fecha o balão na hora em vez de esperar o timeout de UI de 12 s (LM3.4).
- **Cache:** mesma mensagem + mesmo ``kind`` + mesmo ``[start, end)`` → devolve o resultado
  gravado com o ``id`` novo, ``cached = true`` e custo 0, sem chamar o modelo. Banco fora = sem
  cache (spec §11).
- **Orçamento:** com ``budget``, teto estourado → ``budget`` antes de entrar na fila (LM-006,
  CA-13). O custo é gravado em ``costs`` pelo próprio ``LearningModel`` (``budget.record``).
- **Fila:** ações (pedidas pelo Pedro) têm prioridade; um único worker as consome e toda chamada
  de modelo passa por ``slot`` (``Semaphore(1)``), que as observações (LM4.1) também usam —
  no máximo uma chamada do Learning Engine por vez. ``actions_pending`` diz ao LM4.1 se há ação
  esperando (observação não começa enquanto houver).
- **Cancelamento:** nova ação do mesmo cliente cancela a anterior **ainda na fila** (a que já
  está no modelo termina e grava; vai ao cache). A cancelada não recebe ``lm_result`` (``None``).
- **Falhas (LM-007):** 1 nova tentativa só em ``invalid``; ``timeout``/``model``/``budget`` voltam
  direto com ``ok = false``. Só resultados ``ok`` são gravados.

Fila de observações (tarefa LM4.1; spec §9, design §6, ENG-001, CA-02, CA-03, CA-14)::

    wiring → publish(msg do Pedro) → LearningBus (50, descarta o mais antigo) → worker
           → gate (núcleo em listening/sleeping/followup e nenhuma ação pendente)
           → Semaphore(1) → analyzers/observe → grava (+ recurring derivado) → on_observed

- ``publish`` é síncrono e não bloqueia; só mensagens do Pedro, só com ``observe_model`` e abaixo
  de ``observe_daily_max`` (``LearningBudget``). O orçamento é conferido de novo antes da chamada:
  teto estourado = observação descartada (observações pausadas, spec §11).
- **Gate de estado:** observação nunca **começa** com o núcleo em ``thinking``/``speaking`` (nem
  ``confirming``) ou com ação pendente; espera (``gate_poll_s``) até voltar. Ações rodam sempre.
- Falha de modelo (timeout, budget, erro) descarta a observação daquela mensagem; ``invalid`` tem
  1 nova tentativa, como as ações.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from magi.common.contracts import LmActionMsg, LmSavedMsg, TurnState
from magi.learning.analyzers import ActionUnavailable, PromptOptions, analyze, ensure_available
from magi.learning.analyzers import observe as observer
from magi.learning.budget import LearningBudget, LearningCostTask
from magi.learning.bus import LearningBus
from magi.learning.contracts import (
    ActionKind,
    ActionRequest,
    ActionResult,
    Author,
    LearningMessage,
    Observation,
    Selection,
)
from magi.learning.model import LearningModel, ModelError, ModelInvalid
from magi.learning.repo import LearningRepo, StoredAction, normalize_term

log = logging.getLogger(__name__)

#: Cliente padrão (com P1 = A, o ``hud_bridge`` do ``gamerhud``; o socket não identifica clientes).
DEFAULT_CLIENT = "hud"
#: Quantos resultados de Vocabulary a engine lembra para o ``lm_save`` (LM3.5).
VOCAB_KEEP = 200
#: Código de erro de ação indisponível (ver docstring do módulo; sem nova tentativa).
UNAVAILABLE_ERROR = "model"
#: Tentativas no total quando a resposta é ``invalid`` (1 nova tentativa, LM-007).
INVALID_ATTEMPTS = 2
#: Mensagens anteriores à selecionada no contexto do analisador (``ActionRequest.context``).
CONTEXT_BEFORE = 2
#: Janela de mensagens recentes lida para montar o contexto.
CONTEXT_WINDOW = 50

#: Estados do núcleo em que uma observação pode começar (design §6, CA-03).
OBSERVE_STATES = frozenset({TurnState.LISTENING, TurnState.SLEEPING, TurnState.FOLLOWUP})
#: Intervalo de checagem do gate enquanto ele está fechado (s).
GATE_POLL_S = 0.2

Clock = Callable[[], float]
#: ``True`` = o núcleo está num estado em que observação pode começar.
Gate = Callable[[], bool]
#: Recebe ``(session_id, lista inteira de observações da sessão)`` depois de gravar (``lm_obs``).
ObsSink = Callable[[str, list[Observation]], Awaitable[None]]


def state_gate(states: Callable[[], Iterable[Any]]) -> Gate:
    """Gate a partir dos estados dos satélites (``TurnMachine.state``): aberto se **todos** estão
    em ``OBSERVE_STATES`` (sem satélite = aberto). Estado desconhecido fecha o gate."""

    def gate() -> bool:
        for st in states():
            try:
                if TurnState(st) not in OBSERVE_STATES:
                    return False
            except ValueError:
                return False
        return True

    return gate


@dataclass(eq=False)
class _Job:
    request: ActionRequest
    client: str
    started: float
    future: asyncio.Future[ActionResult | None] = field(repr=False)
    cancelled: bool = False
    running: bool = False


async def build_request(repo: LearningRepo, msg: LmActionMsg) -> ActionRequest:
    """``ActionRequest`` de uma ``lm_action``: a mensagem selecionada + até 2 anteriores da
    mesma sessão. ``ActionUnavailable`` se a mensagem não existe ou o recorte sai do texto."""
    target = await repo.get_message(msg.message_id)
    if target is None:
        raise ActionUnavailable(f"mensagem {msg.message_id} desconhecida")
    if msg.end > len(target.text):
        raise ActionUnavailable(f"seleção [{msg.start}, {msg.end}) fora da mensagem {msg.message_id}")
    sel = Selection(target.id, msg.start, msg.end, target.text[msg.start : msg.end])
    before = []
    try:
        recent = await repo.recent_messages(target.session_id, CONTEXT_WINDOW)
        before = [m for m in recent if m.id < target.id][-CONTEXT_BEFORE:]
    except Exception:
        log.warning("learning: contexto da ação sem mensagens anteriores", exc_info=True)
    return ActionRequest(msg.id, ActionKind(msg.kind), sel, [*before, target])


class LearningEngine:
    """Fila de ações (LM3.3) e de observações (LM4.1) do Learning Mode; ``slot`` é comum às duas."""

    def __init__(
        self,
        model: LearningModel,
        repo: LearningRepo,
        *,
        budget: LearningBudget | None = None,
        options: PromptOptions | None = None,
        timeout_s: float | None = None,
        model_name: str | None = None,
        clock: Clock = time.monotonic,
        observe_model: LearningModel | None = None,
        observe_timeout_s: float | None = None,
        observe_model_name: str | None = None,
        gate: Gate | None = None,
        bus: LearningBus[LearningMessage] | None = None,
        on_observed: ObsSink | None = None,
        gate_poll_s: float = GATE_POLL_S,
    ) -> None:
        self.model = model
        self.repo = repo
        self.budget = budget
        self.options = options
        self.timeout_s = timeout_s
        self.model_name = model_name or getattr(model, "model", None)
        self.clock = clock
        #: No máximo uma chamada de modelo do Learning Engine por vez (design §6).
        self.slot = asyncio.Semaphore(1)
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._pending: dict[str, _Job] = {}
        self._worker: asyncio.Task[None] | None = None
        self._seq = itertools.count()
        # -- observações (LM4.1) --
        self.observe_model = observe_model
        self.observe_timeout_s = observe_timeout_s
        self.observe_model_name = observe_model_name or getattr(observe_model, "model", None)
        self.gate = gate
        self.bus: LearningBus[LearningMessage] = bus if bus is not None else LearningBus()
        self.on_observed = on_observed
        self.gate_poll_s = gate_poll_s
        self._observer: asyncio.Task[None] | None = None
        self._obs_busy = False
        # -- palavras salvas (LM3.5) --
        #: Vocabulary ``ok`` respondidos, por ``id`` do pedido (o do cache não está no banco).
        self.vocab: dict[str, StoredAction] = {}

    # -- ciclo de vida --------------------------------------------------------------------------

    @property
    def actions_pending(self) -> int:
        """Ações esperando ou rodando (observações não começam enquanto > 0)."""
        return sum(1 for j in self._pending.values() if not j.cancelled)

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name=f"learning-actions-{next(self._seq)}")

    async def aclose(self) -> None:
        """Para os workers; ações ainda na fila voltam ``None``, observações na fila são descartadas."""
        if self._observer is not None:
            self._observer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._observer
            self._observer = None
        self.bus.clear()
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        while not self._queue.empty():
            job = self._queue.get_nowait()
            if not job.future.done():
                job.future.set_result(None)
        self._pending.clear()

    # -- entrada --------------------------------------------------------------------------------

    async def handle(self, msg: LmActionMsg, client: str = DEFAULT_CLIENT) -> ActionResult | None:
        """``lm_action`` → ``ActionResult`` (``None`` = cancelada por uma ação mais nova)."""
        started = self.clock()
        try:
            req = await build_request(self.repo, msg)
        except ActionUnavailable as e:
            log.info("learning: ação %s indisponível: %s", msg.id, e)
            return self._fail(msg.id, ActionKind(msg.kind), UNAVAILABLE_ERROR, started)
        except Exception:
            log.exception("learning: falha ao montar a ação %s", msg.id)
            return self._fail(msg.id, ActionKind(msg.kind), "model", started)
        result = await self.request(req, client, started=started)
        if result is not None and result.ok and result.kind is ActionKind.VOCABULARY:
            sel = req.selection
            self.vocab[result.id] = StoredAction(result, sel.message_id, sel.start, sel.end)
            while len(self.vocab) > VOCAB_KEEP:
                self.vocab.pop(next(iter(self.vocab)))
        return result

    # -- palavras salvas (LM3.5, spec §10.3) ----------------------------------------------------

    async def resolve_vocab(self, action_id: str) -> StoredAction | None:
        """Vocabulary ``ok`` pelo ``action_id`` (memória da sessão, depois o banco); ``None`` se
        não existir ou for de outro ``kind``/com erro (``lm_save`` recusado)."""
        stored = self.vocab.get(action_id)
        if stored is None:
            try:
                stored = await self.repo.get_action(action_id)
            except Exception:
                log.warning("learning: ação %s não lida do banco", action_id, exc_info=True)
                return None
        if stored is None or not stored.result.ok or stored.result.kind is not ActionKind.VOCABULARY:
            return None
        if not normalize_term(str((stored.result.data or {}).get("term") or "")):
            return None
        return stored

    async def saved_state(self, result: ActionResult | None) -> LmSavedMsg | None:
        """``lm_saved`` do ``norm`` do termo depois de um ``lm_result`` de vocabulary ``ok``
        (inclusive do cache), para a estrela abrir no estado certo; ``None`` nos outros."""
        if result is None or not result.ok or result.kind is not ActionKind.VOCABULARY:
            return None
        norm = normalize_term(str((result.data or {}).get("term") or ""))
        if not norm:
            return None
        try:
            words = await self.repo.saved_words()
        except Exception:
            log.warning("learning: palavras salvas indisponíveis", exc_info=True)
            return LmSavedMsg(norm, False)
        word = next((w for w in words if w.norm == norm and w.removed_at is None), None)
        return LmSavedMsg(norm, word is not None, word.id if word is not None else None)

    async def request(
        self, req: ActionRequest, client: str = DEFAULT_CLIENT, *, started: float | None = None
    ) -> ActionResult | None:
        """Ciclo da spec §5 para um ``ActionRequest`` já montado."""
        started = self.clock() if started is None else started
        try:
            ensure_available(req)
        except ActionUnavailable as e:
            log.info("learning: ação %s indisponível: %s", req.id, e)
            return self._fail(req.id, req.kind, UNAVAILABLE_ERROR, started)

        cached = await self._cached(req)
        if cached is not None:
            return replace(cached, id=req.id, cached=True, ms=self._ms(started), cost_usd=0.0)

        if self.budget is not None and not await self.budget.allowed(LearningCostTask.ACTIONS):
            return self._fail(req.id, req.kind, "budget", started)

        old = self._pending.get(client)
        if old is not None and not old.running and not old.cancelled:
            old.cancelled = True
            if not old.future.done():
                old.future.set_result(None)
            log.info("learning: ação %s cancelada por %s", old.request.id, req.id)
        job = _Job(req, client, started, asyncio.get_running_loop().create_future())
        self._pending[client] = job
        self._queue.put_nowait(job)
        self._ensure_worker()
        return await asyncio.shield(job.future)

    # -- worker ---------------------------------------------------------------------------------

    async def _work(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job.cancelled:
                    continue
                job.running = True
                result = await self._run(job)
                if not job.future.done():
                    job.future.set_result(result)
            except asyncio.CancelledError:
                if not job.future.done():
                    job.future.set_result(None)
                raise
            except Exception:
                log.exception("learning: erro na ação %s", job.request.id)
                if not job.future.done():
                    job.future.set_result(self._fail(job.request.id, job.request.kind, "model", job.started))
            finally:
                if self._pending.get(job.client) is job:
                    del self._pending[job.client]
                self._queue.task_done()

    async def _run(self, job: _Job) -> ActionResult:
        req = job.request
        error = "model"
        async with self.slot:
            for attempt in range(1, INVALID_ATTEMPTS + 1):
                try:
                    data, cost = await self._call(req)
                except ModelInvalid as e:
                    error = e.code
                    log.info("learning: ação %s inválida (tentativa %d): %s", req.id, attempt, e)
                    continue
                except ModelError as e:
                    error = e.code
                    log.info("learning: ação %s falhou (%s): %s", req.id, e.code, e)
                    break
                except TimeoutError:
                    error = "timeout"
                    log.info("learning: ação %s passou de %.1f s", req.id, self.timeout_s or 0)
                    break
                except ActionUnavailable as e:
                    error = UNAVAILABLE_ERROR
                    log.info("learning: ação %s indisponível: %s", req.id, e)
                    break
                result = ActionResult(req.id, req.kind, True, data, None, False,
                                      self._ms(job.started), float(cost))
                await self._save(req, result)
                return result
        return self._fail(req.id, req.kind, error, job.started)

    async def _call(self, req: ActionRequest) -> tuple[dict, float]:
        coro = analyze(self.model, req, self.options)
        if self.timeout_s is None:
            return await coro
        return await asyncio.wait_for(coro, self.timeout_s)

    # -- banco ----------------------------------------------------------------------------------

    async def _cached(self, req: ActionRequest) -> ActionResult | None:
        sel = req.selection
        try:
            return await self.repo.cached_action(sel.message_id, req.kind, sel.start, sel.end)
        except Exception:
            log.warning("learning: cache de ações indisponível", exc_info=True)
            return None

    async def _save(self, req: ActionRequest, result: ActionResult) -> None:
        sel = req.selection
        try:
            await self.repo.save_action(result, message_id=sel.message_id, sel_start=sel.start,
                                        sel_end=sel.end, model=self.model_name)
        except Exception:
            log.warning("learning: ação %s não gravada", req.id, exc_info=True)

    # -- observações (LM4.1) --------------------------------------------------------------------

    @property
    def observing(self) -> bool:
        """Há modelo de observação (``[learning] observe`` e ``[tasks] learning_observe``)."""
        return self.observe_model is not None

    @property
    def observations_idle(self) -> bool:
        """Nenhuma observação na fila nem rodando (testes e medição)."""
        return len(self.bus) == 0 and not self._obs_busy

    def publish(self, msg: LearningMessage) -> bool:
        """Gancho do turno (síncrono, nunca bloqueia): mensagem do Pedro → bus. ``False`` = não
        entrou (sem modelo, mensagem da Condessa ou limite diário atingido)."""
        if self.observe_model is None or msg.author is not Author.YOU:
            return False
        if self.budget is not None and self.budget.observe_today >= self.budget.observe_daily_max:
            log.info("learning: limite diário de observações (%d) atingido", self.budget.observe_daily_max)
            return False
        self.bus.publish(msg)
        self._ensure_observer()
        return True

    def _ensure_observer(self) -> None:
        if self._observer is None or self._observer.done():
            self._observer = asyncio.create_task(self._observe_loop(), name="learning-observe")

    def gate_open(self) -> bool:
        """Observação pode começar agora: estado do núcleo ok e nenhuma ação pendente (design §6)."""
        if self.actions_pending:
            return False
        if self.gate is None:
            return True
        try:
            return bool(self.gate())
        except Exception:
            log.warning("learning: gate de estado falhou; observação espera", exc_info=True)
            return False

    async def wait_gate(self) -> None:
        while not self.gate_open():
            await asyncio.sleep(self.gate_poll_s)

    async def _observe_loop(self) -> None:
        while True:
            msg = await self.bus.get()
            self._obs_busy = True
            try:
                await self.observe_message(msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("learning: erro na observação da mensagem %s", msg.id)
            finally:
                self._obs_busy = False

    async def observe_message(self, msg: LearningMessage) -> list[Observation] | None:
        """Observa uma mensagem do Pedro (spec §9): espera o gate, chama o modelo, grava os itens
        e o ``recurring`` derivado e chama ``on_observed`` com a lista inteira da sessão.
        Devolve as observações novas gravadas (``None`` = não observou)."""
        if self.observe_model is None or msg.author is not Author.YOU:
            return None
        if self.budget is not None and not await self.budget.allowed(LearningCostTask.OBSERVE):
            log.info("learning: observação da mensagem %s pausada (orçamento/limite diário)", msg.id)
            return None
        context = await self._obs_context(msg)
        items = None
        while items is None:
            await self.wait_gate()
            async with self.slot:
                if not self.gate_open():  # o estado mudou enquanto esperava o slot
                    continue
                items = await self._observe_call(msg, context)
                if items is None:
                    return None
        try:
            existing = await self.repo.observations(msg.session_id)
        except Exception:
            log.warning("learning: observações da sessão indisponíveis", exc_info=True)
            existing = []
        new = [*items, *observer.derive_recurring(existing, items)]
        saved: list[Observation] = []
        for obs in new:
            try:
                saved.append(await self.repo.add_observation(obs, model=self.observe_model_name))
            except Exception:
                log.warning("learning: observação %s não gravada", obs.rule_key, exc_info=True)
        if saved and self.on_observed is not None:
            try:
                every = await self.repo.observations(msg.session_id)
            except Exception:
                log.warning("learning: lista de observações indisponível", exc_info=True)
                every = [*existing, *saved]
            await self.on_observed(msg.session_id, every)
        return saved

    async def _obs_context(self, msg: LearningMessage) -> list[LearningMessage]:
        try:
            recent = await self.repo.recent_messages(msg.session_id, CONTEXT_WINDOW)
        except Exception:
            log.warning("learning: observação sem contexto", exc_info=True)
            return []
        return [m for m in recent if m.id < msg.id][-observer.CONTEXT_BEFORE:]

    async def _observe_call(
        self, msg: LearningMessage, context: list[LearningMessage]
    ) -> list[Observation] | None:
        assert self.observe_model is not None
        for attempt in range(1, INVALID_ATTEMPTS + 1):
            coro = observer.observe(self.observe_model, msg, context, self.options)
            try:
                if self.observe_timeout_s is None:
                    items, _cost = await coro
                else:
                    items, _cost = await asyncio.wait_for(coro, self.observe_timeout_s)
            except ModelInvalid as e:
                log.info("learning: observação de %s inválida (tentativa %d): %s", msg.id, attempt, e)
                continue
            except ModelError as e:
                log.info("learning: observação de %s falhou (%s): %s", msg.id, e.code, e)
                return None
            except TimeoutError:
                log.info("learning: observação de %s passou de %.1f s", msg.id, self.observe_timeout_s or 0)
                return None
            return items
        return None

    # -- util -----------------------------------------------------------------------------------

    def _ms(self, started: float) -> int:
        return max(0, round((self.clock() - started) * 1000))

    def _fail(self, action_id: str, kind: ActionKind, error: str, started: float) -> ActionResult:
        return ActionResult(action_id, kind, False, None, error, False, self._ms(started), 0.0)


__all__ = [
    "CONTEXT_BEFORE",
    "DEFAULT_CLIENT",
    "GATE_POLL_S",
    "INVALID_ATTEMPTS",
    "OBSERVE_STATES",
    "UNAVAILABLE_ERROR",
    "LearningEngine",
    "build_request",
    "state_gate",
]
