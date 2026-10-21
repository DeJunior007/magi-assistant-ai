"""Tarefas do agente (dono: Y3.4; spec §5.3, §4.2, R2.3, R3.5, R9) — corpos chamados por ``ayanami.fila``.

- ``agente.pesquisar`` (:func:`pesquisar`): monta o ``GraphAgent`` (persona da Condessa, a padrão do
  ``persona.md``) com a busca web, ≤ :data:`MAX_PASSOS` passos de ferramenta; o prazo de 30 min é o
  ``asyncio.timeout`` de :func:`ayanami.fila.registrar` (estouro → ``falhou`` com ``erro="prazo"``,
  sem retry). ``deps.budget.ensure_allowed`` antes de começar. ``pessoal=True`` (R3.5): o registry
  passa por :class:`RegistryTarefa`, que manda ``personal=True`` em toda chamada e recusa provedor
  ``free_tier`` (``PersonalDataRefused``; a busca cai na reserva paga, se houver). Cada passo grava
  ``progresso``/``frase``. Saída ``{"texto": ≤ 6000, "dados": {"fontes": [url…]}}``, gravada como
  ``ok`` junto com o ``evento tarefa_pronta`` (se ``avisar``) numa transação só.
- ``agente.lembrete`` (:func:`lembrete`): ``evento lembrete`` com o texto (uma vez por tarefa,
  mesmo com retry).
- ``monitor.passo`` (:func:`monitor_passo`): uma consulta (busca) e um juízo do LLM barato
  (``ProviderTask.NEWS``) sobre ``condicao`` → ``{"bateu", "valor"}``. Bateu → ``ok`` + ``evento
  monitor``; não bateu → volta a ``na_fila`` com ``agenda += a_cada_h`` e devolve ``{"segue": True,
  …}``; passou ``expira`` → ``ok`` com ``"expirou sem bater"``. Teto do orçamento → adia como "não
  bateu".
- ``monitores.varrer`` (:func:`monitores_varrer`): defere ``monitor.passo`` (``lock`` e
  ``queueing_lock`` = ``monitor:<id>``) dos monitores ``na_fila`` com ``agenda`` vencida.

Injeção (testes): ``deps.registry`` (provedores; obrigatório), ``deps.extras["agente"]`` (fábrica
``(registry, ferramentas, max_steps) -> objeto com answer(texto, ctx)``; padrão ``GraphAgent``),
``deps.extras["ferramentas"]`` (padrão ``search_tools(registry)``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from procrastinate import JobContext
from procrastinate import exceptions as pexc
from psycopg.types.json import Jsonb

from ayanami import eventos, fila
from ayanami.db import Db, transacao
from ayanami.deps import Deps
from ayanami.tarefas import VIVOS, redigir
from magi.common.contracts import (
    ActionResult,
    BudgetExceeded,
    ChatMessage,
    PersonalDataRefused,
    ProviderTask,
    TurnContext,
    WakeSource,
)
from magi.elo.mensagens import EventoTipo

MAX_PASSOS = 12
MAX_TEXTO = 6000
MAX_RESUMO = eventos.MAX_RESUMO
MAX_FONTES = 20
MAX_VARRER = 200
EXPIROU = "expirou sem bater"
TITULO_PRONTA = "Pesquisa pronta"

INSTRUCAO_PESQUISA = (
    "Tarefa em segundo plano (resposta por escrito, não falada): {pedido}\n\n"
    "Pesquise na internet o que precisar e responda em texto corrido, em português, com no máximo "
    "6000 caracteres, citando as fontes no fim."
)
SISTEMA_JUIZ = (
    "Você julga se uma condição foi atendida a partir de um resultado de busca. Responda só JSON: "
    '{"bateu": true|false, "valor": "<valor observado, curto>"}.'
)
CONSULTA_MONITOR = "Qual é o valor atual de: {o_que}? Responda curto, com o número ou estado e a fonte."


# --------------------------------------------------------------------------- banco


@dataclass(frozen=True, slots=True)
class Linha:
    id: str
    tipo: str
    titulo: str
    estado: str
    params: Mapping[str, Any]
    pessoal: bool
    avisar: bool
    agenda: datetime | None
    expira: datetime | None


def _ler(db: Db, tid: str) -> Linha | None:
    with db.connection() as conn:
        r = conn.execute(
            "SELECT id, tipo, titulo, estado, params, pessoal, avisar, agenda, expira"
            " FROM tarefas WHERE id = %s",
            (tid,),
        ).fetchone()
        if not conn.autocommit:
            conn.rollback()
    if r is None:
        return None
    return Linha(str(r[0]), r[1], r[2], r[3], dict(r[4] or {}), bool(r[5]), bool(r[6]), r[7], r[8])


def _ler_ou_falha(db: Db, tid: str) -> Linha:
    t = _ler(db, tid)
    if t is None:
        raise LookupError(f"tarefa {tid} não existe")
    return t


def _progresso(db: Db, tid: str, progresso: int, frase: str, agora: datetime) -> None:
    with transacao(db) as conn:
        conn.execute(
            "UPDATE tarefas SET progresso = %s, frase = %s, atualizada = %s"
            " WHERE id = %s AND estado = ANY(%s)",
            (max(0, min(100, progresso)), frase[:200], agora, tid, list(VIVOS)),
        )


def _concluir(db: Db, tid: str, resultado: Mapping[str, Any], agora: datetime,
              evento: tuple[EventoTipo, str, str] | None) -> bool:
    """``ok`` + resultado e, na mesma transação, o evento; ``False`` se a tarefa já não estava viva."""
    with transacao(db) as conn:
        r = conn.execute(
            "UPDATE tarefas SET estado = 'ok', resultado = %s, erro = NULL, progresso = 100,"
            " atualizada = %s WHERE id = %s AND estado = ANY(%s) RETURNING id",
            (Jsonb(dict(resultado)), agora, tid, list(VIVOS)),
        ).fetchone()
        if r is None:
            return False
        if evento is not None:
            tipo, titulo, resumo = evento
            eventos.gravar(conn, tipo, titulo, resumo, f"tarefa:{tid}", agora=agora)
    return True


def _adiar(db: Db, tid: str, agenda: datetime, frase: str, agora: datetime) -> None:
    with transacao(db) as conn:
        conn.execute(
            "UPDATE tarefas SET estado = 'na_fila', agenda = %s, frase = %s, atualizada = %s"
            " WHERE id = %s AND estado = ANY(%s)",
            (agenda, frase[:200], agora, tid, list(VIVOS)),
        )


# --------------------------------------------------------------------------- R3.5: pessoal


class _ChatPessoal:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.free_tier = False

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._inner, nome)

    async def chat(self, messages: Sequence[ChatMessage], *, personal: bool = True, **kw: Any) -> Any:
        return await self._inner.chat(messages, personal=True, **kw)

    async def chat_stream(self, messages: Sequence[ChatMessage], *, personal: bool = True,
                          **kw: Any) -> Any:
        return await self._inner.chat_stream(messages, personal=True, **kw)


class _BuscaPessoal:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.free_tier = False

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._inner, nome)

    async def search(self, query: str, *, personal: bool = True) -> Any:
        return await self._inner.search(query, personal=True)


class RegistryTarefa:
    """Registry visto por uma tarefa: com ``pessoal``, só provedor sem ``free_tier`` e sempre
    ``personal=True`` (R3.5). Sem ``pessoal``, repassa tudo como está."""

    def __init__(self, inner: Any, *, pessoal: bool) -> None:
        self._inner = inner
        self.pessoal = pessoal

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._inner, nome)

    def _guardar(self, g: Any, o_que: str, envolver: Callable[[Any], Any]) -> Any:
        if not self.pessoal or g is None:
            return g
        if getattr(g, "free_tier", False):
            raise PersonalDataRefused(f"{o_que}: tarefa pessoal não usa provedor free_tier")
        return envolver(g)

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> Any:
        return self._guardar(self._inner.chat(task), f"chat {task}", _ChatPessoal)

    def search(self) -> Any:
        return self._guardar(self._inner.search(), "search", _BuscaPessoal)

    def search_fallback(self) -> Any:
        get = getattr(self._inner, "search_fallback", None)
        if not callable(get):
            return None
        return self._guardar(get(), "search_fallback", _BuscaPessoal)


# --------------------------------------------------------------------------- agente.pesquisar


class _Passos:
    """Conta os passos de ferramenta, grava progresso/frase e junta as fontes."""

    def __init__(self, deps: Deps, tid: str, maximo: int = MAX_PASSOS) -> None:
        self.deps = deps
        self.tid = tid
        self.maximo = maximo
        self.n = 0
        self.fontes: list[str] = []

    async def passo(self, frase: str) -> bool:
        self.n += 1
        if self.n > self.maximo:
            return False
        pct = min(95, self.n * 100 // (self.maximo + 1))
        await asyncio.to_thread(_progresso, self.deps.db, self.tid, pct,
                                f"Passo {self.n}: {frase}", self.deps.relogio.agora())
        return True

    def juntar(self, r: ActionResult) -> None:
        for c in r.cards:
            url = getattr(c, "url", "")
            if url and url not in self.fontes and len(self.fontes) < MAX_FONTES:
                self.fontes.append(url)


class _FerramentaContada:
    """Ferramenta do agente que conta passo antes de rodar (≤ ``MAX_PASSOS``)."""

    def __init__(self, inner: Any, passos: _Passos) -> None:
        self._inner = inner
        self._passos = passos
        self.spec = inner.spec
        self.danger = inner.danger

    @property
    def name(self) -> str:
        return self._inner.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        alvo = str(args.get("question") or args.get("query") or self.name)[:80]
        if not await self._passos.passo(f"{self.name} “{alvo}”"):
            return ActionResult(ok=False, speech="Limite de passos: responda com o que já tem.")
        r = await self._inner.run(args, ctx, text)
        self._passos.juntar(r)
        return r


def _ferramentas(deps: Deps, registry: Any) -> list[Any]:
    if "ferramentas" in deps.extras:
        return list(deps.extras["ferramentas"])
    from magi.agent.tools.search import search_tools

    return list(search_tools(registry))


def _agente(deps: Deps, registry: Any, ferramentas: Sequence[Any]) -> Any:
    fabrica = deps.extras.get("agente")
    if fabrica is not None:
        return fabrica(registry, ferramentas, MAX_PASSOS)
    from magi.agent.graph import GraphAgent

    return GraphAgent(registry, ferramentas, max_steps=MAX_PASSOS)


def _registry(deps: Deps, pessoal: bool) -> RegistryTarefa:
    if deps.registry is None:
        raise RuntimeError("worker sem registry de provedores (deps.registry)")
    return RegistryTarefa(deps.registry, pessoal=pessoal)


def _resumo(texto: str) -> str:
    linha = " ".join(texto.split())
    return linha if len(linha) <= MAX_RESUMO else linha[: MAX_RESUMO - 1].rstrip() + "…"


async def pesquisar(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``agente.pesquisar``: pesquisa/resumo com o ``GraphAgent`` (§5.3; dono: Y3.4)."""
    t = await asyncio.to_thread(_ler_ou_falha, deps.db, tarefa_id)
    if t.estado not in VIVOS:
        return None
    assert deps.budget is not None
    await deps.budget.ensure_allowed(ProviderTask.AGENT)
    reg = _registry(deps, t.pessoal)
    reg.chat(ProviderTask.AGENT)  # pessoal + free_tier → PersonalDataRefused antes de gastar
    passos = _Passos(deps, tarefa_id)
    ferramentas = [_FerramentaContada(f, passos) for f in _ferramentas(deps, reg)]
    agente = _agente(deps, reg, ferramentas)
    await asyncio.to_thread(_progresso, deps.db, tarefa_id, 0, "Começando a pesquisa",
                            deps.relogio.agora())
    pedido = str(t.params.get("pedido") or t.titulo)
    ctx = TurnContext(satellite="ayanami", source=WakeSource.PTT, started_at=deps.relogio.agora())
    r: ActionResult = await agente.answer(INSTRUCAO_PESQUISA.format(pedido=pedido), ctx)
    passos.juntar(r)
    texto = (r.full_text or r.speech or "").strip()
    if not r.ok or not texto:
        raise RuntimeError(redigir(f"agente sem resposta: {texto or 'vazio'}"))
    resultado = {"texto": texto[:MAX_TEXTO], "dados": {"fontes": list(passos.fontes)}}
    evento = (EventoTipo.TAREFA_PRONTA, TITULO_PRONTA, _resumo(texto)) if t.avisar else None
    await asyncio.to_thread(_concluir, deps.db, tarefa_id, resultado, deps.relogio.agora(), evento)
    return resultado


# --------------------------------------------------------------------------- agente.lembrete


def _lembrar(db: Db, t: Linha, texto: str, agora: datetime) -> None:
    with transacao(db) as conn:
        ja = conn.execute("SELECT 1 FROM eventos WHERE tipo = %s AND ref = %s",
                          (EventoTipo.LEMBRETE.value, f"tarefa:{t.id}")).fetchone()
        if ja is None:
            eventos.gravar(conn, EventoTipo.LEMBRETE, texto or t.titulo, "", f"tarefa:{t.id}",
                           agora=agora)


async def lembrete(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``agente.lembrete``: cria o ``evento lembrete`` na ``agenda`` (uma vez por tarefa; dono: Y3.4)."""
    t = await asyncio.to_thread(_ler_ou_falha, deps.db, tarefa_id)
    if t.estado not in VIVOS:
        return None
    texto = str(t.params.get("texto") or t.titulo).strip()
    await asyncio.to_thread(_lembrar, deps.db, t, texto, deps.relogio.agora())
    return {"texto": texto, "dados": {}}


# --------------------------------------------------------------------------- monitores


def _juizo(texto: str) -> tuple[bool, str]:
    bruto = texto.strip()
    if bruto.startswith("```"):
        bruto = bruto.strip("`").removeprefix("json").strip()
    ini, fim = bruto.find("{"), bruto.rfind("}")
    if ini < 0 or fim < ini:
        raise ValueError(f"juízo sem JSON: {texto[:80]!r}")
    d = json.loads(bruto[ini: fim + 1])
    bateu = d.get("bateu")
    if not isinstance(bateu, bool):
        raise ValueError("juízo sem 'bateu' booleano")
    return bateu, str(d.get("valor") or "")[:200]


async def _consultar(reg: RegistryTarefa, o_que: str) -> str:
    busca = reg.search()
    if busca is None:
        raise RuntimeError("monitor sem provedor de busca")
    res = await busca.search(CONSULTA_MONITOR.format(o_que=o_que), personal=reg.pessoal)
    fontes = " ".join(s.url for s in getattr(res, "sources", ())[:3])
    return f"{res.answer}\n{fontes}".strip()


async def _julgar(reg: RegistryTarefa, o_que: str, condicao: str, consulta: str) -> tuple[bool, str]:
    msgs = [
        ChatMessage(role="system", content=SISTEMA_JUIZ),
        ChatMessage(role="user", content=f"Monitor: {o_que}\nCondição: {condicao}\n"
                                         f"Resultado da busca:\n{consulta[:4000]}"),
    ]
    r = await reg.chat(ProviderTask.NEWS).chat(msgs, json_mode=True, personal=reg.pessoal)
    return _juizo(r.text)


def _proxima(agenda: datetime | None, agora: datetime, a_cada_h: int) -> datetime:
    passo = timedelta(hours=a_cada_h)
    nova = (agenda or agora) + passo
    return nova if nova > agora else agora + passo


async def monitor_passo(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``monitor.passo``: um passo do monitor (§5.3; dono: Y3.4).

    Devolve ``{"segue": True, …}`` quando o monitor continua (a tarefa volta a ``na_fila``)."""
    t = await asyncio.to_thread(_ler_ou_falha, deps.db, tarefa_id)
    if t.estado not in VIVOS:
        return None
    agora = deps.relogio.agora()
    a_cada_h = int(t.params.get("a_cada_h") or 2)
    if t.expira is not None and agora >= t.expira:
        resultado = {"texto": EXPIROU, "dados": {}}
        await asyncio.to_thread(_concluir, deps.db, tarefa_id, resultado, agora, None)
        return resultado
    if t.agenda is not None and t.agenda > agora:  # passo repetido antes da hora: nada a fazer
        await asyncio.to_thread(_adiar, deps.db, tarefa_id, t.agenda, "Aguardando a próxima checagem",
                                agora)
        return {"texto": "", "dados": {}, "segue": True}
    o_que = str(t.params.get("o_que") or t.titulo)
    condicao = str(t.params.get("condicao") or "")
    reg = _registry(deps, t.pessoal)
    try:
        assert deps.budget is not None
        await deps.budget.ensure_allowed(ProviderTask.SEARCH)
        consulta = await _consultar(reg, o_que)
        bateu, valor = await _julgar(reg, o_que, condicao, consulta)
    except BudgetExceeded:
        bateu, valor = False, ""
        frase = "Sem orçamento agora; tento de novo depois"
    else:
        frase = f"Último valor: {valor}" if valor else "Ainda não bateu"
    agora = deps.relogio.agora()
    if bateu:
        resultado = {"texto": f"{o_que}: {valor}" if valor else o_que,
                     "dados": {"valor": valor, "condicao": condicao}}
        evento = (EventoTipo.MONITOR, t.titulo, _resumo(f"{o_que}: {valor}" if valor else o_que))
        await asyncio.to_thread(_concluir, deps.db, tarefa_id, resultado, agora, evento)
        return resultado
    agenda = _proxima(t.agenda, agora, a_cada_h)
    await asyncio.to_thread(_adiar, deps.db, tarefa_id, agenda, frase, agora)
    return {"texto": frase, "dados": {"valor": valor, "agenda": agenda.isoformat()}, "segue": True}


def _vencidos(db: Db, agora: datetime) -> list[str]:
    with db.connection() as conn:
        linhas = conn.execute(
            "SELECT id FROM tarefas WHERE tipo = 'monitor' AND estado = 'na_fila'"
            " AND agenda IS NOT NULL AND agenda <= %s ORDER BY agenda LIMIT %s",
            (agora, MAX_VARRER),
        ).fetchall()
        if not conn.autocommit:
            conn.rollback()
    return [str(r[0]) for r in linhas]


def _gravar_job(db: Db, tid: str, job_id: int) -> None:
    with transacao(db) as conn:
        conn.execute("UPDATE tarefas SET job_id = %s WHERE id = %s", (job_id, tid))


async def monitores_varrer(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``monitores.varrer``: defere ``monitor.passo`` dos vencidos (``lock="monitor:<id>"``; dono: Y3.4)."""
    ids = await asyncio.to_thread(_vencidos, deps.db, deps.relogio.agora())
    app = deps.extras.get("fila") or contexto.app
    deferidos = 0
    for tid in ids:
        opcoes = fila.defer_opcoes("monitor.passo", lock_id=tid, queueing_lock=f"monitor:{tid}")
        try:
            job_id = await app.configure_task("monitor.passo", **opcoes).defer_async(tarefa_id=tid)
        except pexc.AlreadyEnqueued:
            continue
        await asyncio.to_thread(_gravar_job, deps.db, tid, job_id)
        deferidos += 1
    return {"texto": f"{deferidos} monitor(es) deferido(s)", "dados": {"deferidos": deferidos}}

