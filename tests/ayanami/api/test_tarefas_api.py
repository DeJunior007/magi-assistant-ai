"""Y3.1: ``/v1/tarefas*`` e ``/v1/fila`` (spec §2.2, §4.3). Fila em ``InMemoryConnector`` posta em
``ctx.extras["fila"]``; banco ``pg``."""

from __future__ import annotations

import procrastinate
import pytest
from procrastinate import testing

from ayanami import fila

pytestmark = pytest.mark.pg

CORPO = {"tipo": "pesquisa", "titulo": "preço da placa", "params": {"pedido": "quanto custa?"}}


@pytest.fixture
def app_fila() -> procrastinate.App:
    return fila.montar(None, testing.InMemoryConnector(), periodicas=False)


@pytest.fixture
def api(fazer_app, db, app_fila):
    app = fazer_app(db)
    app.state.ctx.extras["fila"] = app_fila
    return app


async def test_post_repetido_mesma_chave_devolve_200_com_a_existente(api, cliente, novo_token, app_fila):
    token = novo_token("celular-pedro", "celular")
    async with cliente(api, token) as c:
        r1 = await c.post("/v1/tarefas", json=CORPO | {"chave": "rtx"})
        r2 = await c.post("/v1/tarefas", json=CORPO | {"chave": "rtx"})
        r3 = await c.post("/v1/tarefas", json=CORPO)  # chave padrão = sha256(tipo + params)
        r4 = await c.post("/v1/tarefas", json=CORPO)
    assert (r1.status_code, r2.status_code, r3.status_code, r4.status_code) == (201, 200, 201, 200)
    assert r2.json() == r1.json() and r4.json()["id"] == r3.json()["id"]
    corpo = r1.json()
    assert set(corpo) == {"id", "tipo", "titulo", "estado", "progresso", "frase", "origem", "criada",
                          "atualizada", "resultado", "erro"}
    assert corpo["estado"] == "na_fila" and corpo["criada"].endswith("Z")
    assert len(app_fila.connector.jobs) == 2


async def test_listar_ver_cancelar(api, cliente, novo_token, app_fila):
    token = novo_token("pc", "pc")
    async with cliente(api, token) as c:
        tid = (await c.post("/v1/tarefas", json=CORPO)).json()["id"]
        lista = (await c.get("/v1/tarefas")).json()["tarefas"]
        assert [t["id"] for t in lista] == [tid]
        assert (await c.get("/v1/tarefas", params={"estado": "ok"})).json() == {"tarefas": []}
        assert (await c.get("/v1/tarefas", params={"estado": "xx"})).status_code == 422
        assert (await c.get(f"/v1/tarefas/{tid}")).json()["id"] == tid
        assert (await c.get("/v1/tarefas/nao-e-uuid")).status_code == 404
        assert (await c.get("/v1/tarefas/00000000-0000-0000-0000-000000000000")).status_code == 404
        r = await c.delete(f"/v1/tarefas/{tid}")
        assert (r.status_code, r.json()) == (202, {"estado": "cancelada"})
        r = await c.delete(f"/v1/tarefas/{tid}")
        assert r.status_code == 409 and r.json()["erro"] == "ja_terminou"
        assert (await c.delete("/v1/tarefas/00000000-0000-0000-0000-000000000000")).status_code == 404
        assert (await c.get(f"/v1/tarefas/{tid}")).json()["estado"] == "cancelada"


@pytest.mark.parametrize("corpo", [
    {"tipo": "pesquisa", "titulo": "", "params": {"pedido": "x"}},
    {"tipo": "pesquisa", "titulo": "t", "params": {}},
    {"tipo": "xpto", "titulo": "t", "params": {}},
    {"tipo": "monitor", "titulo": "t", "params": {"o_que": "a", "condicao": "b", "a_cada_h": 9}},
    {"tipo": "lembrete", "titulo": "t", "params": {"texto": "a", "quando": "ontem"}},
])
async def test_post_invalido_422(api, cliente, novo_token, corpo, app_fila):
    async with cliente(api, novo_token("pc", "pc")) as c:
        r = await c.post("/v1/tarefas", json=corpo)
    assert r.status_code == 422 and r.json()["erro"] == "invalido"
    assert not app_fila.connector.jobs


async def test_escopo_tarefas_exigido(api, cliente, novo_token):
    async with cliente(api, novo_token("casa", "casa")) as c:
        assert (await c.get("/v1/tarefas")).status_code == 403
        assert (await c.get("/v1/fila")).status_code == 403
    async with cliente(api) as c:
        assert (await c.post("/v1/tarefas", json=CORPO)).status_code == 401


async def test_fila_sem_esquema_da_lib_e_com_jobs(api, cliente, novo_token, db):
    from procrastinate.schema import SchemaManager

    async with cliente(api, novo_token("pc", "pc")) as c:
        r = await c.get("/v1/fila")
        assert (r.status_code, r.json()) == (200, {"contagem": {}, "lentas": [], "falhas": []})
        with db.connection() as conn:
            conn.execute(SchemaManager.get_schema())
            for status, ev in (("todo", None), ("doing", "started"), ("failed", "failed")):
                jid = conn.execute("INSERT INTO procrastinate_jobs (queue_name, task_name, status)"
                                   " VALUES ('rapida', 'agente.pesquisar', %s) RETURNING id",
                                   (status,)).fetchone()[0]
                if ev:
                    conn.execute("INSERT INTO procrastinate_events (job_id, type) VALUES (%s, %s)", (jid, ev))
        r = (await c.get("/v1/fila")).json()
    assert r["contagem"] == {"rapida": {"todo": 1, "doing": 1, "failed": 1}}
    assert [x["tarefa"] for x in r["lentas"]] == ["agente.pesquisar"]
    assert [x["fila"] for x in r["falhas"]] == ["rapida"]
