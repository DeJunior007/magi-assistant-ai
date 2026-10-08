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
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from magi.common.contracts import LmActionMsg
from magi.learning.analyzers import ActionUnavailable, PromptOptions, analyze, ensure_available
from magi.learning.budget import LearningBudget, LearningCostTask
from magi.learning.contracts import ActionKind, ActionRequest, ActionResult, Selection
from magi.learning.model import LearningModel, ModelError, ModelInvalid
from magi.learning.repo import LearningRepo

log = logging.getLogger(__name__)

#: Cliente padrão (com P1 = A, o ``hud_bridge`` do ``gamerhud``; o socket não identifica clientes).
DEFAULT_CLIENT = "hud"
#: Código de erro de ação indisponível (ver docstring do módulo; sem nova tentativa).
UNAVAILABLE_ERROR = "model"
#: Tentativas no total quando a resposta é ``invalid`` (1 nova tentativa, LM-007).
INVALID_ATTEMPTS = 2
#: Mensagens anteriores à selecionada no contexto do analisador (``ActionRequest.context``).
CONTEXT_BEFORE = 2
#: Janela de mensagens recentes lida para montar o contexto.
CONTEXT_WINDOW = 50

Clock = Callable[[], float]


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
    """Fila de ações do Learning Mode (LM3.3). Observações entram no LM4.1 usando ``slot``."""

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

    # -- ciclo de vida --------------------------------------------------------------------------

    @property
    def actions_pending(self) -> int:
        """Ações esperando ou rodando (observações não começam enquanto > 0)."""
        return sum(1 for j in self._pending.values() if not j.cancelled)

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name=f"learning-actions-{next(self._seq)}")

    async def aclose(self) -> None:
        """Para o worker; ações ainda na fila voltam ``None``."""
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
        return await self.request(req, client, started=started)

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

    # -- util -----------------------------------------------------------------------------------

    def _ms(self, started: float) -> int:
        return max(0, round((self.clock() - started) * 1000))

    def _fail(self, action_id: str, kind: ActionKind, error: str, started: float) -> ActionResult:
        return ActionResult(action_id, kind, False, None, error, False, self._ms(started), 0.0)


__all__ = [
    "CONTEXT_BEFORE",
    "DEFAULT_CLIENT",
    "INVALID_ATTEMPTS",
    "UNAVAILABLE_ERROR",
    "LearningEngine",
    "build_request",
]
