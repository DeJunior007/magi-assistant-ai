"""Tarefas do agente (Y3.4; spec §5.3, CA-Y19 parte agente). Agente, registry e orçamento falsos."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import procrastinate
import psycopg
import pytest
from procrastinate import testing

from ayanami import fila
from ayanami import tarefas as tf
from ayanami.config import de_dict
from ayanami.deps import Deps
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers import agente
from magi.common.contracts import (
    ActionResult,
    BudgetExceeded,
    CardLevel,
    CardMsg,
    ChatReply,
    PersonalDataRefused,
    ProviderTask,
    SearchResult,
    SearchSource,
    ToolSpec,
)

CFG = de_dict({"geral": {"url_base": "https://ayanami.example"}})


# --------------------------------------------------------------------------- falsos


class Guardado:
    def __init__(self, free_tier: bool, resposta: str = "") -> None:
        self.free_tier = free_tier
        self.resposta = resposta
        self.chamadas: list[tuple[str, bool]] = []

    async def chat(self, messages, *, personal: bool, **kw: Any) -> ChatReply:
        self.chamadas.append((messages[-1].content, personal))
        return ChatReply(text=self.resposta)

    async def search(self, query: str, *, personal: bool) -> SearchResult:
        self.chamadas.append((query, personal))
        return SearchResult(answer="R$ 199", sources=(SearchSource("loja", "https://loja.example/x"),))


class RegistryFalso:
    def __init__(self, *, chat_free: bool = False, busca_free: bool = False, juizo: str = "") -> None:
        self.agente = Guardado(chat_free)
        self.barato = Guardado(chat_free, juizo)
        self.busca = Guardado(busca_free)
        self.pedidos: list[str] = []

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> Guardado:
        self.pedidos.append(f"chat:{task}")
        return self.agente if task == ProviderTask.AGENT else self.barato

    def search(self) -> Guardado:
        self.pedidos.append("search")
        return self.busca


class OrcamentoFalso:
    def __init__(self, estourado: bool = False) -> None:
        self.estourado = estourado
        self.vistos: list[ProviderTask] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        self.vistos.append(task)
        if self.estourado:
            raise BudgetExceeded("teto")


class FerramentaFalsa:
    spec = ToolSpec(name="search", description="busca", parameters={"type": "object"})
    danger = False

    def __init__(self) -> None:
        self.vezes = 0

    @property
    def name(self) -> str:
        return "search"

    async def run(self, args, ctx, text: str = "") -> ActionResult:
        self.vezes += 1
        url = f"https://fonte{self.vezes}.example/"
        return ActionResult(ok=True, speech="achei", cards=(CardMsg(CardLevel.NORMAL, "f", url),))


class AgenteFalso:
    def __init__(self, registry, ferramentas, max_steps, *, passos: int = 2, texto: str = "Resposta.",
                 trava: bool = False) -> None:
        self.registry = registry
        self.ferramentas = ferramentas
        self.max_steps = max_steps
        self.passos = passos
        self.texto = texto
        self.trava = trava
        self.pedidos: list[str] = []

    async def answer(self, text: str, ctx) -> ActionResult:
        self.pedidos.append(text)
        self.registry.chat(ProviderTask.AGENT)
        if self.trava:
            await asyncio.Event().wait()
        for _ in range(self.passos):
            r = await self.ferramentas[0].run({"question": "preço do X"}, ctx)
            if not r.ok:
                break
        return ActionResult(ok=True, speech="curto", full_text=self.texto)


def _fabrica(**kw: Any):
    criados: list[AgenteFalso] = []

    def fabrica(registry, ferramentas, max_steps):
        a = AgenteFalso(registry, ferramentas, max_steps, **kw)
        criados.append(a)
        return a

    return fabrica, criados


# --------------------------------------------------------------------------- unidades sem banco


def test_registry_pessoal_recusa_free_tier_e_forca_personal():
    reg = agente.RegistryTarefa(RegistryFalso(chat_free=True), pessoal=True)
    with pytest.raises(PersonalDataRefused):
        reg.chat()
    livre = agente.RegistryTarefa(RegistryFalso(chat_free=True), pessoal=False)
    assert livre.chat().free_tier is True

    inner = RegistryFalso()
    reg = agente.RegistryTarefa(inner, pessoal=True)
    asyncio.run(reg.search().search("q", personal=False))
    assert inner.busca.chamadas == [("q", True)]
    assert reg.search_fallback() is None


def test_juizo_aceita_cerca_de_codigo_e_recusa_sem_bool():
    assert agente._juizo('```json\n{"bateu": true, "valor": "R$ 10"}\n```') == (True, "R$ 10")
    with pytest.raises(ValueError):
        agente._juizo('{"bateu": "sim"}')
    with pytest.raises(ValueError):
        agente._juizo("não sei")


# --------------------------------------------------------------------------- com banco


class DbConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


@pytest.fixture
def db(pg_nova_base) -> DbConexao:
    dsn = pg_nova_base("ayanami_agente")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbConexao(dsn)


@pytest.fixture
def rel() -> RelogioFalso:
    return RelogioFalso()


@pytest.fixture
def app_fila() -> procrastinate.App:
    return fila.montar(None, testing.InMemoryConnector(), periodicas=False)


def _deps(db, rel, registry, **extras: Any) -> Deps:
    return Deps(db=db, cfg=CFG, relogio=rel, registry=registry,
                budget=extras.pop("budget", None) or OrcamentoFalso(), extras=extras)


async def _rodar(app: procrastinate.App, deps: Deps) -> None:
    await app.run_worker_async(queues=["rapida"], wait=False, listen_notify=False,
                               worker_middleware=[tf.on_job_status(deps)],
                               additional_context={"deps": deps})


def _eventos(db) -> list[tuple]:
    with db.connection() as conn:
        return conn.execute("SELECT tipo, titulo, resumo, ref FROM eventos ORDER BY id").fetchall()


def _linha(db, tid) -> tuple:
    with db.connection() as conn:
        return conn.execute("SELECT estado, agenda, frase, progresso FROM tarefas WHERE id = %s",
                            (str(tid),)).fetchone()


class Contexto:
    def __init__(self, app=None) -> None:
        self.app = app


@pytest.mark.pg
async def test_ca_y19_pesquisa_pessoal_sem_free_tier_resultado_e_evento(db, rel, app_fila):
    reg = RegistryFalso()
    fab, criados = _fabrica(texto="x" * 7000)
    ferr = FerramentaFalsa()
    orc = OrcamentoFalso()
    deps = _deps(db, rel, reg, agente=fab, ferramentas=[ferr], budget=orc)
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("pesquisa", "Preço do X", {"pedido": "preço do X"},
                                                 pessoal=True), None, app=app_fila, relogio=rel)
    await _rodar(app_fila, deps)
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "ok"
    assert len(fim.resultado["texto"]) == agente.MAX_TEXTO
    assert fim.resultado["dados"]["fontes"] == ["https://fonte1.example/", "https://fonte2.example/"]
    assert ProviderTask.AGENT in orc.vistos
    a = criados[0]
    assert a.max_steps == agente.MAX_PASSOS and "preço do X" in a.pedidos[0]
    assert isinstance(a.registry, agente.RegistryTarefa) and a.registry.pessoal
    assert reg.pedidos[0] == f"chat:{ProviderTask.AGENT}"
    ev = _eventos(db)
    assert len(ev) == 1 and ev[0][0] == "tarefa_pronta" and ev[0][1] == "Pesquisa pronta"
    assert len(ev[0][2]) <= 200 and ev[0][3] == f"tarefa:{t.id}"


@pytest.mark.pg
async def test_pesquisa_pessoal_com_free_tier_falha_sem_chamar_o_agente(db, rel, app_fila):
    fab, criados = _fabrica()
    deps = _deps(db, rel, RegistryFalso(chat_free=True), agente=fab, ferramentas=[FerramentaFalsa()])
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("pesquisa", "P", {"pedido": "p"}, pessoal=True),
                                 None, app=app_fila, relogio=rel)
    for _ in range(3):
        for j in app_fila.connector.jobs.values():
            j["scheduled_at"] = None
        await _rodar(app_fila, deps)
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "falhou" and "PersonalDataRefused" in fim.erro
    assert criados == []


@pytest.mark.pg
async def test_pesquisa_grava_progresso_e_para_em_12_passos(db, rel, app_fila):
    fab, _ = _fabrica(passos=20)
    ferr = FerramentaFalsa()
    deps = _deps(db, rel, RegistryFalso(), agente=fab, ferramentas=[ferr])
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("pesquisa", "P", {"pedido": "p"}, avisar=False),
                                 None, app=app_fila, relogio=rel)
    with db.connection() as conn:
        conn.execute("UPDATE tarefas SET estado = 'rodando' WHERE id = %s", (str(t.id),))
    r = await agente.pesquisar(deps, Contexto(), tarefa_id=str(t.id))
    assert ferr.vezes == agente.MAX_PASSOS
    assert len(r["dados"]["fontes"]) == agente.MAX_PASSOS
    estado, _, frase, progresso = _linha(db, t.id)
    assert estado == "ok" and progresso == 100 and frase.startswith("Passo 12:")
    assert _eventos(db) == []  # avisar=False


@pytest.mark.pg
async def test_prazo_estourado_falha_com_erro_prazo_sem_retry(db, rel):
    app = procrastinate.App(connector=testing.InMemoryConnector())
    curto = dataclasses.replace(fila.POR_NOME["agente.pesquisar"], prazo_s=0.02)
    fila.registrar(app, curto)
    fab, _ = _fabrica(trava=True)
    deps = _deps(db, rel, RegistryFalso(), agente=fab, ferramentas=[FerramentaFalsa()])
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("pesquisa", "P", {"pedido": "p"}), None,
                                 app=app, relogio=rel)
    await _rodar(app, deps)
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "falhou" and fim.erro == "prazo"
    assert app.connector.jobs[t.job_id]["status"] == "failed"
    assert [e[0] for e in _eventos(db)] == ["tarefa_falhou"]


@pytest.mark.pg
async def test_lembrete_cria_evento_uma_vez(db, rel, app_fila):
    deps = _deps(db, rel, RegistryFalso())
    quando = (rel.agora() + timedelta(minutes=5)).isoformat()
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("lembrete", "Remédio", {"texto": "tomar remédio",
                                                                          "quando": quando}),
                                 None, app=app_fila, relogio=rel)
    with db.connection() as conn:
        conn.execute("UPDATE tarefas SET estado = 'rodando' WHERE id = %s", (str(t.id),))
    await agente.lembrete(deps, Contexto(), tarefa_id=str(t.id))
    await agente.lembrete(deps, Contexto(), tarefa_id=str(t.id))  # retry não duplica
    assert _eventos(db) == [("lembrete", "tomar remédio", "", f"tarefa:{t.id}")]


async def _monitor(db, app, rel, **params: Any) -> tf.TarefaOut:
    p = {"o_que": "preço do X", "condicao": "abaixo de R$ 200", **params}
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("monitor", "Preço do X", p), None, app=app, relogio=rel)
    return t


@pytest.mark.pg
async def test_monitor_bate_evento_monitor_e_ok(db, rel, app_fila):
    reg = RegistryFalso(juizo='{"bateu": true, "valor": "R$ 199"}')
    deps = _deps(db, rel, reg)
    t = await _monitor(db, app_fila, rel)
    await _rodar(app_fila, deps)
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "ok" and fim.resultado["dados"]["valor"] == "R$ 199"
    ev = _eventos(db)
    assert len(ev) == 1 and ev[0][0] == "monitor" and "R$ 199" in ev[0][2]
    assert reg.busca.chamadas and reg.barato.chamadas  # uma consulta + o juízo barato
    assert f"chat:{ProviderTask.NEWS}" in reg.pedidos


@pytest.mark.pg
async def test_monitor_nao_bate_agenda_mais_a_cada_h(db, rel, app_fila):
    deps = _deps(db, rel, RegistryFalso(juizo='{"bateu": false, "valor": "R$ 250"}'))
    t = await _monitor(db, app_fila, rel, a_cada_h=3)
    _, agenda0, _, _ = _linha(db, t.id)
    with db.connection() as conn:
        conn.execute("UPDATE tarefas SET estado = 'rodando' WHERE id = %s", (str(t.id),))
    r = await agente.monitor_passo(deps, Contexto(), tarefa_id=str(t.id))
    assert r["segue"] is True
    estado, agenda, frase, _ = _linha(db, t.id)
    assert estado == "na_fila" and agenda == agenda0 + timedelta(hours=3)
    assert "R$ 250" in frase and _eventos(db) == []
    # antes da hora: passo repetido não consulta nada
    reg2 = RegistryFalso(juizo='{"bateu": true}')
    r = await agente.monitor_passo(_deps(db, rel, reg2), Contexto(), tarefa_id=str(t.id))
    assert r["segue"] is True and reg2.pedidos == []


@pytest.mark.pg
async def test_monitor_teto_estourado_adia(db, rel, app_fila):
    reg = RegistryFalso(juizo='{"bateu": true}')
    deps = _deps(db, rel, reg, budget=OrcamentoFalso(estourado=True))
    t = await _monitor(db, app_fila, rel)
    r = await agente.monitor_passo(deps, Contexto(), tarefa_id=str(t.id))
    assert r["segue"] is True and reg.busca.chamadas == []
    assert _linha(db, t.id)[0] == "na_fila"


@pytest.mark.pg
async def test_monitor_expirado_ok_sem_bater(db, rel, app_fila):
    deps = _deps(db, rel, RegistryFalso(juizo='{"bateu": true}'))
    t = await _monitor(db, app_fila, rel, expira_dias=1)
    rel.avancar(2 * 86400)
    await _rodar(app_fila, deps)
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "ok" and fim.resultado["texto"] == agente.EXPIROU
    assert _eventos(db) == []


@pytest.mark.pg
async def test_varrer_defere_so_os_vencidos_com_lock(db, rel, app_fila):
    deps = _deps(db, rel, RegistryFalso(), fila=app_fila)
    vencido = await _monitor(db, app_fila, rel)
    rel.avancar(60)
    futuro = await _monitor(db, app_fila, rel, o_que="outro")
    with db.connection() as conn:
        conn.execute("UPDATE tarefas SET agenda = %s WHERE id = %s",
                     (rel.agora() + timedelta(hours=1), str(futuro.id)))
    antes = set(app_fila.connector.jobs)
    r = await agente.monitores_varrer(deps, Contexto(), timestamp=0)
    novos = [app_fila.connector.jobs[i] for i in set(app_fila.connector.jobs) - antes]
    assert r["dados"]["deferidos"] == 1 and len(novos) == 1
    j = novos[0]
    assert j["task_name"] == "monitor.passo" and j["args"] == {"tarefa_id": str(vencido.id)}
    assert j["lock"] == f"monitor:{vencido.id}" and j["priority"] == fila.PRIORIDADE_MONITOR
    # 2ª varredura com o passo ainda na fila: queueing_lock barra a duplicata
    r = await agente.monitores_varrer(deps, Contexto(), timestamp=0)
    assert r["dados"]["deferidos"] == 0
