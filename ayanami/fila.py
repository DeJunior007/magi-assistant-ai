"""Fila ``procrastinate`` 3.10 da Ayanami (dono: Y3.1; spec §4, design §4.2, S5).

- :data:`TAREFAS`: a tabela da §4.2 (17 tarefas; ``embeddings.lote`` só com ``[embeddings]
  ligado``). Cada linha diz fila, prazo, retry, lock, cron, prioridade e o corpo
  (``"módulo:função"`` em ``ayanami.workers``, importado só quando o job roda).
- :func:`montar` cria um ``procrastinate.App`` com as tarefas registradas; ``periodicas=False``
  (workers ``rapida``/``lenta``) não registra os crons — só o worker ``agendada`` defere periódicas.
- ``app`` (atributo do módulo): o ``App`` de produção com ``PsycopgConnector`` sobre
  :func:`ayanami.db.dsn_padrao` e o ``ayanami.toml``; montado no 1º acesso (importar o módulo não
  lê ambiente nem arquivo). A API usa :func:`app_aberto` (abre o conector uma vez) só para
  ``defer``/``cancel``.

Contrato do corpo: ``async def corpo(deps: Deps, contexto: JobContext, **kwargs) -> dict | None``.
Jobs ligados a uma linha de ``tarefas`` recebem ``tarefa_id`` (str); o retorno (``{"texto",
"dados"}``) vira ``tarefas.resultado`` pelo middleware de :mod:`ayanami.tarefas`. Periódicas
recebem ``timestamp`` (int, UTC).

Prazo: ``asyncio.timeout(prazo)`` em volta do corpo; estourou → :class:`PrazoEstourado`, que a
:class:`Repeticao` nunca repete (``falhou`` com ``erro="prazo"``). Abort pedido pelo usuário
(``cancel_job_by_id_async(abort=True)``) chega como ``CancelledError`` e vira ``JobAborted`` (sem
retry); abort por desligamento do worker continua ``CancelledError`` e volta a ``todo`` se a
tarefa tem retry (S5).

Crons em UTC (S5): o ``periodic`` da 3.10 ignora o ``TZ``.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import procrastinate
from procrastinate import JobContext, RetryStrategy
from procrastinate.exceptions import JobAborted
from procrastinate.job_context import AbortReason

from ayanami.config import AyanamiConfig

FILAS = ("rapida", "agendada", "lenta")
PRIORIDADE_PEDIDO = 20
PRIORIDADE_MONITOR = 10
PRIORIDADE_LOTE = 0


class PrazoEstourado(Exception):
    """O corpo passou do prazo da §4.2 (nunca repetido)."""

    def __init__(self, nome: str, prazo_s: int) -> None:
        super().__init__(f"prazo: {nome} passou de {prazo_s} s")
        self.nome = nome
        self.prazo_s = prazo_s


class Repeticao(RetryStrategy):
    """``RetryStrategy`` que não repete prazo estourado."""

    def get_retry_decision(self, *, exception: BaseException, job: Any) -> Any:
        if isinstance(exception, PrazoEstourado):
            return None
        return super().get_retry_decision(exception=exception, job=job)


@dataclass(frozen=True)
class Def:
    nome: str
    fila: str
    prazo_s: int
    tentativas: int  # "a" da §4.2 (1 = sem retry)
    espera: int = 0  # "w"
    lock: str | None = None  # lock fixo da tarefa
    queueing_lock_chave: bool = False  # queueing_lock = chave da tarefa, no defer
    lock_por_id: str | None = None  # prefixo do lock dado no defer (ex.: "monitor:")
    cron: str | None = None  # UTC
    prioridade: int = PRIORIDADE_LOTE
    corpo: str = ""
    so_com_embeddings: bool = False

    @property
    def retry(self) -> Repeticao | None:
        if self.tentativas <= 1:
            return None
        return Repeticao(max_attempts=self.tentativas, wait=self.espera, exponential_wait=2)


_W = "ayanami.workers."
TAREFAS: tuple[Def, ...] = (
    Def("agente.pesquisar", "rapida", 30 * 60, 2, 30, queueing_lock_chave=True,
        prioridade=PRIORIDADE_PEDIDO, corpo=_W + "agente:pesquisar"),
    Def("agente.lembrete", "rapida", 60, 3, 10, queueing_lock_chave=True,
        prioridade=PRIORIDADE_MONITOR, corpo=_W + "agente:lembrete"),
    Def("monitor.passo", "rapida", 5 * 60, 2, 30, lock_por_id="monitor:",
        prioridade=PRIORIDADE_MONITOR, corpo=_W + "agente:monitor_passo"),
    Def("push.enviar", "rapida", 30, 3, 5, prioridade=PRIORIDADE_PEDIDO, corpo=_W + "push:enviar"),
    Def("monitores.varrer", "agendada", 60, 1, lock="varrer", cron="*/15 * * * *",
        corpo=_W + "agente:monitores_varrer"),
    Def("noticias.coletar", "agendada", 45 * 60, 2, 300, lock="noticias", cron="0 */2 * * *",
        corpo=_W + "noticias:coletar"),
    Def("progresso.atualizar", "agendada", 10 * 60, 2, 300, lock="progresso", cron="15 */6 * * *",
        corpo=_W + "noticias:progresso"),
    Def("backup.restic", "agendada", 60 * 60, 3, 600, lock="restic", corpo=_W + "backup:restic"),
    Def("backup.dump_ayanami", "agendada", 15 * 60, 2, 60, lock="restic", cron="0 7 * * *",
        corpo=_W + "backup:dump_ayanami"),
    Def("backup.enviar", "agendada", 60 * 60, 3, 600, lock="restic", cron="30 7 * * *",
        corpo=_W + "backup:enviar"),
    Def("backup.reter", "agendada", 60 * 60, 2, 600, lock="restic", cron="0 8 * * 0",
        corpo=_W + "backup:reter"),
    Def("backup.verificar", "agendada", 90 * 60, 1, lock="restic", cron="30 8 * * 0",
        corpo=_W + "backup:verificar"),
    Def("backup.restore_teste", "agendada", 90 * 60, 1, lock="restic", cron="0 9 1 * *",
        corpo=_W + "backup:restore_teste"),
    Def("limpeza.diaria", "agendada", 10 * 60, 2, 60, lock="limpeza", cron="30 6 * * *",
        corpo=_W + "manutencao:limpeza_diaria"),
    Def("fila.reanimar", "agendada", 60, 1, lock="reanimar", cron="*/5 * * * *",
        corpo=_W + "manutencao:reanimar"),
    Def("stt.transcrever", "lenta", 60 * 60, 2, 60, queueing_lock_chave=True,
        prioridade=PRIORIDADE_PEDIDO, corpo=_W + "stt:transcrever"),
    Def("voz.cache_frases", "lenta", 30 * 60, 1, lock="voz", cron="0 6 * * 1",
        corpo=_W + "voz:cache_frases"),
    Def("embeddings.lote", "lenta", 30 * 60, 2, 60, lock="emb", corpo=_W + "embeddings:lote",
        so_com_embeddings=True),
)
POR_NOME: Mapping[str, Def] = {d.nome: d for d in TAREFAS}

Corpo = Callable[..., Awaitable[Any]]


def resolver_corpo(caminho: str) -> Corpo:
    modulo, _, funcao = caminho.partition(":")
    return getattr(importlib.import_module(modulo), funcao)


def deps_do(contexto: JobContext) -> Any:
    deps = (contexto.additional_context or {}).get("deps")
    if deps is None:
        raise RuntimeError("job sem deps (o worker passa additional_context={'deps': ...})")
    return deps


def registrar(app: procrastinate.App, d: Def, corpo: Corpo | None = None,
              *, periodica: bool = True) -> Any:
    """Registra ``d`` em ``app`` (``corpo`` explícito só nos testes; senão ``d.corpo``)."""

    async def job(contexto: JobContext, **kwargs: Any) -> Any:
        fn = corpo or resolver_corpo(d.corpo)
        deps = deps_do(contexto)
        try:
            async with asyncio.timeout(d.prazo_s):
                return await fn(deps, contexto, **kwargs)
        except TimeoutError as e:
            raise PrazoEstourado(d.nome, d.prazo_s) from e
        except asyncio.CancelledError:
            if contexto.abort_reason() == AbortReason.USER_REQUEST:
                raise JobAborted("cancelada") from None
            raise

    job.__name__ = d.nome.replace(".", "_")
    job.__qualname__ = job.__name__
    tarefa = app.task(name=d.nome, queue=d.fila, retry=d.retry or False, pass_context=True,
                      priority=d.prioridade, lock=d.lock)(job)
    if d.cron and periodica:
        app.periodic(cron=d.cron, periodic_id=d.nome, queueing_lock=d.nome)(tarefa)
    return tarefa


def montar(cfg: AyanamiConfig | None, connector: Any, *, periodicas: bool = True) -> procrastinate.App:
    """App com as tarefas da §4.2 (``embeddings.lote`` só com ``[embeddings] ligado``)."""
    app = procrastinate.App(connector=connector)
    emb = bool(cfg and cfg.embeddings.ligado)
    for d in TAREFAS:
        if d.so_com_embeddings and not emb:
            continue
        registrar(app, d, periodica=periodicas)
    return app


def defer_opcoes(nome: str, *, chave: str | None = None, lock_id: str | None = None,
                 prioridade: int | None = None, **extra: Any) -> dict[str, Any]:
    """Opções de ``configure_task`` para deferir ``nome`` (locks da §4.2)."""
    d = POR_NOME[nome]
    op: dict[str, Any] = {"priority": d.prioridade if prioridade is None else prioridade}
    if d.queueing_lock_chave and chave:
        op["queueing_lock"] = chave
    if d.lock_por_id and lock_id is not None:
        op["lock"] = f"{d.lock_por_id}{lock_id}"
    op.update(extra)
    return op


# --------------------------------------------------------------------------- app de produção

_app: procrastinate.App | None = None
_aberto = False
_trava: asyncio.Lock | None = None


def app_de_producao(*, periodicas: bool = True) -> procrastinate.App:
    from ayanami import config as cfgmod
    from ayanami.db import dsn_padrao, recusar_magi

    dsn = dsn_padrao()
    recusar_magi(dsn)
    cfg = cfgmod.ler(cfgmod.CAMINHO_PADRAO)
    return montar(cfg, procrastinate.PsycopgConnector(conninfo=dsn), periodicas=periodicas)


def __getattr__(nome: str) -> Any:
    global _app
    if nome == "app":
        if _app is None:
            _app = app_de_producao()
        return _app
    raise AttributeError(nome)


async def app_aberto(app: procrastinate.App | None = None) -> procrastinate.App:
    """``app`` (padrão: o de produção) com o conector aberto, uma vez por processo."""
    global _aberto, _trava
    if app is not None:
        return app
    if _trava is None:
        _trava = asyncio.Lock()
    async with _trava:
        prod = __getattr__("app")
        if not _aberto:
            await prod.open_async()
            _aberto = True
        return prod
