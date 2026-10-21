"""Modo nuvem: o turno atendido pela Ayanami com o PC desligado (dono: Y6.3; spec §6.4, §6.5).

:func:`atender` (chamado pela rota do turno, Y6.4):

1. Roteador local (``magi/core/intents.yaml``, rapidfuzz, catálogo do último ``ola`` da casa):
   ``tv.*`` com nota de execução vai direto à casa, **sem LLM**; outra intenção local que não cabe
   na nuvem (jogo, HUD, RGB, música, volume do PC, sistema, Learning...) → ``pc_offline_pedido``.
2. Teto da nuvem batido (``budget.ensure_allowed(AGENT)`` → ``BudgetExceeded``): sem LLM;
   "novidades" lê o feed guardado, o resto → ``sem_verba``.
3. Senão: ``GraphAgent`` com a persona da Condessa + :data:`LINHA_NUVEM`, **só** as ferramentas de
   :data:`NUVEM_PODE`, histórico = últimos ``[nuvem] contexto_turnos`` de ``nuvem_turnos`` do
   dispositivo.

``tv_desligar`` (perigosa) vira uma confirmação (:class:`ayanami.confirmacoes.Confirmacoes`,
tipo :data:`TIPO_CONFIRMA`) respondida no PWA; o executor manda a ``acao`` confirmada à casa.
Todo turno grava ``nuvem_turnos`` (texto, sem áudio). Exceção vira ``erro_generico``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

import yaml

from ayanami.nuvem_tools import (
    NuvemFerramentasDeps,
    PortaTarefas,
    TvActionsNuvem,
    ferramentas,
    ferramentas_tv,
    noticias_do_db,
)
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    BudgetExceeded,
    ChatMessage,
    ProviderTask,
    RouteKind,
    TurnContext,
    WakeSource,
)
from magi.core.router import INTENTS_PATH, LocalRouter, load_intents
from magi.elo.converte import card_de_cardmsg, pedido_de_request, request_de_pedido
from magi.elo.ids import novo_id
from magi.elo.mensagens import AcaoPedido, TurnoFim

log = logging.getLogger(__name__)

NUVEM_PODE: Final = ("news_query", "tarefa_criar", "tarefa_listar", "tarefa_cancelar",
                     "lembrete_criar", "monitor_criar", "estado", "servidor", "tv_ligar",
                     "tv_desligar", "tv_volume", "tv_mudo", "tv_app", "tv_entrada")
LINHA_NUVEM: Final = ("Agora você está na nuvem, sem a memória do PC; diga isso quando fizer "
                      "diferença. Aqui não dá para mexer em jogos, HUD, RGB, Spotify, volume do PC "
                      "nem abrir coisas no PC.")
FRASES_PATH: Final = Path(__file__).with_name("frases.yaml")
FRASES_CHAVES: Final = ("casa_offline", "pc_offline_pedido", "sem_verba", "erro_generico", "pc_caiu")
TIPO_CONFIRMA: Final = "nuvem.tv"
#: Intenções locais que a nuvem atende (o resto do ``intents.yaml`` é coisa do PC).
CABE_NA_NUVEM: Final = ("tv.", "news.", "confirm.", "magi.help")
TEXTO_MAX: Final = 16000


def carregar_frases(caminho: Path = FRASES_PATH) -> dict[str, str]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    faltando = [k for k in FRASES_CHAVES if not isinstance(dados.get(k), str)]
    if faltando:
        raise ValueError(f"frases.yaml sem {', '.join(faltando)}")
    return {str(k): str(v) for k, v in dados.items()}


def cabe_na_nuvem(intent_id: str) -> bool:
    return any(intent_id == p or intent_id.startswith(p) for p in CABE_NA_NUVEM)


# --------------------------------------------------------------------------- portas


class TurnosNuvem(Protocol):
    async def ultimos(self, dispositivo: str, n: int) -> list[tuple[str, str]]: ...

    async def gravar(self, dispositivo: str, usuario: str, resposta: str,
                     ferramentas: Sequence[str]) -> None: ...

    async def id_de(self, dispositivo: str) -> int | None: ...


class TurnosPg:
    """``nuvem_turnos`` no ``ayanami-pg`` (dispositivo pelo ``nome``)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def _ultimos(self, dispositivo: str, n: int) -> list[tuple[str, str]]:
        with self.db.connection() as conn:
            linhas = conn.execute(
                "SELECT t.texto_usuario, t.texto_resposta FROM nuvem_turnos t "
                "JOIN dispositivos d ON d.id = t.dispositivo WHERE d.nome = %s "
                "ORDER BY t.ts DESC LIMIT %s", (dispositivo, n)).fetchall()
        return [(r[0], r[1]) for r in reversed(linhas)]

    async def ultimos(self, dispositivo: str, n: int) -> list[tuple[str, str]]:
        return await asyncio.to_thread(self._ultimos, dispositivo, n)

    def _gravar(self, dispositivo: str, usuario: str, resposta: str, ferramentas: Sequence[str]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO nuvem_turnos (dispositivo, texto_usuario, texto_resposta, ferramentas) "
                "VALUES ((SELECT id FROM dispositivos WHERE nome = %s), %s, %s, %s)",
                (dispositivo, usuario, resposta, list(ferramentas)))

    async def gravar(self, dispositivo: str, usuario: str, resposta: str,
                     ferramentas: Sequence[str]) -> None:
        await asyncio.to_thread(self._gravar, dispositivo, usuario, resposta, ferramentas)

    def _id_de(self, dispositivo: str) -> int | None:
        with self.db.connection() as conn:
            r = conn.execute("SELECT id FROM dispositivos WHERE nome = %s", (dispositivo,)).fetchone()
        return int(r[0]) if r else None

    async def id_de(self, dispositivo: str) -> int | None:
        return await asyncio.to_thread(self._id_de, dispositivo)


#: ``(ferramentas, persona, histórico) -> Agent`` (``answer(text, ctx) -> ActionResult``).
FabricaAgente = Callable[[Sequence[Any], str, Sequence[ChatMessage]], Any]


def _persona_padrao() -> str:
    from magi.agent.prompt import load_persona

    return load_persona()


@dataclass
class NuvemDeps:
    """O que :func:`atender` usa. ``registry``: provedores (``chat(AGENT)``) já com o budget."""

    hub: Any
    budget: Any
    turnos: TurnosNuvem
    tarefas: PortaTarefas
    noticias: Callable[[str, int], Any]
    registry: Any = None
    confirmacoes: Any = None
    contexto_turnos: int = 20
    frases: Mapping[str, str] = field(default_factory=carregar_frases)
    fabrica_agente: FabricaAgente | None = None
    persona: Callable[[], str] = _persona_padrao
    relogio: Any = None
    intents: Path = INTENTS_PATH
    tv: TvActionsNuvem | None = None
    _specs: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.tv is None:
            self.tv = TvActionsNuvem(self.hub, fala_offline=self.frases["casa_offline"])
        if self.fabrica_agente is None:
            self.fabrica_agente = self._graph_agent
        if self.confirmacoes is not None and TIPO_CONFIRMA not in self.confirmacoes.executores:
            self.confirmacoes.ao_confirmar(TIPO_CONFIRMA, self._executar_confirmada)

    @classmethod
    def de_deps(cls, deps: Any, hub: Any, *, confirmacoes: Any = None, app: Any = None,
                **kw: Any) -> NuvemDeps:
        """A partir do :class:`ayanami.deps.Deps` (db/cfg/relogio/registry/budget)."""
        n = getattr(getattr(deps.cfg, "nuvem", None), "contexto_turnos", 20)
        return cls(hub=hub, budget=deps.budget, turnos=TurnosPg(deps.db),
                   tarefas=PortaTarefas.de_db(deps.db, app=app, relogio=deps.relogio),
                   noticias=noticias_do_db(deps.db, deps.relogio), registry=deps.registry,
                   confirmacoes=confirmacoes, contexto_turnos=n, relogio=deps.relogio, **kw)

    def _graph_agent(self, tools: Sequence[Any], persona: str, historico: Sequence[ChatMessage]) -> Any:
        from magi.agent.graph import GraphAgent

        agente = GraphAgent(self.registry, tools, persona=persona)
        agente.seed_history(historico)
        return agente

    def roteador(self) -> LocalRouter:
        if self._specs is None:
            self._specs = load_intents(self.intents)
        assert self.tv is not None
        return LocalRouter(intents=self._specs, casa=self.tv.catalogo)

    def ctx(self, dispositivo: str) -> TurnContext:
        agora = self.relogio.agora() if self.relogio is not None else None
        if agora is None:
            from datetime import UTC, datetime

            agora = datetime.now(UTC)
        return TurnContext(satellite=dispositivo, source=WakeSource.PTT, started_at=agora)

    async def _executar_confirmada(self, c: Any) -> Any:
        d = c.pedido.get("pedido") or {}
        p = AcaoPedido(intent=str(d.get("intent", "")),
                       slots=tuple((str(k), str(v)) for k, v in d.get("slots") or ()),
                       texto=str(d.get("texto") or ""), confirmed=True, args=dict(d.get("args") or {}))
        req = request_de_pedido(p, self.ctx(str(c.pedido.get("dispositivo") or "celular")))
        assert self.tv is not None
        return await self.tv.run(req)


# --------------------------------------------------------------------------- turno


class _Registrada:
    """Embrulha uma ferramenta e anota o nome em ``usadas`` quando roda."""

    def __init__(self, tool: Any, usadas: list[str]) -> None:
        self._tool, self._usadas = tool, usadas
        self.serial = getattr(tool, "serial", True)
        self.danger = getattr(tool, "danger", False)

    @property
    def name(self) -> str:
        return str(self._tool.name)

    @property
    def spec(self) -> Any:
        return self._tool.spec

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        self._usadas.append(self.name)
        return await self._tool.run(args, ctx, text)


def ferramentas_da_nuvem(deps: NuvemDeps, dispositivo_id: int | None = None) -> list[Any]:
    """Todas as ferramentas montadas, **filtradas** por :data:`NUVEM_PODE` (na ordem dela)."""
    assert deps.tv is not None
    fd = NuvemFerramentasDeps(tarefas=deps.tarefas, noticias=deps.noticias, hub=deps.hub,
                              budget=deps.budget, origem=lambda: dispositivo_id)
    todas = {t.name: t for t in [*ferramentas(fd), *ferramentas_tv(deps.tv)]}
    return [todas[n] for n in NUVEM_PODE if n in todas]


def _frase(deps: NuvemDeps, chave: str, ok: bool = False) -> ActionResult:
    return ActionResult(ok=ok, speech=deps.frases[chave])


async def _sem_llm(texto: str, intent_id: str | None, deps: NuvemDeps, ctx: TurnContext,
                   usadas: list[str], disp_id: int | None) -> ActionResult:
    if intent_id == "news.whats_new":
        tool = next(t for t in ferramentas_da_nuvem(deps, disp_id) if t.name == "news_query")
        usadas.append(tool.name)
        return await tool.run({}, ctx, texto)
    return _frase(deps, "sem_verba")


async def _responder(texto: str, dispositivo: str, deps: NuvemDeps, ctx: TurnContext,
                     usadas: list[str], disp_id: int | None) -> ActionResult:
    rota = deps.roteador().route(texto, ctx)
    local = rota.intent if rota.kind is RouteKind.LOCAL else None
    if local is not None and local.id.startswith("tv."):
        usadas.append(str(local.id))
        assert deps.tv is not None
        return await deps.tv.run(ActionRequest(intent=local, ctx=ctx, text=texto))
    if local is not None and not cabe_na_nuvem(str(local.id)):
        return _frase(deps, "pc_offline_pedido")
    try:
        await deps.budget.ensure_allowed(ProviderTask.AGENT)
    except BudgetExceeded:
        return await _sem_llm(texto, str(local.id) if local else None, deps, ctx, usadas, disp_id)
    historico: list[ChatMessage] = []
    for usuario, resposta in await deps.turnos.ultimos(dispositivo, deps.contexto_turnos):
        historico += [ChatMessage("user", usuario), ChatMessage("assistant", resposta)]
    tools = [_Registrada(t, usadas) for t in ferramentas_da_nuvem(deps, disp_id)]
    persona = f"{deps.persona()}\n\n{LINHA_NUVEM}"
    assert deps.fabrica_agente is not None
    agente = deps.fabrica_agente(tools, persona, historico)
    return await agente.answer(texto, ctx)


async def _confirmar(res: ActionResult, dispositivo: str, deps: NuvemDeps, disp_id: int | None) -> None:
    if deps.confirmacoes is None or res.on_confirm is None:
        return
    p = pedido_de_request(res.on_confirm)
    await deps.confirmacoes.criar(
        descricao=res.speech, origem=disp_id, perguntar=False,
        pedido={"tipo": TIPO_CONFIRMA, "dispositivo": dispositivo,
                "pedido": {"intent": p.intent, "slots": [list(s) for s in p.slots], "texto": p.texto,
                           "args": dict(p.args)}})


async def atender(texto: str, dispositivo: str, deps: NuvemDeps, *, turno: str | None = None) -> TurnoFim:
    """Um turno de texto no modo nuvem → ``TurnoFim`` (nunca levanta)."""
    turno = turno or novo_id()
    ctx = deps.ctx(dispositivo)
    usadas: list[str] = []
    erro: str | None = None
    disp_id: int | None = None
    try:
        disp_id = await deps.turnos.id_de(dispositivo)
        res = await _responder(texto, dispositivo, deps, ctx, usadas, disp_id)
        if res.needs_confirmation:
            await _confirmar(res, dispositivo, deps, disp_id)
    except Exception:  # noqa: BLE001 - o turno sempre fecha
        log.exception("nuvem: turno falhou")
        res, erro = _frase(deps, "erro_generico"), "interno"
    resposta = (res.full_text or res.speech or "")[:TEXTO_MAX]
    try:
        await deps.turnos.gravar(dispositivo, texto, resposta, usadas)
    except Exception:  # noqa: BLE001 - falha do banco não derruba a resposta
        log.exception("nuvem: nuvem_turnos não gravado")
    return TurnoFim(
        turno=turno, ok=res.ok and erro is None, texto=resposta, fala=res.speech,
        cards=tuple(card_de_cardmsg(c) for c in res.cards),
        expressao=res.expression.value if res.expression is not None else None, erro=erro)


__all__ = ["NUVEM_PODE", "LINHA_NUVEM", "NuvemDeps", "TurnosPg", "atender", "carregar_frases",
           "ferramentas_da_nuvem"]
