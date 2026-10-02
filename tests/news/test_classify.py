"""Testes da classificação de notícias (tarefa 6.7). Chat falso, sem rede nem chaves. Os testes
``db`` usam um schema temporário."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import ChatReply, NewsItem, QuotaExhausted
from magi.memory import migrate as mig
from magi.news import __main__ as news_main
from magi.news.classify import (
    Classification,
    InvalidEntry,
    build_system_prompt,
    classify_pending,
    parse_entry,
)
from magi.news.repo import PgNewsRepo


def entry(i: int, **kw) -> dict:
    base = {"id": i, "franquia": "Frieren", "tipo": "temporada", "spoiler": False, "spoiler_de": None,
            "tamanho": 0.8, "manchete_segura": f"Manchete {i}"}
    return base | kw


class FakeChat:
    name = "fake"
    model = "fake"
    free_tier = True

    def __init__(self, replies=None, fail_after: int | None = None) -> None:
        self.calls: list[list] = []
        self.replies = replies  # função(itens) -> texto
        self.fail_after = fail_after

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        assert personal is False and json_mode is True
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise QuotaExhausted("cota gratuita acabou")
        self.calls.append(list(messages))
        items = json.loads(messages[-1].content)["itens"]
        text = self.replies(items) if self.replies else json.dumps({"itens": [entry(i["id"]) for i in items]})
        return ChatReply(text=text)


class MemRepo:
    def __init__(self, n: int, feedback=()) -> None:
        self.items = {i: NewsItem(title=f"Notícia {i}", summary="<p>x</p>", id=i) for i in range(1, n + 1)}
        self.feedback = list(feedback)

    async def unclassified(self, limit: int = 50):
        return [i for i in self.items.values() if i.kind is None][:limit]

    async def update_item(self, item):
        self.items[item.id] = item

    async def recent_feedback(self, limit: int = 6):
        return self.feedback[:limit]


# --- validação e prompt ---------------------------------------------------------------------


def test_parse_entry_valida_esquema():
    iid, c = parse_entry(entry(3, tipo="Anúncio", spoiler=True, spoiler_de="Frieren, ep. 10"))
    assert iid == 3 and c.kind == "anuncio" and c.spoiler_of == "Frieren, ep. 10"
    assert parse_entry(entry(1, spoiler_de="x"))[1].spoiler_of is None  # sem spoiler, sem "de quê"
    for bad in (entry(1, tipo="fofoca"), entry(1, tamanho=1.5), entry(1, spoiler="sim"),
                entry(1, manchete_segura=" "), entry(1, id="1"), {"id": 1}, [1]):
        with pytest.raises(InvalidEntry):
            parse_entry(bad)


def test_prompt_sem_retorno_usa_exemplos_fixos():
    p = build_system_prompt()
    assert "manchete_segura" in p and p.count("Entrada:") == 3 and "One Piece" in p


def test_prompt_usa_ate_6_exemplos_do_retorno():
    fb = []
    for n in range(8):
        c = Classification(f"Obra{n}", "trailer", False, None, 0.5, f"Segura {n}")
        fb.append((c.apply(NewsItem(title=f"Original {n}", id=100 + n)), 1))
    p = build_system_prompt(fb)
    assert p.count("Entrada:") == 6 and "One Piece" not in p
    assert '"titulo": "Original 0"' in p and '"manchete_segura": "Segura 5"' in p
    assert "Original 6" not in p


# --- lote ------------------------------------------------------------------------------------


async def test_classifica_em_lotes():
    repo, chat = MemRepo(23), FakeChat()
    rep = await classify_pending(repo, chat)
    assert [len(json.loads(m[-1].content)["itens"]) for m in chat.calls] == [10, 10, 3]
    assert (rep.classified, rep.invalid, rep.quota_exhausted) == (23, 0, False)
    it = repo.items[7]
    assert it.franchise == "Frieren" and it.kind == "temporada"
    assert it.spoiler == {"has": False, "of": None, "safe_title": "Manchete 7", "size": 0.8}
    assert Classification.from_item(it).safe_title == "Manchete 7"
    assert await classify_pending(repo, chat) == type(rep)()  # nada pendente: nenhuma chamada
    assert len(chat.calls) == 3


async def test_exemplos_do_retorno_vao_no_prompt():
    c = Classification("Persona", "data", False, None, 0.6, "Persona 6 tem data")
    repo = MemRepo(2, feedback=[(c.apply(NewsItem(title="P6 date leaked", id=99)), -1)])
    chat = FakeChat()
    await classify_pending(repo, chat)
    system = chat.calls[0][0]
    assert system.role == "system" and "P6 date leaked" in system.content
    assert "Persona 6 tem data" in system.content and "One Piece" not in system.content


async def test_json_invalido_pula_item_sem_travar_lote():
    def replies(items):
        if items[0]["id"] == 1:  # 1º lote: JSON quebrado
            return "{itens: nada"
        good = [entry(i["id"]) for i in items[1:]]
        return json.dumps({"itens": [entry(items[0]["id"], tamanho=7), *good, entry(999)]})

    repo = MemRepo(4)
    rep = await classify_pending(repo, FakeChat(replies), batch_size=2)
    assert (rep.classified, rep.invalid) == (1, 3)
    assert [i.id for i in await repo.unclassified()] == [1, 2, 3]
    assert repo.items[4].kind == "temporada"


async def test_cerca_de_codigo_e_lista_solta():
    repo = MemRepo(1)
    await classify_pending(repo, FakeChat(lambda items: "```json\n" + json.dumps([entry(1)]) + "\n```"))
    assert repo.items[1].kind == "temporada"


async def test_cota_esgotada_adia_sem_erro():
    repo = MemRepo(25)
    rep = await classify_pending(repo, FakeChat(fail_after=1))
    assert (rep.classified, rep.deferred, rep.quota_exhausted) == (10, 15, True)
    assert len(await repo.unclassified()) == 15


def test_sem_tarefa_news_pula_classificacao():
    assert news_main.make_classifier(None) is None


# --- banco -----------------------------------------------------------------------------------


@pytest.fixture
def schema():
    name = f"test_classify_{uuid.uuid4().hex[:10]}"
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


async def _item(repo, title: str) -> int:
    cur = await repo.conn.execute(
        "INSERT INTO news_items (title, summary) VALUES (%s, '') RETURNING id", [title]
    )
    return (await cur.fetchone())[0]


@pytest.mark.db
async def test_banco_classifica_e_usa_retorno(repo):
    ids = [await _item(repo, f"Frieren {n}") for n in range(3)]
    rep = await classify_pending(repo, FakeChat(fail_after=1), batch_size=2)
    assert (rep.classified, rep.deferred) == (2, 1)
    assert [i.id for i in await repo.unclassified()] == ids[2:]
    now = datetime.now(UTC)
    await repo.add_feedback(ids[0], 1, now - timedelta(minutes=5))
    await repo.add_feedback(ids[0], -1, now)
    await repo.add_feedback(ids[2], 1, now)  # ainda não classificado: não vira exemplo
    fb = await repo.recent_feedback()
    assert [(i.id, s) for i, s in fb] == [(ids[0], -1)]
    assert fb[0][0].spoiler["safe_title"] == f"Manchete {ids[0]}"
    chat = FakeChat()
    await classify_pending(repo, chat)
    assert await repo.unclassified() == []
    assert f'"manchete_segura": "Manchete {ids[0]}"' in chat.calls[0][0].content


@pytest.mark.db
async def test_magi_news_classifica_depois_do_agrupamento(schema, monkeypatch):
    async def collect(repo, sources, http, **kw):
        await _item(repo, "Silksong DLC")
        return "relatório"

    monkeypatch.setattr(news_main, "collect_all", collect)
    monkeypatch.setattr(news_main, "make_http_client", lambda: httpx.AsyncClient())
    monkeypatch.setattr(news_main, "make_embedder", lambda config: None)
    monkeypatch.setattr(news_main, "make_classifier", lambda config: FakeChat())
    dsn = f"{mig.dsn_from_env()}?options=-csearch_path%3D{schema},public"
    assert await news_main.run_once(None, dsn, only="rss") == "relatório"
    r = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    try:
        assert await r.unclassified() == []
    finally:
        await r.close()
