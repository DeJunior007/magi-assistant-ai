"""Y5.1: servidor MCP em ``/mcp/`` (CA-Y26, CA-Y27, spec §8).

Cliente MCP da própria lib (``mcp.Client`` + ``streamable_http_client`` sobre ``httpx2``) contra o
ASGI em memória, com o lifespan da app aberto à mão (o ``ASGITransport`` não roda lifespan). Banco
``pg`` no ``ayanami-pg-teste`` (base nova por teste); a casa é um canal falso no hub; relógio manual.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import procrastinate
import psycopg
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from procrastinate import testing

from ayanami import confirmacoes as conf_mod
from ayanami import fila
from ayanami.api.app import criar_app
from ayanami.api.auth import criar_dispositivo
from ayanami.api.casa import servicos
from ayanami.config import de_dict
from ayanami.hub import hub_de
from ayanami.mcp_server import hosts_permitidos
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
URL_MCP = f"{URL_BASE}/mcp/"


class DbPorConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


class RelogioManual:
    """``dormir`` só volta quando o teste avança o tempo."""

    def __init__(self) -> None:
        self._agora = datetime(2026, 10, 13, 21, 0, tzinfo=UTC)
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


class CasaFalsa:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.no: Any = None
        self.acoes: list[Envelope] = []

    async def enviar(self, texto: str) -> None:
        env = decode(texto)
        if env.t is Tipo.ACAO:
            self.acoes.append(env)
            r = responder(env, Tipo.ACAO_OK, AcaoOk(AcaoResultado(ok=True)), "casa-sala")
            asyncio.get_running_loop().create_task(self.hub.receber(self.no, encode(r)))

    async def fechar(self, codigo: int) -> None:
        pass


@pytest.fixture
def db(pg_nova_base) -> DbPorConexao:
    dsn = pg_nova_base("ayanami_mcp")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbPorConexao(dsn)


@pytest.fixture
def relogio() -> RelogioManual:
    return RelogioManual()


@pytest.fixture
def app_fila() -> procrastinate.App:
    return fila.montar(None, testing.InMemoryConnector(), periodicas=False)


@pytest.fixture
def fazer(db, relogio, app_fila):
    def criar(escopos: list[str] | None = None, memoria_ler: bool = False):
        mcp_cfg: dict[str, Any] = {"memoria_ler": memoria_ler}
        if escopos is not None:
            mcp_cfg["escopos"] = escopos
        cfg = de_dict({"geral": {"url_base": URL_BASE}, "mcp": mcp_cfg})
        app = criar_app(cfg, db, relogio)
        app.state.ctx.extras["fila"] = app_fila
        return app

    return criar


@pytest.fixture
def token(db):
    def criar(nome: str, escopos: list[str], tipo: str = "mcp") -> str:
        with db.connection() as conn:
            tok, _ = criar_dispositivo(conn, nome, tipo, escopos)
        return tok

    return criar


@asynccontextmanager
async def sessao(app: Any, tok: str):
    transporte = httpx2.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {tok}"}
    async with httpx2.AsyncClient(transport=transporte, headers=headers, timeout=10) as http:
        async with Client(streamable_http_client(URL_MCP, http_client=http)) as cli:
            yield cli


@asynccontextmanager
async def vivo(app: Any):
    async with app.router.lifespan_context(app):
        yield


def dados(res: Any) -> Any:
    sc = res.structured_content
    if isinstance(sc, dict) and set(sc) == {"result"}:
        return sc["result"]
    return sc


def texto(res: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in res.content)


def auditoria(db: DbPorConexao, alvo: str | None = None) -> list[tuple[str, bool, str]]:
    with db.connection() as conn:
        rs = conn.execute("SELECT alvo, ok, resumo FROM auditoria WHERE tipo = 'mcp' ORDER BY id").fetchall()
    return [tuple(r) for r in rs if alvo is None or r[0] == alvo]


async def http_cru(app: Any, tok: str | None, host: str = "ayanami.exemplo.ts.net") -> int:
    corpo = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}}
    headers = {"Accept": "application/json, text/event-stream", "Host": host}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), timeout=10) as http:
        r = await http.post(f"http://{host}/mcp/", json=corpo, headers=headers)
    return r.status_code


# --------------------------------------------------------------------------- CA-Y26


async def test_ca_y26_sete_tools_escopo_e_tipo(fazer, token, db):
    app = fazer()  # padrão D13a: ["ler", "tarefas"]
    so_ler = token("claude-code", ["ler"])
    pc = token("pc-pedro", ["ler", "tarefas"], tipo="pc")
    async with vivo(app):
        async with sessao(app, so_ler) as cli:
            nomes = sorted(t.name for t in (await cli.list_tools()).tools)
            res = await cli.call_tool("tarefa_criar", {"tipo": "pesquisa", "titulo": "x", "pedido": "y"})
            est = await cli.call_tool("estado", {})
        assert await http_cru(app, pc) == 401
        assert await http_cru(app, None) == 401
    assert nomes == sorted(["noticias_buscar", "noticias_ultimas", "tarefas_listar", "tarefa_ver",
                            "estado", "tarefa_criar", "tarefa_cancelar"])
    assert res.is_error and "escopo: falta 'tarefas'" in texto(res)
    assert not est.is_error and dados(est)["pc_online"] is False and dados(est)["fila"] == {}
    linhas = auditoria(db)
    assert [(a, ok) for a, ok, _ in linhas] == [("tarefa_criar", False), ("estado", True)]
    assert "pedido=1c" in linhas[0][2]  # só o tamanho do texto livre


async def test_tv_acao_so_com_casa_ligado(fazer, token):
    tok = token("claude-code", ["ler", "tarefas", "casa"])
    for escopos, tem in ((["ler", "tarefas"], False), (["ler", "casa"], True)):
        app = fazer(escopos)
        async with vivo(app), sessao(app, tok) as cli:
            nomes = {t.name for t in (await cli.list_tools()).tools}
        assert ("tv_acao" in nomes) is tem
        assert "memoria_gravar" not in nomes and "memoria_buscar" not in nomes
        assert ("tarefa_criar" in nomes) is ("tarefas" in escopos)


async def test_sem_ler_403_e_host_estranho_421(fazer, token):
    app = fazer()
    sem_ler = token("so-tarefas", ["tarefas"])
    com_ler = token("claude-code", ["ler"])
    async with vivo(app):
        assert await http_cru(app, sem_ler) == 403
        assert await http_cru(app, com_ler, host="malvado.exemplo.com") == 421
        assert await http_cru(app, com_ler, host="ayanami.dekasis.com.br") == 200


def test_hosts_permitidos():
    hosts, origens = hosts_permitidos(URL_BASE)
    assert {"ayanami.exemplo.ts.net", "ayanami.dekasis.com.br", "127.0.0.1", "127.0.0.1:*"} <= set(hosts)
    assert "https://ayanami.exemplo.ts.net" in origens


async def test_revogado_recusado(fazer, token, db):
    app = fazer()
    tok = token("claude-code", ["ler"])
    app.state.ctx.auth.revogar("claude-code")
    async with vivo(app):
        assert await http_cru(app, tok) == 401


# --------------------------------------------------------------------------- tarefas


async def test_tarefas_criar_idempotente_listar_ver_cancelar(fazer, token, app_fila, db):
    app = fazer()
    tok = token("claude-code", ["ler", "tarefas"])
    args = {"tipo": "pesquisa", "titulo": "PR do Pedro", "pedido": "segredo pessoal longo", "chave": "k1"}
    async with vivo(app), sessao(app, tok) as cli:
        a = dados(await cli.call_tool("tarefa_criar", args))
        b = dados(await cli.call_tool("tarefa_criar", args))
        ruim = await cli.call_tool("tarefa_criar", {**args, "tipo": "stt"})
        lista = dados(await cli.call_tool("tarefas_listar", {"estado": "na_fila"}))
        ver = dados(await cli.call_tool("tarefa_ver", {"id": a["id"]}))
        nada = await cli.call_tool("tarefa_ver", {"id": "00000000-0000-0000-0000-000000000000"})
        res = await cli.read_resource(f"ayanami://tarefas/{a['id']}")
        canc = dados(await cli.call_tool("tarefa_cancelar", {"id": a["id"]}))
    assert a["id"] == b["id"] and a["estado"] == "na_fila" and len(app_fila.connector.jobs) == 1
    assert ruim.is_error
    assert [t["id"] for t in lista] == [a["id"]] and "params" not in lista[0]
    assert ver["titulo"] == "PR do Pedro" and nada.is_error
    assert json.loads(res.contents[0].text)["id"] == a["id"]
    assert canc == {"estado": "cancelada"}
    assert all("segredo" not in r for _, _, r in auditoria(db))


# --------------------------------------------------------------------------- notícias


def _noticias(db: DbPorConexao, agora: datetime) -> None:
    with db.connection() as conn:
        src = conn.execute("INSERT INTO news_sources (name, kind, url) VALUES ('s','rss','https://s/f')"
                           " RETURNING id").fetchone()[0]
        for i, (titulo, resumo, spoiler, url) in enumerate([
            ("Frieren: temporada 3 anunciada", "Madhouse confirma.", None, "https://s/frieren-t3"),
            ("Frieren: Himmel volta no final", "Detalhe do final revelado.",
             {"has": True, "of": "final", "safe_title": "Frieren: novidade do episódio final", "size": 0.9},
             "https://s/frieren-himmel-volta"),
            ("Frieren: arte nova", "Pôster.", {"has": False, "safe_title": "Frieren: arte nova"},
             "https://s/frieren-arte"),
        ]):
            item = conn.execute(
                "INSERT INTO news_items (title, summary, franchise, spoiler, first_seen)"
                " VALUES (%s, %s, 'Frieren', %s::jsonb, %s) RETURNING id",
                (titulo, resumo, json.dumps(spoiler) if spoiler else None, agora - timedelta(hours=i)),
            ).fetchone()[0]
            raw = conn.execute("INSERT INTO news_raw (source_id, url, title, body) VALUES (%s,%s,%s,%s)"
                               " RETURNING id", (src, url, titulo, resumo)).fetchone()[0]
            conn.execute("INSERT INTO news_item_sources VALUES (%s, %s)", (item, raw))


async def test_noticias_nunca_revelam_spoiler(fazer, token, db, relogio):
    _noticias(db, relogio.agora())
    app = fazer()
    tok = token("claude-code", ["ler"])
    async with vivo(app), sessao(app, tok) as cli:
        busca = dados(await cli.call_tool("noticias_buscar", {"consulta": "frieren"}))
        himmel = dados(await cli.call_tool("noticias_buscar", {"consulta": "Himmel"}))
        ultimas = dados(await cli.call_tool("noticias_ultimas", {"limite": 5}))
        uid = next(x["uid"] for x in ultimas if x["spoiler"])
        res = await cli.read_resource(f"ayanami://noticias/{uid}")
        longa = await cli.call_tool("noticias_buscar", {"consulta": "x" * 201})
    assert len(busca) == 3 and himmel == []  # o texto do spoiler nem casa a busca
    tudo = json.dumps([busca, ultimas, res.contents[0].text], ensure_ascii=False)
    assert "Himmel" not in tudo and "final revelado" not in tudo and "himmel-volta" not in tudo
    sp = next(x for x in ultimas if x["spoiler"])
    assert sp["titulo"] == "Frieren: novidade do episódio final" and sp["resumo"] is None
    assert ultimas[0]["fontes"] == ["https://s/frieren-t3"]
    assert longa.is_error


# --------------------------------------------------------------------------- CA-Y27


async def _com_casa(app: Any) -> CasaFalsa:
    ctx = app.state.ctx
    hub = hub_de(ctx)
    with ctx.db.connection() as conn:
        tok, _ = criar_dispositivo(conn, "casa-sala", "casa", None)
    casa = CasaFalsa(hub)
    casa.no = await hub.registrar(ctx.auth.verificar(tok), casa)
    tvs = (TvInfo(id="sala", nome="Sala", driver="samsung", padrao=True),)
    ola = Envelope(t=Tipo.OLA, corpo=Ola(tipo=TipoDispositivo.CASA, versao="0.1", tvs=tvs),
                   de="casa-sala", para="ayanami")
    await hub.receber(casa.no, encode(ola))
    return casa


async def test_ca_y27_desligar_pede_confirmacao(fazer, token, db, relogio):
    app = fazer(["ler", "casa"])
    ctx = app.state.ctx
    tok = token("claude-code", ["ler", "casa"])
    async with vivo(app):
        casa = await _com_casa(app)
        hub, conf = servicos(ctx)
        async with sessao(app, tok) as cli:
            r1 = dados(await cli.call_tool("tv_acao", {"intent": "tv.power_off", "tv": "sala"}))
            assert casa.acoes == []
            c1 = conf_mod.obter(db, r1["confirmacao"])
            assert c1 is not None and c1.expira == relogio.agora() + timedelta(seconds=120)
            assert r1["expira_em"].endswith("Z")
            # aceita em 119 s → a ação sai com confirmed=True
            relogio.avancar(119)
            await hub.marcar_visto(casa.no)
            await conf.responder(r1["confirmacao"], True)
            assert len(casa.acoes) == 1 and casa.acoes[0].corpo.pedido.confirmed is True
            assert casa.acoes[0].corpo.pedido.intent == "tv.power_off"
            # sem resposta em 120 s → expira, nenhuma ação
            r2 = dados(await cli.call_tool("tv_acao", {"intent": "tv.power_off", "tv": "sala"}))
            relogio.avancar(120)
            await hub.marcar_visto(casa.no)
            with pytest.raises(conf_mod.Expirada):
                await conf.responder(r2["confirmacao"], True)
            assert len(casa.acoes) == 1
            # não perigosa vai direto
            r3 = dados(await cli.call_tool("tv_acao", {"intent": "tv.mute", "tv": "sala"}))
            fora = await cli.call_tool("tv_acao", {"intent": "pc.desligar"})
    assert r3["ok"] is True and len(casa.acoes) == 2 and casa.acoes[1].corpo.pedido.confirmed is False
    assert fora.is_error
    linhas = auditoria(db, "tv_acao")
    assert [ok for _, ok, _ in linhas] == [True, True, True, False]
    assert r1["confirmacao"] in linhas[0][2] and r2["confirmacao"] in linhas[1][2]


async def test_memoria_gravar_pc_offline(fazer, token):
    app = fazer(["ler", "memoria-escrever"], memoria_ler=True)
    tok = token("claude-code", ["ler", "memoria-escrever"])
    async with vivo(app), sessao(app, tok) as cli:
        nomes = {t.name for t in (await cli.list_tools()).tools}
        res = await cli.call_tool("memoria_gravar", {"fato": "o Pedro gosta de café"})
    assert {"memoria_gravar", "memoria_buscar"} <= nomes
    assert res.is_error and "pc_offline" in texto(res)
