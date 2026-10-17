"""Modo nuvem: a Condessa atendendo na Ayanami com o PC desligado (dono: Y6.3; spec §6.4, §6.5;
design §7.3, §7.4; R8.2, R8.3, D11a, D14a).

:func:`atender` (chamado pela rota do turno, Y6.4):

1. Roteador local **sem LLM** (o ``LocalRouter`` do PC, rapidfuzz, mesmas frases do
   ``intents.yaml``, catálogo da casa do último ``ola``): ``tv.*`` com nota de execução vai direto à
   casa (``tv.power_off`` → ``confirma`` no PWA); intenção só do PC (jogo, HUD, RGB, música, volume
   do PC, sistema, Learning, audiolivro, memória) com nota de execução → frase ``pc_offline_pedido``
   (nota de "quis dizer" vai ao agente, que tem a linha da nuvem e decide).
2. Teto batido (``BudgetNuvem.ensure_allowed(AGENT)``) → frase ``sem_verba``, sem LLM.
3. Senão o agente (``GraphAgent`` por padrão) com a persona da Condessa + a linha da nuvem + os
   últimos ``contexto_turnos`` de ``nuvem_turnos`` do dispositivo, e **só** as ferramentas de
   :data:`NUVEM_PODE`. ``tv_desligar`` pendente de confirmação → ``confirma`` no PWA.
4. Grava a troca em ``nuvem_turnos`` (texto, sem áudio; ``ferramentas`` = nomes usados).

Frases fixas em ``ayanami/frases.yaml`` (cacheadas em voz pelo ``voz.cache_frases``).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

import yaml

from ayanami.nuvem_tools import ServicosNuvem, TvActionsNuvem, ferramentas
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    BudgetExceeded,
    Intent,
    ProviderTask,
    RouteKind,
    TurnContext,
    WakeSource,
)
from magi.elo.mensagens import TurnoFim

log = logging.getLogger("ayanami.nuvem")

NUVEM_PODE: Final = ("news_query", "tarefa_criar", "tarefa_listar", "tarefa_cancelar",
                     "lembrete_criar", "monitor_criar", "estado", "tv_ligar", "tv_desligar",
                     "tv_volume", "tv_mudo", "tv_app", "tv_entrada")

LINHA_NUVEM: Final = ("Agora você está na nuvem, sem a memória do PC; diga isso quando fizer "
                      "diferença. Aqui você só tem as ferramentas listadas: pedido de jogo, HUD, RGB, "
                      "Spotify, volume do PC, abrir coisas no PC ou Learning Mode responde que isso "
                      "só no PC, e ele está desligado.")

CAMINHO_FRASES: Final = Path(__file__).resolve().parent / "frases.yaml"
FRASES_OBRIGATORIAS: Final = ("casa_offline", "pc_offline_pedido", "sem_verba", "erro_generico", "pc_caiu")

#: Intenções do ``intents.yaml`` que só existem no PC (spec §6.5 "Não pode").
SO_PC_PREFIXOS: Final = ("game.", "hud.", "volume.", "rgb.", "system.", "music.", "learning.",
                         "book.", "memory.")
SATELITE: Final = "celular"
TEXTO_MAX: Final = 16000


@functools.lru_cache(maxsize=4)
def carregar_frases(caminho: Path = CAMINHO_FRASES) -> Mapping[str, str]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho}: esperava mapa nome→texto")
    faltam = [k for k in FRASES_OBRIGATORIAS if not str(dados.get(k) or "").strip()]
    if faltam:
        raise ValueError(f"{caminho}: faltam frases {faltam}")
    return {str(k): str(v) for k, v in dados.items()}


@functools.lru_cache(maxsize=1)
def _intents() -> tuple[Any, ...]:
    from magi.core.router import load_intents

    return tuple(load_intents())


# --------------------------------------------------------------------------- dependências


class Agente(Protocol):
    async def answer(self, text: str, ctx: TurnContext) -> ActionResult: ...


#: ``(persona, ferramentas, historico) -> Agente``; ``historico`` = ``[(usuario, resposta)]`` em
#: ordem cronológica.
FazerAgente = Callable[[str, Sequence[Any], Sequence[tuple[str, str]]], Agente]


class RepoTurnos(Protocol):
    async def recentes(self, dispositivo: int | None, n: int) -> list[tuple[str, str]]: ...

    async def gravar(self, dispositivo: int | None, usuario: str, resposta: str,
                     ferramentas: Sequence[str]) -> None: ...


@dataclass
class PgTurnos:
    """``nuvem_turnos`` no ``ayanami-pg`` (``Db`` síncrono, acessos em ``to_thread``)."""

    db: Any
    relogio: Any

    def _recentes(self, disp: int | None, n: int) -> list[tuple[str, str]]:
        with self.db.connection() as conn:
            rs = conn.execute(
                "SELECT texto_usuario, texto_resposta FROM nuvem_turnos"
                " WHERE dispositivo IS NOT DISTINCT FROM %s ORDER BY ts DESC, uid LIMIT %s",
                (disp, n),
            ).fetchall()
        return [(r[0], r[1]) for r in reversed(rs)]

    async def recentes(self, dispositivo: int | None, n: int) -> list[tuple[str, str]]:
        return await asyncio.to_thread(self._recentes, dispositivo, n) if n > 0 else []

    def _gravar(self, disp: int | None, u: str, r: str, f: list[str]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO nuvem_turnos (ts, dispositivo, texto_usuario, texto_resposta, ferramentas)"
                " VALUES (%s, %s, %s, %s, %s)",
                (self.relogio.agora(), disp, u, r, f),
            )

    async def gravar(self, dispositivo: int | None, usuario: str, resposta: str,
                     ferramentas: Sequence[str]) -> None:
        await asyncio.to_thread(self._gravar, dispositivo, usuario, resposta, list(ferramentas))


def agente_padrao(registry: Any) -> FazerAgente:
    """``GraphAgent`` do PC com o histórico da nuvem na persona (o deque do agente guarda só 2)."""

    def fazer(persona: str, tools: Sequence[Any], historico: Sequence[tuple[str, str]]) -> Agente:
        from magi.agent.graph import GraphAgent

        texto = persona
        if historico:
            linhas = "\n".join(f"Pedro: {u}\nVocê: {r}" for u, r in historico)
            texto = f"{persona}\n\n## Conversa recente (nuvem)\n{linhas}"
        return GraphAgent(registry, tools, persona=texto)

    return fazer


@dataclass
class NuvemDeps:
    """Tudo que :func:`atender` usa (os testes passam falsos)."""

    relogio: Any
    budget: Any  # BudgetNuvem (ensure_allowed)
    turnos: RepoTurnos
    #: ``dispositivo -> TvActionsNuvem`` (``None`` = sem casa: as ``tv_*`` nem existem)
    tv: Callable[[int | None], TvActionsNuvem | None]
    #: ``dispositivo -> ServicosNuvem`` (tarefas, estado, notícias)
    servicos: Callable[[int | None], ServicosNuvem | Awaitable[ServicosNuvem]]
    fazer_agente: FazerAgente
    persona: str | None = None  # None = ``persona.md`` do PC
    frases: Mapping[str, str] = field(default_factory=carregar_frases)
    contexto_turnos: int = 20
    intents: Sequence[Any] | None = None  # specs do roteador (None = intents.yaml)

    @classmethod
    def da_app(cls, ctx: Any, *, registry: Any = None, budget: Any = None, app_fila: Any = None,
               noticias: Any = None, **kw: Any) -> NuvemDeps:
        """Montagem de produção: ``ctx`` = contexto da API (``db``, ``relogio``, ``cfg``, ``extras``)."""
        from ayanami.custos import BudgetNuvem

        frases = kw.pop("frases", None) or carregar_frases()
        budget = budget or BudgetNuvem.de_config(ctx.db, ctx.cfg, ctx.relogio)

        def tv(disp: int | None) -> TvActionsNuvem:
            return TvActionsNuvem.do_ctx(ctx, disp, frases)

        def servicos(disp: int | None) -> ServicosNuvem:
            return ServicosNuvem.do_db(ctx.db, ctx.relogio, disp, app=app_fila,
                                       estado=estado_de(ctx, budget), noticias=noticias)

        return cls(relogio=ctx.relogio, budget=budget, turnos=PgTurnos(ctx.db, ctx.relogio), tv=tv,
                   servicos=servicos, fazer_agente=agente_padrao(registry), frases=frases,
                   contexto_turnos=ctx.cfg.nuvem.contexto_turnos, **kw)


def estado_de(ctx: Any, budget: Any) -> Callable[[], Awaitable[Mapping[str, Any]]]:
    async def estado() -> Mapping[str, Any]:
        from ayanami.hub import hub_de

        hub = hub_de(ctx)
        casa = hub.estado_casa()
        g = await budget.gasto()
        return {
            "pc_online": hub.online("pc"),
            "casa_online": casa.online,
            "tvs": [{"nome": e.nome, "ligada": e.ligada, "app": e.app} for e in casa.estados],
            "gasto_nuvem_usd": str(g.nuvem_usd),
            "teto_nuvem_usd": str(g.teto_efetivo_usd),
        }

    return estado


# --------------------------------------------------------------------------- turno


def _disp_id(dispositivo: str | int | None) -> int | None:
    if isinstance(dispositivo, int):
        return dispositivo
    s = str(dispositivo or "").strip()
    return int(s) if s.isdigit() else None


def _ctx(relogio: Any) -> TurnContext:
    return TurnContext(satellite=SATELITE, source=WakeSource.PTT, started_at=relogio.agora())


async def _bloqueado(budget: Any) -> bool:
    if budget is None:
        return False
    try:
        await budget.ensure_allowed(ProviderTask.AGENT)
    except BudgetExceeded:
        return True
    return False


class _Registra:
    """Embrulha uma ferramenta: guarda o nome usado no turno."""

    def __init__(self, tool: Any, usadas: list[str]) -> None:
        self._t, self._usadas = tool, usadas
        self.danger = getattr(tool, "danger", False)
        self.serial = getattr(tool, "serial", True)

    @property
    def spec(self) -> Any:
        return self._t.spec

    @property
    def name(self) -> str:
        return self._t.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        self._usadas.append(self._t.name)
        return await self._t.run(args, ctx, text)


def _fim(turno: str, r: ActionResult, *, erro: str | None = None) -> TurnoFim:
    fala = r.speech or ""
    texto = (r.full_text or fala)[:TEXTO_MAX]
    exp = r.expression.value if r.expression is not None else None
    return TurnoFim(turno=turno, ok=r.ok and erro is None, texto=texto, fala=fala, expressao=exp, erro=erro)


async def atender(texto: str, dispositivo: str, deps: NuvemDeps, *, turno: str | None = None) -> TurnoFim:
    """Um turno no modo nuvem (spec §6.5). Nunca levanta: erro vira ``erro_generico``."""
    turno = turno or uuid.uuid4().hex
    disp = _disp_id(dispositivo)
    usadas: list[str] = []
    try:
        r, erro = await _atender(texto, disp, deps, usadas)
    except Exception as e:  # noqa: BLE001 - o turno sempre fecha
        log.exception("nuvem_turno_falhou (%s)", type(e).__name__)
        r, erro = ActionResult(ok=False, speech=deps.frases["erro_generico"]), "erro"
    fim = _fim(turno, r, erro=erro)
    try:
        await deps.turnos.gravar(disp, texto, fim.texto or fim.fala, usadas)
    except Exception as e:  # noqa: BLE001 - gravar não derruba a resposta
        log.warning("nuvem_turnos_gravar_falhou (%s)", type(e).__name__)
    return fim


async def _atender(texto: str, disp: int | None, deps: NuvemDeps,
                   usadas: list[str]) -> tuple[ActionResult, str | None]:
    from magi.core.router import LocalRouter

    frases = deps.frases
    tv = deps.tv(disp)
    ctx = _ctx(deps.relogio)
    roteador = LocalRouter(intents=list(deps.intents if deps.intents is not None else _intents()),
                           casa=tv.catalogo if tv is not None else None)
    rota = roteador.route(texto, ctx)
    intent = rota.intent if rota.kind is RouteKind.LOCAL else None  # "quis dizer" vai ao agente
    if intent is not None and intent.id.startswith(SO_PC_PREFIXOS):
        return ActionResult(ok=False, speech=frases["pc_offline_pedido"]), None
    if intent is not None and intent.id.startswith("tv."):
        if tv is None:
            return ActionResult(ok=False, speech=frases["casa_offline"]), None
        usadas.append(f"intent:{intent.id}")
        return await _tv_direto(tv, intent, texto, ctx), None
    if await _bloqueado(deps.budget):
        return ActionResult(ok=False, speech=frases["sem_verba"]), "sem_verba"

    serv = deps.servicos(disp)
    if inspect.isawaitable(serv):
        serv = await serv
    tools = [_Registra(t, usadas) for t in ferramentas(serv, tv, frozenset(NUVEM_PODE))]
    historico = await deps.turnos.recentes(disp, deps.contexto_turnos)
    if deps.persona is not None:
        persona = deps.persona
    else:
        from magi.agent.prompt import load_persona

        persona = load_persona()
    agente = deps.fazer_agente(f"{persona.strip()}\n\n{LINHA_NUVEM}", tools, historico)
    r = await agente.answer(texto, ctx)
    if r.needs_confirmation and r.on_confirm is not None:
        if tv is not None and tv.handles(r.on_confirm.intent.id):
            return await tv.confirmar(r.on_confirm, r.speech), None
        return ActionResult(ok=False, speech=frases["erro_generico"]), "confirmacao"
    return r, None


async def _tv_direto(tv: TvActionsNuvem, intent: Intent, texto: str, ctx: TurnContext) -> ActionResult:
    req = ActionRequest(intent=intent, ctx=ctx, text=texto)
    if intent.danger:
        from magi.core.actions.tv import SAY_TV_CONFIRM_OFF, SAY_TV_CONFIRM_OFF_PLAIN

        tv_slot = next((s for s in intent.slots if s.name == "tv"), None)
        nome = tv_slot.display or tv_slot.value if tv_slot is not None else ""
        desc = SAY_TV_CONFIRM_OFF.format(nome=nome) if nome else SAY_TV_CONFIRM_OFF_PLAIN
        return await tv.confirmar(req, desc)
    return await tv.run(req)
