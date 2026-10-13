"""Y3.1: registro da fila (CA-Y13), prazo, retry, worker/batimento, ``fila.reanimar`` e
``limpeza.diaria`` (prazos da §3 com relógio falso, ``pg``)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import procrastinate
import psycopg
import pytest
from procrastinate import testing
from procrastinate.schema import SchemaManager

from ayanami import fila, worker
from ayanami.config import de_dict
from ayanami.deps import Deps
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers import manutencao

CFG = de_dict({"geral": {"url_base": "https://ayanami.exemplo.ts.net"}})
CFG_EMB = de_dict({"geral": {"url_base": "https://ayanami.exemplo.ts.net"}, "embeddings": {"ligado": True}})

# a tabela da §4.2: nome → (fila, a, w, lock, cron)
TABELA = {
    "agente.pesquisar": ("rapida", 2, 30, None, None),
    "agente.lembrete": ("rapida", 3, 10, None, None),
    "monitor.passo": ("rapida", 2, 30, None, None),
    "push.enviar": ("rapida", 3, 5, None, None),
    "monitores.varrer": ("agendada", 1, None, "varrer", "*/15 * * * *"),
    "noticias.coletar": ("agendada", 2, 300, "noticias", "0 */2 * * *"),
    "progresso.atualizar": ("agendada", 2, 300, "progresso", "15 */6 * * *"),
    "backup.restic": ("agendada", 3, 600, "restic", None),
    "backup.dump_ayanami": ("agendada", 2, 60, "restic", "0 7 * * *"),
    "backup.enviar": ("agendada", 3, 600, "restic", "30 7 * * *"),
    "backup.reter": ("agendada", 2, 600, "restic", "0 8 * * 0"),
    "backup.verificar": ("agendada", 1, None, "restic", "30 8 * * 0"),
    "backup.restore_teste": ("agendada", 1, None, "restic", "0 9 1 * *"),
    "limpeza.diaria": ("agendada", 2, 60, "limpeza", "30 6 * * *"),
    "fila.reanimar": ("agendada", 1, None, "reanimar", "*/5 * * * *"),
    "stt.transcrever": ("lenta", 2, 60, None, None),
    "voz.cache_frases": ("lenta", 1, None, "voz", "0 6 * * 1"),
}
EMB = {"embeddings.lote": ("lenta", 2, 60, "emb", None)}


def _nossas(app: procrastinate.App) -> dict[str, procrastinate.tasks.Task]:
    return {n: t for n, t in app.tasks.items() if not n.startswith(("builtin:", "procrastinate."))}


def _crons(app: procrastinate.App) -> dict[str, tuple[str, dict]]:
    periodicas = app.periodic_registry.periodic_tasks.values()
    return {p.periodic_id: (p.cron, p.configure_kwargs) for p in periodicas}


@pytest.mark.parametrize(("cfg", "esperado"), [(CFG, TABELA), (CFG_EMB, TABELA | EMB)])
def test_ca_y13_registro_igual_a_tabela(cfg, esperado):
    app = fila.montar(cfg, testing.InMemoryConnector())
    tarefas = _nossas(app)
    assert set(tarefas) == set(esperado)
    assert len(tarefas) == (18 if cfg.embeddings.ligado else 17)
    crons = _crons(app)
    for nome, (fila_, a, w, lock, cron) in esperado.items():
        t = tarefas[nome]
        assert t.queue == fila_, nome
        assert t.lock == lock, nome
        if a == 1:
            assert t.retry_strategy is None, nome
        else:
            r = t.retry_strategy
            assert (r.max_attempts, r.wait, r.exponential_wait) == (a, w, 2), nome
        if cron:
            assert crons[nome] == (cron, {"queueing_lock": nome}), nome
        else:
            assert nome not in crons
    # periódicas: todas da agendada, menos o cache de voz (§4.2: roda na lenta, imagem -ml); o cron
    # dele só é deferido pelo worker agendada (os outros montam com periodicas=False)
    filas = {p.periodic_id: p.task.queue for p in app.periodic_registry.periodic_tasks.values()}
    assert {n for n, f in filas.items() if f != "agendada"} == {"voz.cache_frases"}


def test_sem_periodicas_nos_workers_rapida_e_lenta():
    app = fila.montar(CFG, testing.InMemoryConnector(), periodicas=False)
    assert not app.periodic_registry.periodic_tasks
    assert len(_nossas(app)) == 17


def test_locks_e_prioridade_no_defer():
    assert fila.defer_opcoes("agente.pesquisar", chave="k") == {"priority": 20, "queueing_lock": "k"}
    assert fila.defer_opcoes("monitor.passo", chave="k", lock_id="abc") == {"priority": 10,
                                                                            "lock": "monitor:abc"}
    assert fila.defer_opcoes("agente.lembrete", chave="k")["queueing_lock"] == "k"


def test_prazo_estourado_nao_repete():
    r = fila.POR_NOME["agente.pesquisar"].retry
    job = SimpleNamespace(attempts=0)
    assert r.get_retry_decision(exception=fila.PrazoEstourado("x", 1), job=job) is None
    assert r.get_retry_decision(exception=RuntimeError("x"), job=job) is not None
    assert r.get_retry_decision(exception=RuntimeError("x"), job=SimpleNamespace(attempts=2)) is None


async def test_prazo_vira_falha_sem_retry():
    app = procrastinate.App(connector=testing.InMemoryConnector())
    rel = RelogioFalso()

    async def demorado(deps, contexto):
        await asyncio.sleep(1)  # cortado pelo prazo de 0,01 s

    d = fila.Def("teste.demorado", "rapida", 0, 2, 0)
    object.__setattr__(d, "prazo_s", 0.01)
    fila.registrar(app, d, demorado)
    jid = await app.configure_task("teste.demorado").defer_async()
    await app.run_worker_async(queues=["rapida"], wait=False, listen_notify=False,
                               additional_context={"deps": Deps(db=None, cfg=CFG, relogio=rel)})
    assert (await app.job_manager.get_job_status_async(jid)).value == "failed"
    assert app.connector.jobs[jid]["attempts"] == 1


async def test_job_sem_deps_falha_claro():
    app = procrastinate.App(connector=testing.InMemoryConnector())

    async def corpo(deps, contexto):  # pragma: no cover
        return None

    fila.registrar(app, fila.Def("teste.x", "rapida", 5, 1), corpo)
    jid = await app.configure_task("teste.x").defer_async()
    await app.run_worker_async(queues=["rapida"], wait=False, listen_notify=False)
    assert (await app.job_manager.get_job_status_async(jid)).value == "failed"


def test_stubs_apontam_o_dono():
    import importlib

    for d in fila.TAREFAS:
        modulo, _, funcao = d.corpo.partition(":")
        fn = getattr(importlib.import_module(modulo), funcao)
        if modulo.endswith("manutencao"):
            continue
        assert "dono:" in (fn.__doc__ or ""), d.nome
    import ayanami.workers.push as push

    assert "P2.1" in push.enviar.__doc__


# --------------------------------------------------------------------------- reanimar


class _JmFalso:
    def __init__(self, presos):
        self.presos = presos
        self.repetidos = []
        self.pedido = None

    async def get_stalled_jobs(self, **kw):
        self.pedido = kw
        return list(self.presos)

    async def retry_job(self, job, **kw):
        self.repetidos.append(job.id)


class DbConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


@pytest.fixture
def base(pg_nova_base) -> str:
    dsn = pg_nova_base("ayanami_fila")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
        conn.execute(SchemaManager.get_schema())
    return dsn


@pytest.mark.pg
async def test_reanimar_devolve_presos_e_tarefa_volta_a_fila(base):
    db = DbConexao(base)
    rel = RelogioFalso()
    with psycopg.connect(base) as conn:
        conn.execute("INSERT INTO tarefas (tipo, titulo, estado, job_id) VALUES"
                     " ('pesquisa', 'a', 'rodando', 41), ('pesquisa', 'b', 'rodando', 42)")
    jm = _JmFalso([SimpleNamespace(id=41), SimpleNamespace(id=7)])
    ctx = SimpleNamespace(app=SimpleNamespace(job_manager=jm), job=SimpleNamespace(id=7))
    r = await manutencao.reanimar(Deps(db=db, cfg=CFG, relogio=rel), ctx, timestamp=0)
    assert jm.pedido == {"seconds_since_heartbeat": 300}
    assert jm.repetidos == [41]  # o próprio reanimar (7) nunca
    assert r["dados"]["jobs"] == [41]
    with psycopg.connect(base) as conn:
        estados = dict(conn.execute("SELECT job_id, estado FROM tarefas").fetchall())
    assert estados == {41: "na_fila", 42: "rodando"}


# --------------------------------------------------------------------------- limpeza


@pytest.mark.pg
async def test_limpeza_respeita_prazos(base, tmp_path):
    rel = RelogioFalso(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    agora = rel.agora()

    def dias(n: float) -> datetime:
        return agora - timedelta(days=n)

    with psycopg.connect(base) as conn:
        disp = conn.execute("INSERT INTO dispositivos (nome, tipo, hash, prefixo, escopos)"
                            " VALUES ('pc', 'pc', 'h', 'p', '{}') RETURNING id").fetchone()[0]
        for ts in (dias(91), dias(89)):
            conn.execute("INSERT INTO auditoria (ts, dispositivo, tipo, resumo, ok)"
                         " VALUES (%s, %s, 'tarefa', 'r', true)",
                         (ts, disp))
        for ts in (dias(31), dias(29)):
            conn.execute("INSERT INTO eventos (tipo, titulo, criado) VALUES ('x', 'y', %s)", (ts,))
        for sinc in (dias(31), dias(29), None):
            conn.execute("INSERT INTO nuvem_turnos (ts, dispositivo, texto_usuario, texto_resposta,"
                         " sincronizado) VALUES (%s, %s, 'a', 'b', %s)", (dias(60), disp, sinc))
        for i, exp in enumerate((dias(8), dias(6))):
            conn.execute("INSERT INTO confirmacoes (id, descricao, pedido, expira)"
                         " VALUES (%s, 'd', '{}', %s)",
                         (f"c{i}", exp))
        for i, exp in enumerate((dias(2), dias(0.5))):
            conn.execute("INSERT INTO pareamentos (codigo_hash, criado_por, expira) VALUES (%s, %s, %s)",
                         (f"h{i}", disp, exp))
        jobs = {}
        for rotulo, status, idade in (("ok_velho", "succeeded", 31), ("ok_novo", "succeeded", 29),
                                      ("cancel_velho", "cancelled", 40), ("falha_velha", "failed", 40)):
            jid = conn.execute("INSERT INTO procrastinate_jobs (queue_name, task_name, status)"
                               " VALUES ('rapida', 't', %s) RETURNING id", (status,)).fetchone()[0]
            conn.execute("INSERT INTO procrastinate_events (job_id, type, at) VALUES (%s, 'deferred', %s),"
                         " (%s, %s, %s)", (jid, dias(idade + 1), jid, status, dias(idade)))
            jobs[rotulo] = jid
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    velho, novo = entrada / "velho.ogg", entrada / "novo.ogg"
    for f, idade in ((velho, 3), (novo, 1)):
        f.write_bytes(b"x")
        ts = dias(idade).timestamp()
        os.utime(f, (ts, ts))

    deps = Deps(db=DbConexao(base), cfg=CFG, relogio=rel, dados=tmp_path)
    r = await manutencao.limpeza_diaria(deps, SimpleNamespace(), timestamp=0)
    assert r["dados"] == {"auditoria": 1, "eventos": 1, "nuvem_turnos": 1, "confirmacoes": 1,
                          "pareamentos": 1, "procrastinate_jobs": 2, "entrada": 1}
    assert not velho.exists() and novo.exists()
    with psycopg.connect(base) as conn:
        restam = {r[0] for r in conn.execute("SELECT id FROM procrastinate_jobs").fetchall()}
        assert restam == {jobs["ok_novo"], jobs["falha_velha"]}
        assert conn.execute("SELECT count(*) FROM nuvem_turnos").fetchone()[0] == 2
    # 2ª vez não apaga nada
    r2 = await manutencao.limpeza_diaria(deps, SimpleNamespace(), timestamp=0)
    assert set(r2["dados"].values()) == {0}


# --------------------------------------------------------------------------- worker e batimento


@pytest.mark.pg
async def test_worker_grava_batimento_e_healthcheck(base):
    db = DbConexao(base)
    rel = RelogioFalso()
    deps = Deps(db=db, cfg=CFG, relogio=rel)
    app = fila.montar(CFG, testing.InMemoryConnector(), periodicas=False)
    await worker.rodar(app, deps, "rapida", host="node2", wait=False, listen_notify=False)
    visto = worker.ultimo_batimento(db, "rapida")  # o relógio falso anda 30 s a cada batimento
    assert visto is not None and timedelta(0) <= rel.agora() - visto <= timedelta(seconds=30)
    assert worker.cli_batimento(["rapida", "--max", "60"], db=db, relogio=rel) == 0
    rel.avancar(61)
    assert worker.cli_batimento(["rapida", "--max", "60"], db=db, relogio=rel) == 1
    assert worker.cli_batimento(["lenta"], db=db, relogio=rel) == 1


def test_batimento_com_banco_fora_sai_2(capsys):
    class Fora:
        @contextmanager
        def connection(self):
            raise psycopg.OperationalError("fora")
            yield  # pragma: no cover

    assert worker.cli_batimento(["agendada"], db=Fora(), relogio=RelogioFalso()) == 2
    assert "OperationalError" in capsys.readouterr().err


async def test_batendo_repete_pelo_relogio():
    rel = RelogioFalso()
    gravados = []

    class Db:
        @contextmanager
        def connection(self):
            class C:
                def execute(self, sql, args):
                    gravados.append(args)

                @contextmanager
                def transaction(self):
                    yield

            yield C()

    t = asyncio.create_task(worker.batendo(Deps(db=Db(), cfg=CFG, relogio=rel), "lenta", "h"))
    for _ in range(200):
        await asyncio.sleep(0)
        if len(gravados) >= 3:
            break
    t.cancel()
    assert len(gravados) >= 3
    assert gravados[1][2] - gravados[0][2] == timedelta(seconds=30)


def test_worker_recusa_fila_desconhecida():
    with pytest.raises(SystemExit):
        worker.cli(["outra"])
