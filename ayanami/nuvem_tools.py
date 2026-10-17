"""Ferramentas do agente no modo nuvem (dono: Y6.3; spec §6.5, §13.4; design §7.3; R8.2).

- Tarefas por :func:`ayanami.tarefas.criar_tarefa` (``tarefa_criar`` = pesquisa/resumo,
  ``lembrete_criar``, ``monitor_criar``), ``tarefa_listar``, ``tarefa_cancelar``.
- ``estado``: PC, casa, gasto da nuvem no mês e tarefas vivas (só leitura).
- ``news_query``: a mesma ``NewsQueryTool`` do PC sobre o ``PgNewsRepo`` do ``ayanami-pg``.
- ``tv_*``: as **mesmas** ferramentas de :mod:`magi.agent.tools.tv` (C2.2), ligadas a um
  :class:`TvActionsNuvem` que manda ``acao`` à casa pelo hub (:func:`ayanami.api.casa.pedir_acao`,
  origem ``"nuvem"``). ``tv_desligar`` (perigosa) vira ``confirma`` no PWA
  (:meth:`TvActionsNuvem.confirmar`). Casa fora do ar → frase ``casa_offline`` do ``frases.yaml``.

:func:`ferramentas` só devolve nomes de ``NUVEM_PODE`` (``ayanami.nuvem``); ``tv_estado`` fica de fora.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from magi.agent.tools.base import ToolArgsError, arg_int, arg_str
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    Expression,
    IntentId,
    ToolSpec,
    TurnContext,
)
from magi.core.router import CasaCatalogo
from magi.elo.converte import pedido_de_request
from magi.elo.mensagens import AcaoPedido

log = logging.getLogger("ayanami.nuvem_tools")

TV_INTENTS: frozenset[str] = frozenset({
    IntentId.TV_POWER_ON.value, IntentId.TV_POWER_OFF.value, IntentId.TV_VOLUME.value,
    IntentId.TV_MUTE.value, IntentId.TV_UNMUTE.value, IntentId.TV_APP.value, IntentId.TV_INPUT.value,
})

Pedir = Callable[[AcaoPedido], Awaitable[tuple[int, dict]]]
Confirmar = Callable[[AcaoPedido, str], Awaitable[str]]


# --------------------------------------------------------------------------- TV


class TvActionsNuvem:
    """``TvActions`` da nuvem (spec §13.4, último parágrafo): ``ActionHandler`` + ``ActionRegistry``
    das ferramentas ``tv_*``, com ``catalogo``/``estado()`` lidos do último ``ola`` da casa no hub.

    ``pedir(pedido) -> (status, corpo)`` e ``confirmar(pedido, descricao) -> id`` são injetáveis;
    :meth:`do_ctx` liga os dois à app (``casa.pedir_acao`` e ``Confirmacoes.criar``).
    """

    intents = TV_INTENTS

    def __init__(self, casa: Callable[[], Any], pedir: Pedir, confirmar: Confirmar,
                 frases: Mapping[str, str]) -> None:
        self._casa, self._pedir, self._confirmar, self.frases = casa, pedir, confirmar, frases
        self.pedidos: list[AcaoPedido] = []  # o que foi à casa neste turno (gravado em nuvem_turnos)

    @classmethod
    def do_ctx(cls, ctx: Any, dispositivo: int | None, frases: Mapping[str, str]) -> TvActionsNuvem:
        from ayanami.api import casa as api_casa

        hub, conf = api_casa.servicos(ctx)  # registra o executor "casa.acao" do "sim"

        async def pedir(p: AcaoPedido) -> tuple[int, dict]:
            return await api_casa.pedir_acao(ctx, None, None, p, "nuvem", dispositivo_id=dispositivo)

        async def confirmar(p: AcaoPedido, descricao: str) -> str:
            c = await conf.criar(
                descricao=descricao,
                pedido={"tipo": "casa.acao", "origem": "nuvem", "tv": None,
                        "pedido": api_casa.para_json(p)},
                origem=dispositivo,
            )
            return c.id

        return cls(hub.estado_casa, pedir, confirmar, frases)

    # -- catálogo / estado -------------------------------------------------

    @property
    def catalogo(self) -> CasaCatalogo:
        from magi.core.actions.tv import entradas_do_ola

        c = self._casa()
        return CasaCatalogo(tvs=tuple(c.tvs), apps=tuple(c.apps), entradas=entradas_do_ola(c.tvs))

    def online(self) -> bool:
        return bool(self._casa().online)

    async def estado(self) -> tuple[bool, tuple[Any, ...]]:
        c = self._casa()
        return bool(c.online), tuple(c.estados)

    # -- ActionRegistry ----------------------------------------------------

    def register(self, handler: Any) -> None:  # pragma: no cover - registro fixo
        raise TypeError("TvActionsNuvem só atende tv.*")

    def handles(self, intent_id: str) -> bool:
        return intent_id in TV_INTENTS

    def _offline(self) -> ActionResult:
        return ActionResult(ok=False, speech=self.frases["casa_offline"], expression=Expression.CONFUSED)

    @staticmethod
    def pedido(req: ActionRequest) -> AcaoPedido:
        args = {k: v for k, v in req.args.items() if isinstance(v, str | int | float | bool)}
        return pedido_de_request(dataclasses.replace(req, args=args))

    async def run(self, req: ActionRequest) -> ActionResult:
        if req.intent.id not in TV_INTENTS:
            return ActionResult(ok=False, speech=self.frases["erro_generico"])
        if not self.online():
            return self._offline()
        p = self.pedido(req)
        self.pedidos.append(p)
        try:
            status, corpo = await self._pedir(p)
        except Exception as e:  # noqa: BLE001 - a casa é opcional: nunca derruba o turno
            log.warning("nuvem_tv_falhou (%s)", type(e).__name__)
            return ActionResult(ok=False, speech=self.frases["erro_generico"], expression=Expression.CONFUSED)
        if status == 503:
            return self._offline()
        if status == 202:
            return ActionResult(ok=True, speech=str(corpo.get("msg") or ""))
        if status != 200:
            return ActionResult(ok=False, speech=str(corpo.get("msg") or self.frases["erro_generico"]),
                                expression=Expression.CONFUSED)
        ok = bool(corpo.get("ok"))
        return ActionResult(ok=ok, speech=str(corpo.get("fala") or ""),
                            expression=None if ok else Expression.CONFUSED)

    async def confirmar(self, req: ActionRequest, descricao: str) -> ActionResult:
        """Pedido perigoso (``tv_desligar``): cria a ``confirma`` que o PWA mostra (§6.5)."""
        if not self.online():
            return self._offline()
        p = dataclasses.replace(self.pedido(req), confirmed=False)
        self.pedidos.append(p)
        try:
            await self._confirmar(p, descricao)
        except Exception as e:  # noqa: BLE001
            log.warning("nuvem_confirma_falhou (%s)", type(e).__name__)
            return ActionResult(ok=False, speech=self.frases["erro_generico"], expression=Expression.CONFUSED)
        return ActionResult(ok=True, speech=descricao)


# --------------------------------------------------------------------------- tarefas, estado, notícias


@dataclass
class ServicosNuvem:
    """O que as ferramentas não-TV usam (injetável nos testes; :meth:`do_db` liga ao banco)."""

    criar: Callable[[Any], Awaitable[tuple[Any, bool]]]
    listar: Callable[[], Awaitable[Sequence[Any]]]
    cancelar: Callable[[str], Awaitable[str]]
    estado: Callable[[], Awaitable[Mapping[str, Any]]]
    noticias: Any = None  # NewsQuery (None = sem banco de notícias)

    @classmethod
    def do_db(cls, db: Any, relogio: Any, origem: int | None, *, app: Any = None,
              estado: Callable[[], Awaitable[Mapping[str, Any]]] | None = None,
              noticias: Any = None) -> ServicosNuvem:
        import asyncio

        from ayanami import tarefas

        async def criar(t: Any) -> tuple[Any, bool]:
            return await tarefas.criar_tarefa(db, t, origem, app=app, relogio=relogio)

        async def listar() -> Sequence[Any]:
            vivas = await asyncio.to_thread(tarefas.listar_tarefas, db, None, 10)
            return vivas

        async def cancelar(tid: str) -> str:
            return await tarefas.cancelar_tarefa(db, tid, app=app, relogio=relogio)

        async def sem_estado() -> Mapping[str, Any]:
            return {}

        return cls(criar, listar, cancelar, estado or sem_estado, noticias)


def _spec(nome: str, desc: str, props: Mapping[str, Any], req: Sequence[str] = ()) -> ToolSpec:
    params: dict[str, Any] = {"type": "object", "properties": dict(props)}
    if req:
        params["required"] = list(req)
    return ToolSpec(name=nome, description=desc, parameters=params)


class _Ferramenta:
    serial = False
    danger = False

    def __init__(self, spec: ToolSpec, fn: Callable[[Mapping[str, Any]], Awaitable[ActionResult]],
                 *, serial: bool = False) -> None:
        self.spec, self._fn, self.serial = spec, fn, serial

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        try:
            return await self._fn(args)
        except ToolArgsError as e:
            return ActionResult(ok=False, speech=str(e), expression=Expression.CONFUSED)


def _ok(fala: str, texto: str | None = None) -> ActionResult:
    return ActionResult(ok=True, speech=fala, full_text=texto or fala)


def _erro(fala: str) -> ActionResult:
    return ActionResult(ok=False, speech=fala, expression=Expression.CONFUSED)


def ferramentas_tarefas(s: ServicosNuvem) -> list[Any]:
    from ayanami.tarefas import JaTerminou, TarefaIn, TarefaInvalida, TarefaNaoEncontrada

    async def criar(tipo: str, titulo: str, params: dict[str, Any]) -> ActionResult:
        try:
            t, criada = await s.criar(TarefaIn(tipo=tipo, titulo=titulo[:120], params=params))  # type: ignore[arg-type]
        except TarefaInvalida as e:
            return _erro(f"Não deu para criar: {e}.")
        fala = "Anotado, vou cuidar disso." if criada else "Isso já está na fila."
        return _ok(fala, f"{fala} ({t.tipo} {t.id})")

    async def tarefa_criar(a: Mapping[str, Any]) -> ActionResult:
        pedido = arg_str(a, "pedido")
        if not pedido:
            raise ToolArgsError("Faltou o pedido.")
        tipo = "resumo" if arg_str(a, "tipo") == "resumo" else "pesquisa"
        return await criar(tipo, arg_str(a, "titulo") or pedido, {"pedido": pedido})

    async def lembrete_criar(a: Mapping[str, Any]) -> ActionResult:
        texto, quando = arg_str(a, "texto"), arg_str(a, "quando")
        if not texto or not quando:
            raise ToolArgsError("Faltou o texto ou a hora do lembrete.")
        return await criar("lembrete", texto, {"texto": texto, "quando": quando})

    async def monitor_criar(a: Mapping[str, Any]) -> ActionResult:
        o_que, condicao = arg_str(a, "o_que"), arg_str(a, "condicao")
        if not o_que or not condicao:
            raise ToolArgsError("Faltou o que vigiar ou a condição.")
        params: dict[str, Any] = {"o_que": o_que, "condicao": condicao}
        if (h := arg_int(a, "a_cada_h")) is not None:
            params["a_cada_h"] = h
        return await criar("monitor", o_que, params)

    async def tarefa_listar(_a: Mapping[str, Any]) -> ActionResult:
        itens = list(await s.listar())
        if not itens:
            return _ok("Nenhuma tarefa por aqui.")
        linhas = [f"{t.titulo}: {t.estado}" for t in itens]
        return _ok(f"{len(itens)} tarefa(s).", "; ".join(linhas))

    async def tarefa_cancelar(a: Mapping[str, Any]) -> ActionResult:
        tid = arg_str(a, "id")
        if not tid:
            raise ToolArgsError("Qual tarefa?")
        try:
            r = await s.cancelar(tid)
        except (TarefaNaoEncontrada, ValueError):
            return _erro("Não achei essa tarefa.")
        except JaTerminou:
            return _erro("Essa já terminou.")
        return _ok("Cancelada." if r == "cancelada" else "Cancelando.")

    txt = {"type": "string"}
    return [
        _Ferramenta(_spec("tarefa_criar", "Cria uma pesquisa ou resumo demorado em segundo plano.",
                          {"pedido": txt, "titulo": txt,
                           "tipo": {"type": "string", "enum": ["pesquisa", "resumo"]}},
                          ("pedido",)), tarefa_criar, serial=True),
        _Ferramenta(_spec("tarefa_listar", "Lista as tarefas recentes e o estado delas.", {}), tarefa_listar),
        _Ferramenta(_spec("tarefa_cancelar", "Cancela uma tarefa pelo id.", {"id": txt}, ("id",)),
                    tarefa_cancelar, serial=True),
        _Ferramenta(_spec("lembrete_criar", "Cria um lembrete; quando = ISO 8601 com fuso.",
                          {"texto": txt, "quando": txt}, ("texto", "quando")), lembrete_criar, serial=True),
        _Ferramenta(_spec("monitor_criar", "Vigia algo periodicamente e avisa quando a condição bater.",
                          {"o_que": txt, "condicao": txt, "a_cada_h": {"type": "integer"}},
                          ("o_que", "condicao")), monitor_criar, serial=True),
    ]


def ferramenta_estado(s: ServicosNuvem) -> Any:
    async def estado(_a: Mapping[str, Any]) -> ActionResult:
        e = dict(await s.estado())
        return ActionResult(ok=True, speech="", full_text=json.dumps(e, ensure_ascii=False, default=str))

    return _Ferramenta(_spec("estado", "Estado agora: PC, casa e TVs, gasto da nuvem no mês, tarefas vivas.",
                             {}), estado)


def ferramentas(s: ServicosNuvem, tv: TvActionsNuvem | None,
                pode: frozenset[str] | Sequence[str]) -> list[Any]:
    """Todas as ferramentas do modo nuvem cujo nome está em ``pode`` (``NUVEM_PODE``)."""
    out: list[Any] = [*ferramentas_tarefas(s), ferramenta_estado(s)]
    if s.noticias is not None:
        from magi.agent.tools.news import NewsQueryTool

        out.append(NewsQueryTool(s.noticias))
    if tv is not None:
        from magi.agent.tools.tv import tv_tools

        out += tv_tools(tv, tv)  # type: ignore[arg-type]  # TvActionsNuvem tem catalogo/estado/run
    permitidas = frozenset(pode)
    return [f for f in out if f.name in permitidas]

