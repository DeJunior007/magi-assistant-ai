"""Y3.1: tarefas — CA-Y14 (idempotência por chave), CA-Y15 (cancelar na fila / rodando, erro
redigido), validação do ``TarefaIn`` e o ``worker_middleware`` de estado. Fila em
``InMemoryConnector``; a tabela ``tarefas`` no ``ayanami-pg-teste`` (``pg``)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
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

CFG = de_dict({"geral": {"url_base": "https://ayanami.exemplo.ts.net"}})


# --------------------------------------------------------------------------- sem banco


def test_redigir_tira_segredos():
    msg = "falhou com sk-abc123 e token ayn_pc_x; Authorization: Bearer xyz.789 fim"
    r = tf.redigir(msg)
    assert "sk-abc" not in r and "ayn_pc_x" not in r and "xyz.789" not in r
    assert r == "falhou com sk-… e token ayn_…; Authorization: Bearer … fim"


@pytest.mark.parametrize(("t", "campo"), [
    (tf.TarefaIn("pesquisa", "", {"pedido": "x"}), "titulo"),
    (tf.TarefaIn("pesquisa", "x" * 121, {"pedido": "x"}), "titulo"),
    (tf.TarefaIn("pesquisa", "t", {}), "params.pedido"),
    (tf.TarefaIn("pesquisa", "t", {"pedido": "x" * 2001}), "params.pedido"),
    (tf.TarefaIn("lembrete", "t", {"texto": "x", "quando": "amanhã"}), "params.quando"),
    (tf.TarefaIn("lembrete", "t", {"texto": "x", "quando": "2026-01-02T10:00:00"}), "params.quando"),
    (tf.TarefaIn("monitor", "t", {"o_que": "a", "condicao": "b", "a_cada_h": 7}), "params.a_cada_h"),
    (tf.TarefaIn("monitor", "t", {"o_que": "a", "condicao": "b", "expira_dias": 91}), "params.expira_dias"),
    (tf.TarefaIn("pesquisa", "t", {"pedido": "x"}, chave="k" * 129), "chave"),
    (tf.TarefaIn("outro", "t", {}), "tipo"),  # type: ignore[arg-type]
])
def test_validar_recusa(t, campo):
    with pytest.raises(tf.TarefaInvalida) as e:
        tf.validar(t)
    assert e.value.campo == campo


def test_validar_normaliza_e_chave_padrao():
    p = tf.validar(tf.TarefaIn("monitor", "t", {"o_que": "a", "condicao": "b", "lixo": 1}))
    assert p == {"o_que": "a", "condicao": "b", "a_cada_h": 2, "expira_dias": 30}
    assert tf.chave_padrao("pesquisa", {"a": 1, "b": 2}) == tf.chave_padrao("pesquisa", {"b": 2, "a": 1})
    assert tf.chave_padrao("pesquisa", {"a": 1}) != tf.chave_padrao("resumo", {"a": 1})


def test_mapa_de_estados():
    assert tf.ESTADO_DO_JOB == {"todo": "na_fila", "doing": "rodando", "succeeded": "ok",
                                "failed": "falhou", "cancelled": "cancelada", "aborted": "cancelada"}


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
    dsn = pg_nova_base("ayanami_tarefas")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbConexao(dsn)


@pytest.fixture
def rel() -> RelogioFalso:
    return RelogioFalso()


class Corpos:
    """Corpos falsos por nome de tarefa (o resto da tabela fica com o corpo real/stub)."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, dict]] = []
        self.fns: dict[str, Any] = {}

    def app(self) -> procrastinate.App:
        app = procrastinate.App(connector=testing.InMemoryConnector())
        for d in fila.TAREFAS:
            fn = self.fns.get(d.nome)
            fila.registrar(app, d, self._embrulhar(d.nome, fn) if fn else None, periodica=False)
        return app

    def _embrulhar(self, nome: str, fn: Any) -> Any:
        async def corpo(deps, contexto, **kw):
            self.chamadas.append((nome, kw))
            return await fn(deps, contexto, **kw)

        return corpo


async def _rodar(app: procrastinate.App, deps: Deps, fila_: str = "rapida", **kw: Any) -> None:
    await app.run_worker_async(queues=[fila_], wait=False, listen_notify=False,
                               worker_middleware=[tf.on_job_status(deps)],
                               additional_context={"deps": deps}, **kw)


PEDIDO = tf.TarefaIn("pesquisa", "preço da placa", {"pedido": "quanto custa a RTX?"})


@pytest.mark.pg
async def test_ca_y14_mesma_chave_uma_tarefa_e_depois_de_ok_cria_outra(db, rel):
    corpos = Corpos()

    async def ok(deps, contexto, *, tarefa_id):
        return {"texto": "achei", "dados": {"usd": 1}}

    corpos.fns["agente.pesquisar"] = ok
    app = corpos.app()
    t1, c1 = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    t2, c2 = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    assert (c1, c2) == (True, False)
    assert t2.id == t1.id and t1.estado == "na_fila" and t1.job_id is not None
    assert len(app.connector.jobs) == 1
    job = app.connector.jobs[t1.job_id]
    assert job["queueing_lock"] == t1.chave and job["priority"] == 20

    await _rodar(app, Deps(db=db, cfg=CFG, relogio=rel))
    feita = tf.obter_tarefa(db, t1.id)
    assert feita.estado == "ok" and feita.resultado == {"texto": "achei", "dados": {"usd": 1}}
    assert corpos.chamadas == [("agente.pesquisar", {"tarefa_id": str(t1.id)})]

    t3, c3 = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    assert c3 is True and t3.id != t1.id and t3.chave == t1.chave


@pytest.mark.pg
async def test_chave_explicita_e_tarefa_rodando_segura_a_chave(db, rel):
    """DS3: com o 1º job em ``doing`` o ``queueing_lock`` não segura; o índice segura."""
    corpos = Corpos()
    app = corpos.app()
    t = tf.TarefaIn("resumo", "r", {"pedido": "x"}, chave="minha")
    t1, _ = await tf.criar_tarefa(db, t, None, app=app, relogio=rel)
    tf.marcar(db, t1.id, "rodando", rel.agora())
    app.connector.jobs[t1.job_id]["status"] = "doing"
    t2, c2 = await tf.criar_tarefa(db, t, None, app=app, relogio=rel)
    assert c2 is False and t2.id == t1.id and len(app.connector.jobs) == 1


@pytest.mark.pg
async def test_already_enqueued_devolve_a_existente(db, rel):
    app = Corpos().app()
    t1, _ = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    # a tarefa terminou por fora mas o job ainda está em todo com o mesmo queueing_lock
    tf.marcar(db, t1.id, "falhou", rel.agora())
    t2, c2 = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    assert c2 is False and t2.id == t1.id
    assert len(tf.listar_tarefas(db)) == 1


@pytest.mark.pg
async def test_lembrete_agendado_e_monitor_com_lock(db, rel):
    app = Corpos().app()
    lem, _ = await tf.criar_tarefa(db, tf.TarefaIn("lembrete", "remédio", {
        "texto": "tomar", "quando": "2026-01-02T10:00:00-03:00"}), None, app=app, relogio=rel)
    job = app.connector.jobs[lem.job_id]
    assert job["task_name"] == "agente.lembrete"
    assert job["scheduled_at"] == datetime(2026, 1, 2, 13, 0, tzinfo=UTC)
    monitor = tf.TarefaIn("monitor", "rtx", {"o_que": "preço", "condicao": "< 2000"})
    mon, _ = await tf.criar_tarefa(db, monitor, None, app=app, relogio=rel)
    job = app.connector.jobs[mon.job_id]
    assert (job["task_name"], job["lock"], job["priority"]) == ("monitor.passo", f"monitor:{mon.id}", 10)
    with db.connection() as conn:
        agenda, expira = conn.execute("SELECT agenda, expira FROM tarefas WHERE id = %s",
                                      (mon.id,)).fetchone()
    assert agenda == rel.agora() and (expira - agenda).days == 30


@pytest.mark.pg
async def test_ca_y15_cancelar_na_fila_nunca_roda(db, rel):
    corpos = Corpos()

    async def nunca(deps, contexto, *, tarefa_id):  # pragma: no cover
        raise AssertionError("não devia rodar")

    corpos.fns["agente.pesquisar"] = nunca
    app = corpos.app()
    t, _ = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    assert await tf.cancelar_tarefa(db, t.id, app=app, relogio=rel) == "cancelada"
    await _rodar(app, Deps(db=db, cfg=CFG, relogio=rel))
    assert corpos.chamadas == []
    assert tf.obter_tarefa(db, t.id).estado == "cancelada"
    assert (await app.job_manager.get_job_status_async(t.job_id)).value == "cancelled"
    with pytest.raises(tf.JaTerminou):
        await tf.cancelar_tarefa(db, t.id, app=app, relogio=rel)
    with pytest.raises(tf.TarefaNaoEncontrada):
        await tf.cancelar_tarefa(db, "00000000-0000-0000-0000-000000000000", app=app, relogio=rel)


@pytest.mark.pg
async def test_ca_y15_cancelar_rodando_sai_na_primeira_checagem(db, rel):
    corpos = Corpos()
    rodando = asyncio.Event()
    estado: dict[str, Any] = {"voltas": 0, "voltas_no_pedido": None, "saiu_por": None}

    async def laco(deps, contexto, *, tarefa_id):
        rodando.set()
        try:
            while True:
                estado["voltas"] += 1
                await asyncio.sleep(0.005)  # a "checagem": todo await é ponto de cancelamento
        except asyncio.CancelledError:
            estado["saiu_por"] = "cancelamento"
            raise

    corpos.fns["agente.pesquisar"] = laco
    app = corpos.app()
    t, _ = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    w = asyncio.create_task(_rodar(app, Deps(db=db, cfg=CFG, relogio=rel), abort_job_polling_interval=0.01))
    await asyncio.wait_for(rodando.wait(), 5)
    assert tf.obter_tarefa(db, t.id).estado == "rodando"
    assert await tf.cancelar_tarefa(db, t.id, app=app, relogio=rel) == "cancelando"
    await asyncio.wait_for(w, 5)
    assert estado["saiu_por"] == "cancelamento"
    assert tf.obter_tarefa(db, t.id).estado == "cancelada"
    # cancelado pelo usuário: aborted e sem retry, mesmo com a=2
    assert (await app.job_manager.get_job_status_async(t.job_id)).value == "aborted"
    assert app.connector.jobs[t.job_id]["attempts"] == 1


@pytest.mark.pg
async def test_ca_y15_erro_redigido_retry_e_falha_final_com_evento(db, rel):
    corpos = Corpos()

    async def explode(deps, contexto, *, tarefa_id):
        raise RuntimeError("chave sk-abc vazou junto com ayn_pc_x")

    corpos.fns["agente.pesquisar"] = explode
    app = corpos.app()
    deps = Deps(db=db, cfg=CFG, relogio=rel)
    t, _ = await tf.criar_tarefa(db, PEDIDO, None, app=app, relogio=rel)
    await _rodar(app, deps)
    # a=2: a 1ª falha volta para a fila com o erro já redigido
    t1 = tf.obter_tarefa(db, t.id)
    assert t1.estado == "na_fila"
    assert t1.erro == "RuntimeError: chave sk-… vazou junto com ayn_…"
    # RetryStrategy(max_attempts=2) da lib = até 2 repetições (3 execuções); o job foi reagendado
    # no futuro: traz para agora a cada volta
    for _ in range(2):
        assert tf.obter_tarefa(db, t.id).estado == "na_fila"
        app.connector.jobs[t.job_id]["scheduled_at"] = None
        await _rodar(app, deps)
    assert len(corpos.chamadas) == 3
    t2 = tf.obter_tarefa(db, t.id)
    assert t2.estado == "falhou" and "sk-abc" not in t2.erro and "ayn_pc_x" not in t2.erro
    with db.connection() as conn:
        eventos = conn.execute("SELECT tipo, titulo, ref FROM eventos").fetchall()
    assert eventos == [("tarefa_falhou", "preço da placa", f"tarefa:{t.id}")]


@pytest.mark.pg
async def test_prazo_estourado_falha_com_erro_prazo_sem_retry_e_sem_aviso(db, rel):
    app = procrastinate.App(connector=testing.InMemoryConnector())

    async def demora(deps, contexto, *, tarefa_id):
        await asyncio.sleep(1)

    d = fila.Def("teste.prazo", "rapida", 0, 3, 0)
    object.__setattr__(d, "prazo_s", 0.01)
    fila.registrar(app, d, demora)
    with db.connection() as conn:
        tid = conn.execute("INSERT INTO tarefas (tipo, titulo, avisar) VALUES ('pesquisa', 'p', false)"
                           " RETURNING id").fetchone()[0]
    jid = await app.configure_task("teste.prazo").defer_async(tarefa_id=str(tid))
    await _rodar(app, Deps(db=db, cfg=CFG, relogio=rel))
    t = tf.obter_tarefa(db, tid)
    assert (t.estado, t.erro) == ("falhou", "prazo")
    assert (await app.job_manager.get_job_status_async(jid)).value == "failed"
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM eventos").fetchone()[0] == 0


@pytest.mark.pg
async def test_job_sem_tarefa_passa_direto_pelo_middleware(db, rel):
    app = procrastinate.App(connector=testing.InMemoryConnector())

    async def nada(deps, contexto, *, timestamp):
        return None

    fila.registrar(app, fila.Def("teste.periodica", "agendada", 5, 1), nada)
    jid = await app.configure_task("teste.periodica").defer_async(timestamp=0)
    await _rodar(app, Deps(db=db, cfg=CFG, relogio=rel), "agendada")
    assert (await app.job_manager.get_job_status_async(jid)).value == "succeeded"
