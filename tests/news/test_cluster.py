"""Tarefa 6.6: agrupamento de notícias (R18.3, R18.6).

Embeddings falsos e determinísticos: cada "assunto" é um eixo; textos do mesmo assunto ficam com
cosseno ~0,99, assuntos diferentes ~0. Os testes ``db`` usam um schema temporário.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import NewsItem, NewsRaw, NewsSource
from magi.memory import migrate as mig
from magi.news import __main__ as news_main
from magi.news.cluster import cluster_pending, embed_text, lead
from magi.news.repo import PgNewsRepo
from magi.providers.keypool import FreeQuotaExhausted


def HOUR_AGO() -> datetime:  # noqa: N802
    return datetime.now(UTC) - timedelta(hours=1)


DIM = 768  # padrão de {{NEWS_DIM}} na migração
TOPICS = ["frieren", "silksong", "persona"]


class FakeEmbedder:
    name = "fake"
    dimensions = DIM

    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[int] = []
        self.fail_after = fail_after

    async def embed(self, texts, *, personal):
        assert personal is False
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise FreeQuotaExhausted("cota gratuita acabou")
        self.calls.append(len(texts))
        return [vector(t) for t in texts]


def vector(text: str) -> list[float]:
    v = [0.0] * DIM
    low = text.lower()
    topic = next((i for i, t in enumerate(TOPICS) if t in low), None)
    if topic is not None:
        v[topic] = 1.0
    h = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
    v[10 + h % (DIM - 10)] += 0.1 if topic is not None else 1.0
    return v


def test_lead_e_texto():
    body = "<p>Primeiro   parágrafo.</p>\n<p>" + "x " * 400 + "</p>"
    got = lead(body)
    assert got.startswith("Primeiro parágrafo. x") and len(got) <= 301 and got.endswith("…")
    assert embed_text(NewsRaw(source_id=1, url="u", title=" T ", body="<b>a</b>")) == "T\na"


def test_sem_tarefa_news_pula():
    assert news_main.make_embedder(None) is None


# --- banco -----------------------------------------------------------------------------------


@pytest.fixture
def schema():
    name = f"test_cluster_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name)
        yield name
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


@pytest.fixture
async def repo(schema):
    r = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    yield r
    await r.close()


async def _sources(repo, trusts=(1, 3, 2)):
    return [
        await repo.upsert_source(
            NewsSource(name=f"site{i}", kind="rss", url=f"https://s{i}.example/", trust=t)
        )
        for i, t in enumerate(trusts)
    ]


async def _raw(repo, sid, n, title, body=""):
    raw = NewsRaw(source_id=sid, url=f"https://s{sid}.example/{n}", title=title, body=body)
    rid = await repo.add_raw(raw)
    assert rid is not None
    return rid


async def _links(repo):
    cur = await repo.conn.execute("SELECT item_id, raw_id FROM news_item_sources ORDER BY raw_id")
    return await cur.fetchall()


@pytest.mark.db
async def test_mesma_noticia_de_3_sites_vira_1_item(repo):
    s = await _sources(repo)
    a = await _raw(repo, s[0], 1, "Frieren ganha 2ª temporada", "Anúncio feito hoje.")
    b = await _raw(repo, s[1], 1, "Segunda temporada de Frieren confirmada", "Estúdio Madhouse.")
    c = await _raw(repo, s[2], 1, "FRIEREN: temporada 2 anunciada")
    await _raw(repo, s[0], 2, "Silksong tem data de lançamento")
    emb = FakeEmbedder()
    rep = await cluster_pending(repo, emb, batch_size=3)
    assert (rep.embedded, rep.created, rep.joined, rep.quota_exhausted) == (4, 2, 2, False)
    assert emb.calls == [3, 1]  # lotes
    links = await _links(repo)
    frieren = {item for item, raw in links if raw in (a, b, c)}
    assert len(frieren) == 1 and len(links) == 4
    (item, cos), *_ = await repo.similar_items(vector("frieren"), HOUR_AGO(), 0.88)
    assert item.id in frieren and cos > 0.95
    assert (item.sources, item.max_trust, item.title) == (3, 3, "Frieren ganha 2ª temporada")
    assert item.summary == "Anúncio feito hoje."
    (other, _), = await repo.similar_items(vector("silksong"), HOUR_AGO(), 0.88)
    assert (other.sources, other.max_trust) == (1, 1)
    assert await repo.ungrouped_raw() == []
    # outra crua do mesmo site não conta fonte nova
    await _raw(repo, s[1], 2, "Frieren: mais detalhes da temporada 2")
    await cluster_pending(repo, emb)
    (item, _), = await repo.similar_items(vector("frieren"), HOUR_AGO(), 0.88)
    assert item.sources == 3


@pytest.mark.db
async def test_janela_de_72h(repo):
    s = await _sources(repo)
    now = datetime.now(UTC)
    old = await repo.add_item(
        NewsItem(title="Persona 6 (velho)", first_seen=now - timedelta(hours=73)), vector("persona velho"), []
    )
    recent = await repo.add_item(
        NewsItem(title="Silksong (71 h)", first_seen=now - timedelta(hours=71)), vector("silksong 71"), []
    )
    p = await _raw(repo, s[0], 1, "Persona 6 anunciado")
    k = await _raw(repo, s[1], 1, "Silksong: patch novo")
    rep = await cluster_pending(repo, FakeEmbedder(), now=lambda: now)
    assert (rep.created, rep.joined) == (1, 1)
    links = dict((raw, item) for item, raw in await _links(repo))
    assert links[k] == recent
    assert links[p] not in (old, recent)


@pytest.mark.db
async def test_cota_esgotada_deixa_pendente(repo):
    s = await _sources(repo)
    ids = [await _raw(repo, s[i % 3], i, f"Frieren notícia {i}") for i in range(5)]
    rep = await cluster_pending(repo, FakeEmbedder(fail_after=1), batch_size=2)
    assert (rep.embedded, rep.deferred, rep.quota_exhausted) == (2, 3, True)
    assert [r.id for r in await repo.ungrouped_raw()] == ids[2:]
    rep = await cluster_pending(repo, FakeEmbedder(), batch_size=2)
    assert (rep.embedded, rep.created, rep.joined) == (3, 0, 3)
    assert await repo.ungrouped_raw() == []


@pytest.mark.db
async def test_magi_news_agrupa_depois_da_coleta(schema, monkeypatch):
    async def collect(repo, sources, http, **kw):
        sid = (await _sources(repo, (2,)))[0]
        await repo.add_raw(NewsRaw(source_id=sid, url="https://s.example/1", title="Frieren voltou"))
        return "relatório"

    monkeypatch.setattr(news_main, "collect_all", collect)
    monkeypatch.setattr(news_main, "make_http_client", lambda: httpx.AsyncClient())
    monkeypatch.setattr(news_main, "make_embedder", lambda config: FakeEmbedder(fail_after=0))
    dsn = f"{mig.dsn_from_env()}?options=-csearch_path%3D{schema},public"
    assert await news_main.run_once(None, dsn) == "relatório"  # cota esgotada não é erro
    monkeypatch.setattr(news_main, "make_embedder", lambda config: FakeEmbedder())
    await news_main.run_once(None, dsn)
    repo = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    try:
        assert len(await _links(repo)) == 1
    finally:
        await repo.close()


@pytest.mark.db
async def test_search_items_por_obra(repo):
    """6.12: casamento tolerante (acento, pontuação, palavra inteira), só classificados, ordenado."""
    from dataclasses import replace

    now = datetime.now(UTC)
    ids = []
    for title, franchise, prio in [
        ("Silksong: patch 1.1", "Hollow Knight: Silksong", 0.4),
        ("Trailer novo", "Hollow Knight: Silksong", 0.9),
        ("Pokémon Z-A ganha data", "Pokémon", 0.5),
        ("Silksongs falsos", None, 1.0),
    ]:
        it = NewsItem(title=title, franchise=franchise, first_seen=now)
        iid = await repo.add_item(it, vector(title), [])
        await repo.update_item(replace(it, id=iid, kind="anuncio", priority=prio))
        ids.append(iid)
    await repo.add_item(NewsItem(title="Silksong sem classificar", first_seen=now), vector("x"), [])
    got = await repo.search_items(franchise="silksong", limit=5)
    assert [i.id for i in got] == [ids[1], ids[0]]
    assert [i.id for i in await repo.search_items(franchise="POKEMON")] == [ids[2]]
    assert len(await repo.search_items(limit=10)) == 4
