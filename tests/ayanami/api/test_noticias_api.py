"""``GET /v1/noticias`` e ``PUT /v1/noticias/preferencias`` (Y3.2; spec §5.2, CA-Y16)."""

from __future__ import annotations

import psycopg
import pytest

from magi.elo import news_sync

pytestmark = pytest.mark.pg


def _semear(dsn: str, n: int) -> None:
    """``n`` itens: metade com o mesmo ``atualizado`` (empate resolvido pelo ``id``)."""
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO news_sources (name, kind, url, trust) VALUES"
                     " ('A', 'rss', 'https://a.test/feed', 3)")
        conn.execute(
            "INSERT INTO news_items (title, embedding, atualizado)"
            " SELECT 'item ' || g, NULL, CASE WHEN g %% 2 = 0 THEN '2026-10-12T20:00:00Z'::timestamptz"
            " ELSE '2026-10-12T20:00:00Z'::timestamptz + g * interval '1 microsecond' END"
            " FROM generate_series(1, %s) g", [n])
        conn.execute(
            "INSERT INTO news_raw (source_id, url, title, body) SELECT s.id, 'https://a.test/' || i.id,"
            " i.title, 'corpo' FROM news_items i, news_sources s")
        conn.execute(
            "INSERT INTO news_item_sources (item_id, raw_id) SELECT i.id, r.id FROM news_items i"
            " JOIN news_raw r ON r.url = 'https://a.test/' || i.id")


async def _paginas(c, n=200):
    paginas, desde = [], None
    for _ in range(10):
        params = {"n": n} | ({"desde": desde} if desde else {})
        r = await c.get("/v1/noticias", params=params)
        assert r.status_code == 200, r.text
        p = r.json()
        paginas.append(p)
        desde = p["cursor"]
        if p["fim"]:
            return paginas
    raise AssertionError("sem fim")


async def test_ca_y16_450_itens_em_3_paginas(app, db, cliente, novo_token):
    _semear(db.dsn, 450)
    async with cliente(app, novo_token("pc", "pc")) as c:
        paginas = await _paginas(c)
        assert [len(p["itens"]) for p in paginas] == [200, 200, 50]
        assert [p["fim"] for p in paginas] == [False, False, True]
        uids = [i["uid"] for p in paginas for i in p["itens"]]
        assert len(uids) == len(set(uids)) == 450
        p0 = paginas[0]
        item = p0["itens"][0]
        assert item["brutos"] and set(item) >= {"uid", "title", "summary", "embedding", "first_seen",
                                                "sources", "max_trust", "franchise", "kind",
                                                "spoiler", "priority", "level", "brutos"}
        assert {b["url"] for b in p0["brutos"]} == {u for i in p0["itens"] for u in i["brutos"]}
        assert p0["fontes"] == [{"name": "A", "kind": "rss", "url": "https://a.test/feed", "trust": 3}]
        assert p0["brutos"][0]["fonte_url"] == "https://a.test/feed"
        ts, _, ident = p0["cursor"].rpartition("|")
        assert ts.endswith("Z") and ident.isdigit()

        # nada novo: mesma posição, fim
        r = await c.get("/v1/noticias", params={"desde": paginas[-1]["cursor"]})
        assert r.json() | {"cursor": None} == {"cursor": None, "fim": True, "fontes": [], "brutos": [],
                                               "itens": []}
        assert r.json()["cursor"] == paginas[-1]["cursor"]

        # item editado volta numa página nova (o gatilho move o atualizado)
        with psycopg.connect(db.dsn) as conn:
            conn.execute("UPDATE news_items SET level = 'alta' WHERE title = 'item 7'")
        r = await c.get("/v1/noticias", params={"desde": paginas[-1]["cursor"]})
        assert [i["title"] for i in r.json()["itens"]] == ["item 7"]


async def test_banco_vazio_e_cursor_invalido(app, cliente, novo_token):
    async with cliente(app, novo_token("pc", "pc")) as c:
        r = await c.get("/v1/noticias")
        assert r.json() == {"cursor": None, "fim": True, "fontes": [], "brutos": [], "itens": []}
        for ruim in ("lixo", "2026-10-12T20:00:00|x", "2026-10-12T20:00:00|1"):
            r = await c.get("/v1/noticias", params={"desde": ruim})
            assert r.status_code == 422 and r.json()["erro"] == "invalido"
        assert (await c.get("/v1/noticias", params={"n": 201})).status_code == 422


async def test_escopo(app, cliente, novo_token):
    async with cliente(app, novo_token("cel", "celular")) as c:
        assert (await c.get("/v1/noticias")).status_code == 403
        assert (await c.put("/v1/noticias/preferencias", json={})).status_code == 403
    async with cliente(app) as c:
        assert (await c.get("/v1/noticias")).status_code == 401


async def test_preferencias_substitui_prefs_e_progresso_nao_regride(app, db, cliente, novo_token):
    with psycopg.connect(db.dsn) as conn:
        conn.execute("INSERT INTO franchise_prefs (franchise, weight) VALUES ('Some', 2)")
        conn.execute("INSERT INTO progress (franchise, kind, value, updated_at) VALUES"
                     " ('Frieren', 'episode', '12', '2026-10-12T00:00:00Z'),"
                     " ('Silksong', 'hours', '30', '2026-10-01T00:00:00Z')")
    corpo = {
        "franchise_prefs": [{"franchise": "Frieren", "weight": 1.5, "dropped": False, "spoilers_ok": True}],
        "progress": [
            {"franchise": "Frieren", "kind": "episode", "value": "10", "updated_at": "2026-10-10T00:00:00Z"},
            {"franchise": "Silksong", "kind": "hours", "value": "41", "updated_at": "2026-10-11T00:00:00Z"},
            {"franchise": "Nova", "kind": "episode", "value": "1", "updated_at": None},
        ],
    }
    async with cliente(app, novo_token("pc", "pc")) as c:
        r = await c.put("/v1/noticias/preferencias", json=corpo)
        assert r.status_code == 204
        assert (await c.put("/v1/noticias/preferencias", json={"progress": [{"kind": "x"}]})
                ).status_code == 422
    with psycopg.connect(db.dsn) as conn:
        assert conn.execute("SELECT franchise, weight, spoilers_ok FROM franchise_prefs").fetchall() == [
            ("Frieren", 1.5, True)]
        prog = dict(conn.execute("SELECT franchise, value FROM progress").fetchall())
    assert prog == {"Frieren": "12", "Silksong": "41", "Nova": "1"}


async def test_paginas_aplicam_no_pc_pelo_news_sync(app, db, cliente, novo_token, pg_base_pc):
    """Contrato com a Y3.3: as páginas gravam no esquema do PC sem duplicar."""
    _semear(db.dsn, 5)
    with psycopg.connect(db.dsn) as conn:
        conn.execute("UPDATE news_items SET embedding = array_fill(0.5::real, ARRAY[768])::vector,"
                     " spoiler = '{\"has\": false}', level = 'normal'")
    async with cliente(app, novo_token("pc", "pc")) as c:
        paginas = await _paginas(c, n=2)
    with psycopg.connect(pg_base_pc) as pc:
        try:
            dim = news_sync.dimensao_embedding(pc)
            for _ in range(2):
                for p in paginas:
                    news_sync.aplicar_pagina(pc, p, dim)
            sql = "SELECT count(*) FROM news_items WHERE ayanami_uid IS NOT NULL"
            n_itens = pc.execute(sql).fetchone()[0]
            n_brutos = pc.execute("SELECT count(*) FROM news_raw").fetchone()[0]
            n_emb = pc.execute("SELECT count(*) FROM news_items WHERE embedding IS NOT NULL").fetchone()[0]
            assert (n_itens, n_brutos, n_emb) == (5, 5, 5)
        finally:
            with pc.transaction():
                pc.execute("DELETE FROM news_items; DELETE FROM news_raw; DELETE FROM news_sources")
