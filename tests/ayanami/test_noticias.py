"""``noticias.coletar`` e ``progresso.atualizar`` (Y3.2; spec §5.1). Sem rede nem LLM: a coleta,
o embedder e a pontuação do ``magi-news`` são falsos; o banco é uma base nova no
``ayanami-pg-teste``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import psycopg
import pytest

from ayanami.config import Noticias, de_dict
from ayanami.deps import Deps
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers import noticias
from magi.common.contracts import NewsRaw, NewsSource
from magi.news import __main__ as news
from magi.news import progress as news_progress

URL = "https://ayanami.exemplo.ts.net"
DIM = 768


class DbConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


def _cfg(**noticias_kw):
    return de_dict({"geral": {"url_base": URL}, "noticias": {"dim": DIM, **noticias_kw}})


# --------------------------------------------------------------------------- config (sem banco)


def test_montar_config_fontes_timeout_e_embedder():
    padrao = noticias._nomes_padrao()
    assert len(padrao) >= 2
    n = Noticias(dim=DIM, fontes=(padrao[0], "inexistente"), timeout_s=12.0,
                 embedder={"provider": "gemini", "model": "emb-1", "free_tier": True,
                           "keys": ["gemini_free"]})
    cfg = noticias.montar_config(n)
    from magi.news.sources import load_sources

    assert [s.name for s in load_sources(cfg)] == [padrao[0]]
    assert cfg.raw["news"]["timeout_s"] == 12.0
    p = cfg.provider_for("news")
    assert (p.name, p.free_tier, p.keys) == ("gemini", True, ("gemini_free",))
    assert cfg.task("news").model == "emb-1"


def test_montar_config_sem_nada_usa_padroes():
    cfg = noticias.montar_config(Noticias())
    assert cfg.tasks == {} and cfg.raw == {"news": {}}


async def test_desligado_nao_coleta(monkeypatch):
    async def nunca(*a, **k):  # pragma: no cover
        raise AssertionError("não devia coletar")

    monkeypatch.setattr(news, "run_once", nunca)
    deps = Deps(db=None, cfg=_cfg(ligado=False), relogio=RelogioFalso())
    r = await noticias.coletar(deps, SimpleNamespace(), timestamp=0)
    assert r["dados"] == {"ligado": False}


# --------------------------------------------------------------------------- com banco


@pytest.fixture
def base(pg_nova_base: Callable[[str], str]) -> str:
    dsn = pg_nova_base("ayanami_noticias")
    with psycopg.connect(dsn) as conn:
        migrar(conn, dim=DIM)
    return dsn


class _Relatorio:
    def summary(self) -> str:
        return "falso"


class EmbedderFalso:
    """Mesmo vetor para cruas com a mesma 1ª palavra do título (agrupa por tema)."""

    name = "falso"
    dimensions = DIM

    def __init__(self) -> None:
        self.temas: dict[str, int] = {}
        self.pessoal: list[bool] = []

    async def embed(self, texts, *, personal):
        self.pessoal.append(personal)
        out = []
        for t in texts:
            i = self.temas.setdefault(t.split()[0], len(self.temas))
            v = [0.0] * DIM
            v[i] = 1.0
            out.append(v)
        return out


def _falsos(monkeypatch, cruas: list[tuple[str, str, str]]):
    """``cruas`` = (fonte, url, título); a fonte ``a``/``b`` tem confiança 3."""
    chamadas = SimpleNamespace(coleta=0, dsn=None, embedder=EmbedderFalso())

    async def coleta(repo, sources, http, *, config=None, timeout_s=None):
        chamadas.coleta += 1
        ids = {}
        for nome in ("a", "b"):
            ids[nome] = await repo.upsert_source(NewsSource(nome, "rss", f"https://{nome}.test/feed", 3))
        for fonte, url, titulo in cruas:
            await repo.add_raw(NewsRaw(ids[fonte], url, titulo, "corpo " + titulo))
        return _Relatorio()

    async def pontua(repo, now):
        await repo.conn.execute(
            "UPDATE news_items SET priority = CASE WHEN title LIKE 'BOMBA%%' THEN 0.95 ELSE 0.5 END,"
            " level = CASE WHEN title LIKE 'BOMBA%%' THEN 'bomba' ELSE 'normal' END WHERE level IS NULL"
        )
        return _Relatorio()

    async def sem_progresso(*a, **k):
        return None

    def http_falso(**kw):
        def recusa(req):  # pragma: no cover
            raise AssertionError(f"rede real pedida: {req.url}")

        return httpx.AsyncClient(transport=httpx.MockTransport(recusa))

    monkeypatch.setattr(news, "load_sources", lambda config: [])
    monkeypatch.setattr(news, "collect_all", coleta)
    monkeypatch.setattr(news, "make_http_client", http_falso)
    monkeypatch.setattr(news, "update_if_due", sem_progresso)
    monkeypatch.setattr(news, "make_embedder", lambda config: chamadas.embedder)
    monkeypatch.setattr(news, "make_classifier", lambda config: None)
    monkeypatch.setattr(news, "score_pending", pontua)
    return chamadas


def _deps(base: str, **kw) -> Deps:
    return Deps(db=DbConexao(base), cfg=_cfg(**kw), relogio=RelogioFalso(), extras={"dsn": base})


@pytest.mark.pg
async def test_coleta_grava_itens_e_so_a_bomba_vira_evento(base, monkeypatch):
    f = _falsos(monkeypatch, [
        ("a", "https://a.test/1", "BOMBA anúncio grande"),
        ("b", "https://b.test/1", "BOMBA anúncio grande (outra fonte)"),
        ("a", "https://a.test/2", "comum notinha"),
    ])
    deps = _deps(base)
    r = await noticias.coletar(deps, SimpleNamespace(), timestamp=0)
    assert f.coleta == 1 and f.embedder.pessoal == [False]
    with psycopg.connect(base) as conn:
        itens = conn.execute("SELECT uid::text, title, sources, level FROM news_items ORDER BY id").fetchall()
        eventos = conn.execute("SELECT tipo, titulo, resumo, ref FROM eventos").fetchall()
    assert [(t, s, lv) for _, t, s, lv in itens] == [
        ("BOMBA anúncio grande", 2, "bomba"), ("comum notinha", 1, "normal")]
    uid_bomba = itens[0][0]
    assert eventos == [("noticia_bomba", "Notícia bomba: BOMBA anúncio grande",
                        "corpo BOMBA anúncio grande", f"noticia:{uid_bomba}")]
    assert r["dados"]["bombas"] == [uid_bomba]

    # 2ª coleta sem nada novo: a mesma bomba não gera outro evento
    f2 = _falsos(monkeypatch, [])
    r2 = await noticias.coletar(deps, SimpleNamespace(), timestamp=0)
    assert f2.coleta == 1 and r2["dados"]["bombas"] == []
    with psycopg.connect(base) as conn:
        assert conn.execute("SELECT count(*) FROM eventos").fetchone()[0] == 1


@pytest.mark.pg
async def test_bomba_com_spoiler_nao_revela_e_obra_largada_nao_avisa(base, monkeypatch):
    _falsos(monkeypatch, [
        ("a", "https://a.test/1", "BOMBA final revelado"),
        ("b", "https://b.test/1", "BOMBA final revelado!"),
        ("a", "https://a.test/2", "BOMBAX largada"),
        ("b", "https://b.test/2", "BOMBAX largada!"),
    ])
    pontua_original = news.score_pending

    async def pontua(repo, now):
        await pontua_original(repo, now)
        await repo.conn.execute(
            "UPDATE news_items SET franchise = 'Obra', spoiler = '{\"has\": true, \"of\": \"Obra\"}'"
            " WHERE title LIKE 'BOMBA final%%'")
        await repo.conn.execute("UPDATE news_items SET franchise = 'Velha' WHERE title LIKE 'BOMBAX%%'")
        return _Relatorio()

    monkeypatch.setattr(news, "score_pending", pontua)
    with psycopg.connect(base) as conn:
        conn.execute("INSERT INTO franchise_prefs (franchise, dropped) VALUES ('Velha', true)")
    await noticias.coletar(_deps(base), SimpleNamespace(), timestamp=0)
    with psycopg.connect(base) as conn:
        eventos = conn.execute("SELECT titulo, resumo FROM eventos").fetchall()
    assert eventos == [("Notícia bomba: Tem notícia de Obra com spoiler", "")]


@pytest.mark.pg
async def test_dimensao_diferente_do_pc_recusa_sem_coletar(base, monkeypatch):
    f = _falsos(monkeypatch, [])
    with pytest.raises(noticias.DimensaoErrada):
        await noticias.coletar(_deps(base, dim=1536), SimpleNamespace(), timestamp=0)
    assert f.coleta == 0


@pytest.mark.pg
async def test_dsn_do_magi_pg_recusado(base, monkeypatch):
    from ayanami.db import DbError

    _falsos(monkeypatch, [])
    deps = _deps(base)
    deps.extras["dsn"] = "postgresql://magi@127.0.0.1:54329/magi"
    with pytest.raises(DbError):
        await noticias.coletar(deps, SimpleNamespace(), timestamp=0)


@pytest.mark.pg
async def test_progresso_sem_llm(base, monkeypatch):
    vistos = []

    async def due(repo, http, sources, settings, now):
        vistos.append(now)
        return None

    def proibido(*a, **k):  # pragma: no cover
        raise AssertionError("progresso não usa LLM")

    monkeypatch.setattr(news_progress, "update_if_due", due)
    monkeypatch.setattr(news, "make_embedder", proibido)
    monkeypatch.setattr(news, "make_classifier", proibido)
    monkeypatch.setattr("magi.news.sources.make_http_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(proibido)))
    deps = _deps(base)
    r = await noticias.progresso(deps, SimpleNamespace(), timestamp=0)
    assert vistos == [deps.relogio.agora()]
    assert "nada a fazer" in r["texto"]
