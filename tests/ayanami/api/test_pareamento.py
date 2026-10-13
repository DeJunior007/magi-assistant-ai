"""CA-Y8: código de 6 dígitos, 5 min, uso único, 10º erro mata, 6º pedido/min do IP → 429, token
com escopos de ``celular``; preferências do dispositivo."""

from __future__ import annotations

import re

import pytest

from ayanami.api.auth import ESCOPOS_PADRAO, TOKEN_RE

pytestmark = pytest.mark.pg


async def _codigo(app, cliente, pc_token, **corpo):
    async with cliente(app, pc_token) as c:
        r = await c.post("/v1/pareamento", json=corpo or {"nome_sugerido": "celular-pedro"})
    assert r.status_code == 201, r.text
    return r.json()


async def _trocar(app, cliente, codigo, nome="celular-pedro", ip="100.64.0.9"):
    async with cliente(app, ip=ip) as c:
        return await c.post("/v1/pareamento/trocar", json={"codigo": codigo, "nome": nome})


@pytest.fixture
def pc(novo_token):
    return novo_token("pc", "pc")


async def test_pareia_e_o_token_tem_escopos_de_celular(app, cliente, pc, db):
    corpo = await _codigo(app, cliente, pc)
    assert re.fullmatch(r"\d{6}", corpo["codigo"])
    assert corpo["expira_em"] == "2026-01-01T12:05:00Z"
    r = await _trocar(app, cliente, corpo["codigo"])
    assert r.status_code == 201
    j = r.json()
    assert TOKEN_RE.match(j["token"]) and j["token"].startswith("ayn_celular_")
    assert j["nome"] == "celular-pedro" and j["escopos"] == sorted(ESCOPOS_PADRAO["celular"])
    async with cliente(app, j["token"]) as c:
        assert (await c.get("/v1/feed")).status_code == 200  # autenticou
    # uso único
    assert (await _trocar(app, cliente, corpo["codigo"], nome="outro")).status_code == 400
    with db.connection() as conn:
        assert conn.execute("SELECT codigo_hash FROM pareamentos").fetchone()[0] != corpo["codigo"]
        assert conn.execute("SELECT count(*) FROM auditoria WHERE ok").fetchone()[0] == 2


async def test_so_pc_pede_codigo(app, cliente, novo_token):
    async with cliente(app, novo_token("cel", "celular")) as c:
        r = await c.post("/v1/pareamento", json={})
    assert r.status_code == 403 and r.json()["erro"] == "tipo_proibido"


async def test_expira_em_5_minutos(app, cliente, pc, relogio):
    codigo = (await _codigo(app, cliente, pc))["codigo"]
    relogio.avancar(300)
    r = await _trocar(app, cliente, codigo)
    assert r.status_code == 400 and r.json()["erro"] == "codigo_invalido"


async def test_codigo_novo_invalida_o_anterior(app, cliente, pc):
    velho = (await _codigo(app, cliente, pc))["codigo"]
    novo = (await _codigo(app, cliente, pc))["codigo"]
    assert velho != novo
    assert (await _trocar(app, cliente, velho, ip="100.64.0.2")).status_code == 400
    assert (await _trocar(app, cliente, novo, ip="100.64.0.3")).status_code == 201


async def test_decimo_erro_mata_o_codigo(app, cliente, pc):
    codigo = (await _codigo(app, cliente, pc))["codigo"]
    errado = "000000" if codigo != "000000" else "111111"
    for i in range(9):
        r = await _trocar(app, cliente, errado, ip=f"100.64.1.{i}")
        assert r.status_code == 400, i
    r = await _trocar(app, cliente, errado, ip="100.64.2.1")
    assert r.status_code == 429 and r.json()["erro"] == "codigo_morto"
    # o 11º, mesmo com o código certo, não passa: o código morreu
    assert (await _trocar(app, cliente, codigo, ip="100.64.2.2")).status_code == 400


async def test_sexto_pedido_por_minuto_do_ip(app, cliente, pc, relogio):
    codigo = (await _codigo(app, cliente, pc))["codigo"]
    for _ in range(5):
        assert (await _trocar(app, cliente, "999999", ip="100.64.3.3")).status_code == 400
    r = await _trocar(app, cliente, codigo, ip="100.64.3.3")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    relogio.avancar(60)
    assert (await _trocar(app, cliente, codigo, ip="100.64.3.3")).status_code == 201


async def test_nome_em_uso_nao_gasta_o_codigo(app, cliente, pc, novo_token):
    novo_token("celular-pedro", "celular")
    codigo = (await _codigo(app, cliente, pc))["codigo"]
    r = await _trocar(app, cliente, codigo)
    assert r.status_code == 409 and r.json()["erro"] == "nome_em_uso"
    assert (await _trocar(app, cliente, codigo, nome="celular-dois")).status_code == 201


async def test_nome_invalido(app, cliente, pc):
    codigo = (await _codigo(app, cliente, pc))["codigo"]
    for nome in ("Celular", "ayanami", "-x", "a" * 33):
        assert (await _trocar(app, cliente, codigo, nome=nome, ip=f"100.64.4.{len(nome)}")).status_code == 422


async def test_preferencias(app, cliente, novo_token, db):
    token = novo_token("cel", "celular")
    pref = {"push": True, "push_com_pc": False, "silencio": "23:00-07:30", "tv_padrao": "sala",
            "voz_em_texto": True}
    async with cliente(app, token) as c:
        assert (await c.put("/v1/dispositivo/preferencias", json=pref)).status_code == 204
        r = await c.put("/v1/dispositivo/preferencias", json={**pref, "silencio": "25:00-07:00"})
        assert r.status_code == 422 and r.json()["erro"] == "invalido"
        assert (await c.put("/v1/dispositivo/preferencias", json={"x": 1})).status_code == 422
    with db.connection() as conn:
        assert conn.execute("SELECT preferencias FROM dispositivos WHERE nome = 'cel'").fetchone()[0] == pref
    async with cliente(app, novo_token("casa", "casa")) as c:
        assert (await c.put("/v1/dispositivo/preferencias", json=pref)).status_code == 403
