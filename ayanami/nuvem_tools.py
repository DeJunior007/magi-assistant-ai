"""Ferramentas do agente no modo nuvem (dono: Y6.3; spec §6.5, §13.4 último parágrafo).

- ``tarefa_criar``/``tarefa_listar``/``tarefa_cancelar``, ``lembrete_criar``, ``monitor_criar``:
  por :func:`ayanami.tarefas.criar_tarefa` e companhia (as funções vêm por :class:`PortaTarefas`,
  trocadas por falsos nos testes).
- ``estado``: PC/casa online, gasto do mês e tarefas vivas.
- ``news_query``: novidades do ``ayanami-pg`` (``news_items``), sem pesquisar na internet.
- ``tv_*``: as **mesmas** ferramentas de :mod:`magi.agent.tools.tv` ligadas a
  :class:`TvActionsNuvem`, que manda ``acao`` à casa pelo hub (``de="ayanami"``,
  ``origem="nuvem"``) em vez do elo TCP local. Casa offline → frase ``casa_offline``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from ayanami import tarefas as _tarefas
from ayanami.hub import NoOffline
from magi.agent.tools.base import arg_str
from magi.agent.tools.tv import tv_tools
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    Expression,
    ToolSpec,
    TurnContext,
)
from magi.core.actions import Registry
from magi.core.actions.tv import SAY_CASA_OFF, TvActions, _Caiu, entradas_do_ola
from magi.core.router import CasaCatalogo
from magi.elo.mensagens import Acao, Envelope, EstadoTv

log = logging.getLogger(__name__)

NOTICIAS_MAX = 5
SAY_TAREFA_CRIADA = "Beleza, deixei na fila: {titulo}."
SAY_TAREFA_JA = "Essa já estava na fila: {titulo}."
SAY_SEM_TAREFAS = "Nenhuma tarefa por aqui."
SAY_CANCELADA = "Cancelei."
SAY_NAO_ACHEI_TAREFA = "Não achei essa tarefa."
SAY_SEM_NOTICIAS = "Nada de novo guardado por enquanto."
SAY_SEM_NOTICIAS_TEMA = "Não tenho nada guardado sobre {topic}."


# --------------------------------------------------------------------------- TV pela casa


class TvActionsNuvem(TvActions):
    """``TvActions`` cujo "elo" é o hub da Ayanami: catálogo do último ``ola`` da casa, ``acao``
    por ``hub.enviar_e_esperar``. Reaproveita ``_run``/``traduz``/``_confirma`` do PC inteiros."""

    def __init__(self, hub: Any, *, fala_offline: str = SAY_CASA_OFF, **kw: Any) -> None:
        super().__init__(host="ayanami", **kw)  # host ≠ localhost: nunca lê casa.toml local
        self.hub = hub
        self.fala_offline = fala_offline

    @property  # type: ignore[override]
    def catalogo(self) -> CasaCatalogo:
        c = self.hub.estado_casa()
        return CasaCatalogo(tvs=c.tvs, apps=c.apps, entradas=entradas_do_ola(c.tvs))

    @catalogo.setter
    def catalogo(self, _valor: CasaCatalogo) -> None:
        pass

    def _vivo(self) -> bool:
        return bool(self.hub.online("casa"))

    async def _conectar(self) -> bool:
        return self._vivo()

    async def _pedir(self, env: Envelope, timeout: float) -> Envelope | None:
        corpo = env.corpo
        if isinstance(corpo, Acao):
            corpo = dataclasses.replace(corpo, origem="nuvem")
        env = dataclasses.replace(env, de="ayanami", para="casa", corpo=corpo)
        try:
            return await self.hub.enviar_e_esperar(env, timeout)
        except NoOffline as e:
            raise _Caiu() from e
        except TimeoutError:
            return None

    async def run(self, req: ActionRequest) -> ActionResult:
        if not self._vivo():
            return ActionResult(ok=False, speech=self.fala_offline, expression=Expression.CONFUSED)
        res = await super().run(req)
        if not res.ok and res.speech == SAY_CASA_OFF:
            return dataclasses.replace(res, speech=self.fala_offline)
        return res

    async def estado(self) -> tuple[bool, tuple[EstadoTv, ...]]:
        c = self.hub.estado_casa()
        return bool(c.online), tuple(c.estados)

    async def aclose(self) -> None:
        return None


def registro_tv(tv: TvActionsNuvem) -> Registry:
    return Registry([tv])


# --------------------------------------------------------------------------- portas


@dataclass
class PortaTarefas:
    """Funções de :mod:`ayanami.tarefas` (``db``/``app``/``relogio`` já amarrados)."""

    criar: Callable[[_tarefas.TarefaIn, int | None], Awaitable[tuple[Any, bool]]]
    listar: Callable[[str | None, int], Awaitable[list[Any]]]
    cancelar: Callable[[str], Awaitable[str]]

    @classmethod
    def de_db(cls, db: Any, *, app: Any = None, relogio: Any = None) -> PortaTarefas:
        async def criar(t: _tarefas.TarefaIn, origem: int | None) -> tuple[Any, bool]:
            return await _tarefas.criar_tarefa(db, t, origem, app=app, relogio=relogio)

        async def listar(estado: str | None, n: int) -> list[Any]:
            return await asyncio.to_thread(_tarefas.listar_tarefas, db, estado, n)

        async def cancelar(tid: str) -> str:
            return await _tarefas.cancelar_tarefa(db, tid, app=app, relogio=relogio)

        return cls(criar, listar, cancelar)


def noticias_do_db(db: Any, relogio: Any) -> Callable[[str, int], Awaitable[list[dict[str, Any]]]]:
    """``(topic, days) -> [{"titulo", "resumo", "franquia"}]`` contra ``news_items`` (sem spoiler
    escondido: item com ``spoiler`` só sai se a franquia tem ``spoilers_ok``)."""

    def ler(topic: str, days: int) -> list[dict[str, Any]]:
        desde = relogio.agora() - timedelta(days=days)
        sql = ("SELECT i.title, coalesce(i.summary, ''), coalesce(i.franchise, '') FROM news_items i "
               "LEFT JOIN franchise_prefs p ON p.franchise = i.franchise "
               "WHERE i.first_seen >= %s AND coalesce(p.dropped, false) = false "
               "AND (i.spoiler IS NULL OR coalesce(p.spoilers_ok, false))")
        args: list[Any] = [desde]
        if topic:
            sql += " AND (i.franchise ILIKE %s OR i.title ILIKE %s)"
            args += [f"%{topic}%", f"%{topic}%"]
        sql += " ORDER BY i.priority DESC NULLS LAST, i.first_seen DESC LIMIT %s"
        args.append(NOTICIAS_MAX)
        with db.connection() as conn:
            linhas = conn.execute(sql, args).fetchall()
        return [{"titulo": r[0], "resumo": r[1], "franquia": r[2]} for r in linhas]

    async def consultar(topic: str, days: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(ler, topic, days)

    return consultar


# --------------------------------------------------------------------------- ferramentas


@dataclass
class Ferramenta:
    """``Tool`` simples: ``spec`` + corpo assíncrono ``(args, ctx) -> ActionResult``."""

    spec: ToolSpec
    corpo: Callable[[Mapping[str, Any], TurnContext], Awaitable[ActionResult]]
    serial: bool = False
    danger: bool = False

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        try:
            return await self.corpo(args, ctx)
        except _tarefas.TarefaInvalida as e:
            return ActionResult(ok=False, speech=f"Pedido inválido ({e}).", expression=Expression.CONFUSED)


def _obj(props: Mapping[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": dict(props), "required": list(required)}


_S = {"type": "string"}


@dataclass
class NuvemFerramentasDeps:
    tarefas: PortaTarefas
    noticias: Callable[[str, int], Awaitable[list[dict[str, Any]]]]
    hub: Any = None
    budget: Any = None
    origem: Callable[[], int | None] = field(default=lambda: None)


def ferramentas(d: NuvemFerramentasDeps) -> list[Ferramenta]:
    async def _criar(tipo: str, titulo: str, params: dict[str, Any]) -> ActionResult:
        t = _tarefas.TarefaIn(tipo=tipo, titulo=titulo[:120] or tipo, params=params)  # type: ignore[arg-type]
        out, criada = await d.tarefas.criar(t, d.origem())
        modelo = SAY_TAREFA_CRIADA if criada else SAY_TAREFA_JA
        return ActionResult(ok=True, speech=modelo.format(titulo=getattr(out, "titulo", titulo)))

    async def tarefa_criar(a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        tipo = arg_str(a, "tipo") or "pesquisa"
        pedido = arg_str(a, "pedido")
        return await _criar(tipo, arg_str(a, "titulo") or pedido, {"pedido": pedido})

    async def tarefa_listar(a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        lista = await d.tarefas.listar(arg_str(a, "estado") or None, 10)
        if not lista:
            return ActionResult(ok=True, speech=SAY_SEM_TAREFAS)
        linhas = [f"{t.titulo} ({t.estado}, id {t.id})" for t in lista]
        return ActionResult(ok=True, speech=f"{len(lista)} tarefa(s).", full_text="\n".join(linhas))

    async def tarefa_cancelar(a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        try:
            await d.tarefas.cancelar(arg_str(a, "id"))
        except (_tarefas.TarefaNaoEncontrada, ValueError):
            return ActionResult(ok=False, speech=SAY_NAO_ACHEI_TAREFA)
        except _tarefas.JaTerminou as e:
            return ActionResult(ok=False, speech=f"Essa já terminou ({e.estado}).")
        return ActionResult(ok=True, speech=SAY_CANCELADA)

    async def lembrete_criar(a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        texto = arg_str(a, "texto")
        return await _criar("lembrete", texto, {"texto": texto, "quando": arg_str(a, "quando")})

    async def monitor_criar(a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        o_que = arg_str(a, "o_que")
        params: dict[str, Any] = {"o_que": o_que, "condicao": arg_str(a, "condicao")}
        if a.get("a_cada_h") is not None:
            params["a_cada_h"] = a["a_cada_h"]
        return await _criar("monitor", o_que, params)

    async def estado(_a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        partes = []
        if d.hub is not None:
            partes.append("PC " + ("ligado" if d.hub.online("pc") else "desligado"))
            partes.append("casa " + ("no ar" if d.hub.online("casa") else "fora do ar"))
        if d.budget is not None:
            try:
                s = await d.budget.status()
                partes.append(f"nuvem US$ {s.spent_usd:.2f} de US$ {s.cap_usd:.2f} no mês")
            except Exception:  # noqa: BLE001
                log.exception("estado: gasto ilegível")
        vivas = await d.tarefas.listar("rodando", 50) + await d.tarefas.listar("na_fila", 50)
        partes.append(f"{len(vivas)} tarefa(s) em andamento")
        texto = "; ".join(partes) + "."
        return ActionResult(ok=True, speech=texto[:1].upper() + texto[1:])

    async def news_query(a: Mapping[str, Any], _c: TurnContext) -> ActionResult:
        topic = arg_str(a, "topic")
        try:
            days = max(1, min(365, int(a.get("days") or 30)))
        except (TypeError, ValueError):
            days = 30
        itens = await d.noticias(topic, days)
        if not itens:
            return ActionResult(ok=True, speech=SAY_SEM_NOTICIAS_TEMA.format(topic=topic) if topic
                                else SAY_SEM_NOTICIAS)
        texto = "\n".join(f"- {i['titulo']}: {i['resumo']}".rstrip(": ") for i in itens)
        return ActionResult(ok=True, speech=itens[0]["titulo"], full_text=texto)

    quando = {**_S, "description": "Data ISO 8601 com fuso (ex.: 2026-10-21T09:00:00-03:00)"}
    return [
        Ferramenta(ToolSpec("tarefa_criar", "Põe uma pesquisa ou resumo na fila da Ayanami.",
                            _obj({"tipo": {"type": "string", "enum": ["pesquisa", "resumo"]},
                                  "pedido": _S, "titulo": _S}, ("pedido",))), tarefa_criar, serial=True),
        Ferramenta(ToolSpec("tarefa_listar", "Lista as tarefas da fila (estado opcional).",
                            _obj({"estado": _S})), tarefa_listar),
        Ferramenta(ToolSpec("tarefa_cancelar", "Cancela uma tarefa pelo id.", _obj({"id": _S}, ("id",))),
                   tarefa_cancelar, serial=True),
        Ferramenta(ToolSpec("lembrete_criar", "Cria um lembrete (aviso no celular na hora marcada).",
                            _obj({"texto": _S, "quando": quando}, ("texto", "quando"))),
                   lembrete_criar, serial=True),
        Ferramenta(ToolSpec("monitor_criar", "Vigia algo de tempos em tempos e avisa quando a "
                            "condição bater.", _obj({"o_que": _S, "condicao": _S,
                                                     "a_cada_h": {"type": "integer"}},
                                                    ("o_que", "condicao"))), monitor_criar, serial=True),
        Ferramenta(ToolSpec("estado", "Estado geral: PC, casa, gasto do mês e tarefas.", _obj({})), estado),
        Ferramenta(ToolSpec("news_query", "Novidades guardadas de jogos e anime. topic: obra ou "
                            "franquia (vazio = geral); days: janela em dias (padrão 30).",
                            _obj({"topic": _S, "days": {"type": "integer"}})), news_query),
    ]


def ferramentas_tv(tv: TvActionsNuvem) -> list[Any]:
    """As ``tv_*`` do PC (C2.2) sobre o ``TvActionsNuvem`` (``tv_estado`` incluso; o filtro
    ``NUVEM_PODE`` fica em :mod:`ayanami.nuvem`)."""
    return tv_tools(registro_tv(tv), tv)
