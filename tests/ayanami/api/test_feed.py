"""``GET /v1/feed`` (Y2.3): cards de notícia, tarefa e lembrete, do mais novo ao mais velho, paginados
por ``antes``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ayanami.eventos import criar_evento

pytestmark = pytest.mark.pg

T0 = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def _semear(db) -> list[str]:
    """Um card por minuto, alternando os três tipos; devolve os títulos do mais novo ao mais velho."""
    titulos = []
    with db.connection() as conn:
        for i in range(30):
            ts = T0 + timedelta(minutes=i)
            titulo = f"c{i:02d}"
            match i % 3:
                case 0:
                    conn.execute("INSERT INTO news_items (title, summary, first_seen) VALUES (%s, %s, %s)",
                                 (titulo, "s" * 300, ts))
                case 1:
                    conn.execute(
                        "INSERT INTO tarefas (tipo, titulo, estado, frase, criada, atualizada)"
                        " VALUES ('pesquisa', %s, 'ok', 'pronta', %s, %s)", (titulo, ts, ts))
                case 2:
                    criar_evento(db, "lembrete", titulo, "remédio", None, agora=ts)
            titulos.append(titulo)
        # fora do feed: tarefa rodando, tarefa do tipo lembrete, evento que não é lembrete
        sql = "INSERT INTO tarefas (tipo, titulo, estado, atualizada) VALUES (%s, %s, %s, %s)"
        conn.execute(sql, ("pesquisa", "r", "rodando", T0))
        conn.execute(sql, ("lembrete", "l", "ok", T0))
    criar_evento(db, "tarefa_pronta", "nao", agora=T0)
    return titulos[::-1]


async def test_feed_pagina_por_antes(app, cliente, novo_token, db):
    esperado = _semear(db)
    token = novo_token("celular-pedro", "celular")
    vistos, antes = [], None
    async with cliente(app, token) as c:
        while True:
            params = {"n": 7} | ({"antes": antes} if antes else {})
            r = await c.get("/v1/feed", params=params)
            assert r.status_code == 200
            cards = r.json()["cards"]
            if not cards:
                break
            assert len(cards) <= 7
            vistos += cards
            antes = cards[-1]["ts"]
    assert [x["titulo"] for x in vistos] == esperado
    por_tipo = {x["titulo"]: x for x in vistos}
    assert por_tipo["c00"]["tipo"] == "noticia" and por_tipo["c00"]["ref"].startswith("noticia:")
    assert len(por_tipo["c00"]["resumo"]) == 200
    assert por_tipo["c01"] | {"ref": None} == {"tipo": "tarefa", "titulo": "c01", "resumo": "pronta",
                                               "ts": "2026-01-01T11:01:00Z", "ref": None}
    assert por_tipo["c02"]["tipo"] == "lembrete" and por_tipo["c02"]["resumo"] == "remédio"


async def test_feed_padrao_e_validacao(app, cliente, novo_token, db):
    _semear(db)
    token = novo_token("celular-pedro", "celular")
    async with cliente(app, token) as c:
        r = await c.get("/v1/feed")
        assert r.status_code == 200 and len(r.json()["cards"]) == 30  # relógio falso 12:00 > tudo
        assert (await c.get("/v1/feed", params={"n": 0})).status_code == 422
        assert (await c.get("/v1/feed", params={"n": 101})).status_code == 422
        assert (await c.get("/v1/feed", params={"antes": "ontem"})).status_code == 422
        r = await c.get("/v1/feed", params={"antes": "2026-01-01T11:01:00Z"})
        assert [x["titulo"] for x in r.json()["cards"]] == ["c00"]


async def test_feed_sem_escopo_403(app, cliente, novo_token):
    token = novo_token("casa-sala", "casa")
    async with cliente(app, token) as c:
        assert (await c.get("/v1/feed")).status_code == 403
