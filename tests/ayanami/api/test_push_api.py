"""P2.1 — ``/v1/push/assinar`` (POST/DELETE) pelo ASGI em memória, banco no ``ayanami-pg-teste``."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.pg

SUB = {"endpoint": "https://fcm.exemplo/send/abc", "expirationTime": None,
       "keys": {"p256dh": "BFalsoChavePublicaDoNavegador_123-abc", "auth": "authFalso_12"}}


def _assinaturas(db):
    with db.connection() as conn:
        return conn.execute("SELECT d.nome, s.endpoint, s.falhas FROM push_assinaturas s"
                            " JOIN dispositivos d ON d.id = s.dispositivo ORDER BY s.id").fetchall()


async def test_assinar_substitui_e_desassinar(app, db, cliente, novo_token):
    token = novo_token("celular-pedro", "celular")
    async with cliente(app, token) as c:
        r = await c.post("/v1/push/assinar", json=SUB)
        assert r.status_code == 201
        assert _assinaturas(db) == [("celular-pedro", SUB["endpoint"], 0)]
        r = await c.post("/v1/push/assinar", json=SUB)  # repetir é idempotente
        assert r.status_code == 201 and len(_assinaturas(db)) == 1
        nova = {**SUB, "endpoint": "https://fcm.exemplo/send/def"}
        assert (await c.post("/v1/push/assinar", json=nova)).status_code == 201
        assert _assinaturas(db) == [("celular-pedro", nova["endpoint"], 0)]  # uma por celular
        r = await c.request("DELETE", "/v1/push/assinar", json={"endpoint": nova["endpoint"]})
        assert r.status_code == 204 and _assinaturas(db) == []
        r = await c.request("DELETE", "/v1/push/assinar", json={"endpoint": nova["endpoint"]})
        assert r.status_code == 204
    with db.connection() as conn:
        resumos = [r[0] for r in conn.execute("SELECT resumo FROM auditoria WHERE tipo = 'push'")]
    assert "assinatura gravada" in resumos and "assinatura apagada" in resumos
    assert not any("fcm.exemplo" in r for r in resumos)


async def test_endpoint_muda_de_dono(app, db, cliente, novo_token):
    t1, t2 = novo_token("celular-a", "celular"), novo_token("celular-b", "celular")
    async with cliente(app, t1) as c:
        assert (await c.post("/v1/push/assinar", json=SUB)).status_code == 201
    async with cliente(app, t2) as c:
        assert (await c.post("/v1/push/assinar", json=SUB)).status_code == 201
        assert _assinaturas(db) == [("celular-b", SUB["endpoint"], 0)]
    async with cliente(app, t1) as c:  # o antigo dono não apaga a do outro
        r = await c.request("DELETE", "/v1/push/assinar", json={"endpoint": SUB["endpoint"]})
        assert r.status_code == 204 and len(_assinaturas(db)) == 1


async def test_recusas(app, db, cliente, novo_token):
    async with cliente(app) as c:
        assert (await c.post("/v1/push/assinar", json=SUB)).status_code == 401
    async with cliente(app, novo_token("pc-pedro", "pc")) as c:
        r = await c.post("/v1/push/assinar", json=SUB)
        assert r.status_code == 403 and r.json()["erro"] == "tipo_proibido"
    async with cliente(app, novo_token("celular-pedro", "celular")) as c:
        for ruim in ({**SUB, "endpoint": "http://fcm.exemplo/x"}, {"endpoint": SUB["endpoint"]},
                     {**SUB, "keys": {"p256dh": "não base64!", "auth": "authFalso_12"}}):
            assert (await c.post("/v1/push/assinar", json=ruim)).status_code == 422
    assert _assinaturas(db) == []


async def test_chave_publica(app, cliente, novo_token):
    from ayanami.config import Segredos

    token = novo_token("celular-pedro", "celular")
    async with cliente(app, token) as c:
        app.state.ctx.segredos = None
        r = await c.get("/v1/push/chave")
        assert r.status_code == 503 and r.json()["erro"] == "sem_vapid"
        app.state.ctx.segredos = Segredos({"VAPID_PUBLIC_KEY": "BPublicaFalsa_abc"})
        r = await c.get("/v1/push/chave")
        assert r.status_code == 200 and r.json() == {"chave": "BPublicaFalsa_abc"}
    async with cliente(app, novo_token("pc-casa", "pc")) as c:
        assert (await c.get("/v1/push/chave")).status_code in (403, 401)
