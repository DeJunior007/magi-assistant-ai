"""Limites da §2.3: 61ª requisição/min → 429 com ``Retry-After``; rotas isentas; tamanho de corpo
→ 413; log de acesso sem token, ``Bearer`` nem corpo (R10.1)."""

from __future__ import annotations

import json
import logging
import re

import pytest

from ayanami.api.auth import TOKEN_RE, ErroApi, gerar_token, hash_token, prefixo_token
from ayanami.api.limites import KIB, Janela
from ayanami.relogio import RelogioFalso


@pytest.mark.parametrize("tipo", ["pc", "casa", "celular", "mcp"])
def test_formato_do_token(tipo):
    vistos = {gerar_token(tipo) for _ in range(50)}
    assert len(vistos) == 50
    for t in vistos:
        assert TOKEN_RE.match(t)
        assert prefixo_token(t) == t[: len(f"ayn_{tipo}_") + 4]
        assert re.fullmatch(r"[0-9a-f]{64}", hash_token(t))


def test_janela_deslizante():
    r = RelogioFalso()
    j = Janela(r, 3)
    for _ in range(3):
        j.contar("a")
        r.avancar(10)
    with pytest.raises(ErroApi) as e:
        j.contar("a")
    assert e.value.status == 429 and e.value.headers["Retry-After"] == "30"
    j.contar("b")
    r.avancar(30)
    j.contar("a")


@pytest.mark.pg
async def test_61a_requisicao_por_minuto(app, cliente, novo_token, relogio):
    um, outro = novo_token("um", "celular"), novo_token("outro", "celular")
    async with cliente(app, um) as c:
        for i in range(60):
            assert (await c.get("/v1/feed")).status_code == 501, i
        r = await c.get("/v1/feed")
        assert r.status_code == 429 and r.json()["erro"] == "muitas_requisicoes"
        assert r.headers["Retry-After"] == "60"
        for _ in range(5):  # rotas isentas
            assert (await c.get("/v1/eventos")).status_code == 501
    async with cliente(app, outro) as c:
        assert (await c.get("/v1/feed")).status_code == 501
    relogio.avancar(60)
    async with cliente(app, um) as c:
        assert (await c.get("/v1/feed")).status_code == 501


@pytest.mark.pg
async def test_corpo_grande_413(app, cliente, novo_token):
    token = novo_token("cel", "celular")
    grande = {"silencio": "x" * (257 * KIB)}
    async with cliente(app, token) as c:
        r = await c.put("/v1/dispositivo/preferencias", json=grande)
        assert r.status_code == 413 and r.json()["erro"] == "corpo_grande"

        async def pedacos():
            for _ in range(5):
                yield b"x" * (64 * KIB)

        r = await c.put("/v1/dispositivo/preferencias", content=pedacos(),
                        headers={"content-type": "application/json"})
        assert r.status_code == 413
        # /v1/turno aceita até 1 MiB: passa do limite de corpo e chega na rota (stub)
        r = await c.post("/v1/turno", content=b"x" * (300 * KIB),
                         headers={"content-type": "application/json"})
        assert r.status_code == 501


@pytest.mark.pg
async def test_log_sem_token_nem_corpo(app, cliente, novo_token, caplog):
    token = novo_token("cel", "celular")
    with caplog.at_level(logging.DEBUG):
        async with cliente(app, token) as c:
            for i in range(25):
                await c.put("/v1/dispositivo/preferencias", json={"tv_padrao": f"TV-secreta-{i}"})
                await c.get(f"/v1/turno/01J{i:023d}")
    assert len([r for r in caplog.records if r.name == "ayanami.api.acesso"]) == 50
    texto = caplog.text
    assert "ayn_" not in texto and "Bearer" not in texto and "TV-secreta" not in texto
    assert token[12:] not in texto
    linha = json.loads(next(r.getMessage() for r in caplog.records if r.name == "ayanami.api.acesso"))
    assert set(linha) == {"metodo", "rota", "status", "dispositivo", "ms", "entrada", "saida"}
    assert linha["rota"] == "/v1/dispositivo/preferencias" and linha["status"] == 204
    assert linha["dispositivo"] is not None and linha["entrada"] > 0
    rotas = {json.loads(r.getMessage())["rota"] for r in caplog.records if r.name == "ayanami.api.acesso"}
    assert "/v1/turno/{id}" in rotas
