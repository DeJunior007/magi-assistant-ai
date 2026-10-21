"""Y5.1: servidor MCP em ``/mcp`` (CA-Y26, CA-Y27; spec §8). Cliente MCP da própria lib sobre o ASGI
em memória (``httpx2.ASGITransport``), banco ``pg`` descartável, casa falsa registrada no hub e
relógio manual (``dormir`` só volta quando o teste avança o tempo)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import psycopg
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from procrastinate import testing

from ayanami import fila
from ayanami.api.app import criar_app
from ayanami.api.auth import criar_dispositivo
from ayanami.config import de_dict
from ayanami.confirmacoes import confirmacoes_de
from ayanami.hub import hub_de
from ayanami.migrar import migrar
from magi.elo.mensagens import (
    AcaoOk,
    AcaoResultado,
    Envelope,
    Ola,
    Tipo,
    TipoDispositivo,
    TvInfo,
    decode,
    encode,
    responder,
)

pytestmark = pytest.mark.pg

URL_BASE = "https://ayanami.exemplo.ts.net"
PADRAO = {"noticias_buscar", "noticias_ultimas", "tarefas_listar", "tarefa_ver", "estado",
          "tarefa_criar", "tarefa_cancelar", "servidor"}


class RelogioManual:
    def __init__(self) -> None:
        self._agora = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)
        self._mono = 1000.0
        self.esperas: list[tuple[float, asyncio.Future[None]]] = []

    def agora(self) -> datetime:
        return self._agora

    def monotonico(self) -> float:
        return self._mono

    async def dormir(self, s: float) -> None:
        item = (self._mono + max(0.0, s), asyncio.get_running_loop().create_future())
        self.esperas.append(item)
        try:
            await item[1]
        finally:
            self.esperas.remove(item)

    def avancar(self, s: float) -> None:
        self._mono += s
        self._agora += timedelta(seconds=s)
        for fim, fut in list(self.esperas):
            if fim <= self._mono + 1e-9 and not fut.done():
                fut.set_result(None)


class DbPorConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


async def ate(cond, limite: float = 3.0) -> None:
    for _ in range(int(limite / 0.005)):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condição não chegou")


@pytest.fixture
def relogio() -> RelogioManual:
    return RelogioManual()


@pytest.fixture
def db(pg_nova_base) -> DbPorConexao:
    dsn = pg_nova_base("ayanami_mcp")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbPorConexao(dsn)


def _token(db: DbPorConexao, nome: str, tipo: str, escopos: list[str] | None = None) -> str:
    with db.connection() as conn:
        token, _ = criar_dispositivo(conn, nome, tipo, escopos)
    return token


def _app(db: DbPorConexao, relogio: RelogioManual, escopos: list[str] | None = None) -> Any:
    geral: dict[str, Any] = {"geral": {"url_base": URL_BASE}}
    if escopos is not None:
        geral["mcp"] = {"escopos": escopos}
    app = criar_app(de_dict(geral), db, relogio)
    app.state.ctx.extras["fila"] = fila.montar(None, testing.InMemoryConnector(), periodicas=False)
    return app


@asynccontextmanager
async def sessao(app: Any, token: str):
    """Cliente MCP da lib contra o ASGI em memória, com o lifespan da app aberto."""
    async with app.router.lifespan_context(app):
        transporte = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transporte, timeout=10,
                                      headers={"Authorization": f"Bearer {token}"}) as http:
            async with Client(streamable_http_client("http://127.0.0.1/mcp/", http_client=http)) as cli:
                yield cli


def _texto(res: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in res.content)


def _dados(res: Any) -> Any:
    assert not res.is_error, _texto(res)
    s = res.structured_content
    return s.get("result", s) if isinstance(s, dict) and set(s) == {"result"} else s


def _auditoria(db: DbPorConexao) -> list[tuple]:
    with db.connection() as conn:
        return conn.execute("SELECT alvo, ok, resumo, dispositivo FROM auditoria WHERE tipo = 'mcp'"
                            " ORDER BY id").fetchall()


async def _status_http(app: Any, token: str) -> int:
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http:
            r = await http.post("http://127.0.0.1/mcp/", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json"},
                content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
    return r.status_code


# --------------------------------------------------------------------------- CA-Y26


async def test_ca_y26_sete_tools_escopo_e_tipo(db, relogio):
    app = _app(db, relogio)  # padrão D13a: ler + tarefas
    so_ler = _token(db, "claude-code", "mcp", ["ler"])
    async with sessao(app, so_ler) as cli:
        nomes = {t.name for t in (await cli.list_tools()).tools}
        assert nomes == PADRAO and len(nomes) == 8  # 7 da CA-Y26 + servidor (Y1.3c)
        r = await cli.call_tool("tarefa_criar", {"tipo": "pesquisa", "titulo": "t", "pedido": "x"})
        assert r.is_error and "escopo: falta 'tarefas'" in _texto(r)
        assert not app.state.ctx.extras["fila"].connector.jobs
    assert ("tarefa_criar", False) in [(a, ok) for a, ok, *_ in _auditoria(db)]
    assert await _status_http(_app(db, relogio), _token(db, "pc", "pc")) == 401
    assert await _status_http(_app(db, relogio), _token(db, "sem-ler", "mcp", ["tarefas"])) == 403
    assert await _status_http(_app(db, relogio), "ayn_mcp_" + "x" * 43) == 401


async def test_tv_acao_so_com_casa_nos_escopos(db, relogio):
    tok = _token(db, "claude-code", "mcp", ["ler", "casa"])
    async with sessao(_app(db, relogio, ["ler"]), tok) as cli:
        nomes = {t.name for t in (await cli.list_tools()).tools}
    assert "tv_acao" not in nomes and "tarefa_criar" not in nomes
    async with sessao(_app(db, relogio, ["ler", "casa", "memoria-escrever"]), tok) as cli:
        nomes = {t.name for t in (await cli.list_tools()).tools}
        r = await cli.call_tool("memoria_gravar", {"fato": "gosta de chá"})
    assert {"tv_acao", "memoria_gravar"} <= nomes and "memoria_buscar" not in nomes
    assert r.is_error and "escopo: falta 'memoria-escrever'" in _texto(r)


async def test_revogado_e_recusado(db, relogio):
    app = _app(db, relogio)
    tok = _token(db, "velho", "mcp", ["ler"])
    app.state.ctx.auth.revogar("velho")
    assert await _status_http(app, tok) == 401


# --------------------------------------------------------------------------- tarefas e estado


async def test_tarefas_criar_ver_listar_cancelar_e_auditoria(db, relogio):
    app = _app(db, relogio)
    tok = _token(db, "claude-desktop", "mcp", ["ler", "tarefas"])
    async with sessao(app, tok) as cli:
        args = {"tipo": "pesquisa", "titulo": "ler o PR", "pedido": "o que mudou no mcp 2.3", "chave": "k1"}
        t1 = _dados(await cli.call_tool("tarefa_criar", args))
        t2 = _dados(await cli.call_tool("tarefa_criar", args))
        assert t1["id"] == t2["id"] and t1["estado"] == "na_fila"  # idempotente
        assert _dados(await cli.call_tool("tarefa_ver", {"id": t1["id"]}))["titulo"] == "ler o PR"
        assert [t["id"] for t in _dados(await cli.call_tool("tarefas_listar", {}))] == [t1["id"]]
        r = await cli.call_tool("tarefa_criar", {"tipo": "stt", "titulo": "x", "pedido": "y"})
        assert r.is_error
        assert (await cli.call_tool("tarefa_ver", {"id": "nao-e-uuid"})).is_error
        assert _dados(await cli.call_tool("tarefa_cancelar", {"id": t1["id"]})) == {"estado": "cancelada"}
        est = _dados(await cli.call_tool("estado", {}))
        assert set(est) == {"pc_online", "casa_online", "tvs", "fila", "ultimo_backup"}
        rec = await cli.read_resource(f"ayanami://tarefas/{t1['id']}")
        assert json.loads(rec.contents[0].text)["estado"] == "cancelada"
    linhas = _auditoria(db)
    alvos = [a for a, *_ in linhas]
    assert alvos.count("tarefa_criar") == 3 and "tarefa_cancelar" in alvos and "estado" in alvos
    assert all(d is not None for *_, d in linhas)
    assert not any("o que mudou" in r for _, _, r, _ in linhas)  # sem texto livre no resumo


# --------------------------------------------------------------------------- notícias


def _noticia(db: DbPorConexao, title: str, summary: str, spoiler: dict | None, quando: datetime) -> str:
    with db.connection() as conn:
        uid = conn.execute(
            "INSERT INTO news_items (title, summary, franchise, spoiler, first_seen)"
            " VALUES (%s, %s, 'frieren', %s::jsonb, %s) RETURNING uid::text",
            (title, summary, json.dumps(spoiler) if spoiler else None, quando)).fetchone()[0]
    return uid


async def test_noticias_nunca_revelam_spoiler(db, relogio):
    agora = relogio.agora()
    _noticia(db, "Frieren temporada 3 anunciada", "Estreia em 2027.", None, agora - timedelta(days=1))
    uid = _noticia(db, "Himmel volta dos mortos no cap 140", "Detalhes do capítulo.",
                   {"has": True, "of": "mangá", "safe_title": "Novidade no mangá de Frieren"},
                   agora - timedelta(hours=2))
    _noticia(db, "Frieren velha", "antiga", None, agora - timedelta(days=30))
    app = _app(db, relogio)
    async with sessao(app, _token(db, "claude-code", "mcp", ["ler"])) as cli:
        assert _dados(await cli.call_tool("noticias_buscar", {"consulta": "Himmel"})) == []
        assert _dados(await cli.call_tool("noticias_buscar", {"consulta": "capítulo"})) == []
        achou = _dados(await cli.call_tool("noticias_buscar", {"consulta": "frieren"}))
        assert [n["titulo"] for n in achou] == ["Novidade no mangá de Frieren",
                                                "Frieren temporada 3 anunciada"]
        assert achou[0]["resumo"] is None
        ult = _dados(await cli.call_tool("noticias_ultimas", {"limite": 5}))
        texto = await cli.read_resource(f"ayanami://noticias/{uid}")
        r = await cli.call_tool("noticias_buscar", {"consulta": "x", "limite": 31})
    assert r.is_error
    tudo = json.dumps(ult) + texto.contents[0].text
    assert "Himmel" not in tudo and "Detalhes" not in tudo and len(ult) == 3


# --------------------------------------------------------------------------- CA-Y27


class CasaFalsa:
    def __init__(self, hub) -> None:
        self.hub = hub
        self.no = None
        self.acoes: list[Envelope] = []

    async def enviar(self, texto: str) -> None:
        env = decode(texto)
        if env.t is Tipo.ACAO:
            self.acoes.append(env)
            r = responder(env, Tipo.ACAO_OK, AcaoOk(AcaoResultado(ok=True)), "casa-sala")
            asyncio.get_running_loop().create_task(self.hub.receber(self.no, encode(r)))

    async def fechar(self, codigo: int) -> None:
        pass


async def test_ca_y27_power_off_confirma_aceita_ou_expira(db, relogio):
    app = _app(db, relogio, ["ler", "casa"])
    ctx = app.state.ctx
    hub = hub_de(ctx)
    casa = CasaFalsa(hub)
    casa.no = await hub.registrar(ctx.auth.verificar(_token(db, "casa-sala", "casa")), casa)
    ola = Envelope(t=Tipo.OLA, corpo=Ola(tipo=TipoDispositivo.CASA, versao="0.1",
                                        tvs=(TvInfo(id="sala", nome="Sala", driver="samsung", padrao=True),)),
                   de="casa-sala", para="ayanami")
    await hub.receber(casa.no, encode(ola))
    tok = _token(db, "claude-code", "mcp", ["ler", "casa"])
    srv = ctx.extras["mcp"]
    async with sessao(app, tok) as cli:
        # 1) aceita em 119 s → acao com confirmed=True
        c1 = _dados(await cli.call_tool("tv_acao", {"tv": "Sala", "intent": "tv.power_off"}))
        assert set(c1) == {"confirmacao", "expira_em"} and casa.acoes == []
        with db.connection() as conn:
            assert conn.execute("SELECT count(*) FROM confirmacoes").fetchone()[0] == 1
        relogio.avancar(119)
        await hub.marcar_visto(casa.no)
        _, res = await confirmacoes_de(ctx).responder(c1["confirmacao"], True)
        assert res["ok"] is True and len(casa.acoes) == 1
        assert casa.acoes[0].corpo.pedido.confirmed is True
        assert casa.acoes[0].corpo.pedido.intent == "tv.power_off"
        # 2) sem resposta em 120 s → expira, sem acao
        c2 = _dados(await cli.call_tool("tv_acao", {"tv": "Sala", "intent": "tv.power_off"}))
        relogio.avancar(120)
        await ate(lambda: not srv.vigias)
        assert len(casa.acoes) == 1
        # 3) ação não perigosa roda direto
        await hub.marcar_visto(casa.no)
        assert _dados(await cli.call_tool("tv_acao", {"tv": "Sala", "intent": "tv.mute"}))["ok"] is True
        r = await cli.call_tool("tv_acao", {"intent": "casa.algo"})
        assert r.is_error
    assert len(casa.acoes) == 2
    linhas = _auditoria(db)
    tv = [(ok, resumo) for a, ok, resumo, _ in linhas if a == "tv_acao"]
    assert [ok for ok, r in tv if "expirada" not in r] == [True, True, True]  # as três chamadas
    assert (False, f"confirmacao {c2['confirmacao']} expirada") in tv
    assert not any(f"confirmacao {c1['confirmacao']} expirada" in r for _, r in tv)
