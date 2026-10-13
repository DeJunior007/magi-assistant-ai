"""CA-Y6: formato do token, só o sha256 no banco, 401/403 sobre ``ESCOPO_DE_ROTA`` (inclusive
stubs), revogação com cache de 5 s e ganchos; CLI ``ayanami dispositivo``."""

from __future__ import annotations

import io
import re

import psycopg
import pytest

from ayanami.api.auth import (
    ESCOPO_DE_ROTA,
    ESCOPOS_PADRAO,
    TOKEN_RE,
    Exigencia,
    hash_token,
    prefixo_token,
)
from ayanami.dispositivos_cli import cli as cli_dispositivo

pytestmark = pytest.mark.pg


def _caminho(c: str) -> str:
    return re.sub(r"\{[^}]+\}", "01J0000000000000000000000X", c)


async def _pedir(cl, metodo: str, caminho: str):
    return await cl.request(metodo, _caminho(caminho), json={} if metodo in ("POST", "PUT") else None)


def test_rotas_da_app_batem_com_a_tabela():
    import importlib

    from ayanami.api.app import ROTEADORES

    rotas = {
        (m, r.path)
        for nome in ROTEADORES
        for r in importlib.import_module(f"ayanami.api.{nome}").router.routes
        for m in r.methods
        if m != "HEAD"
    }
    assert rotas == set(ESCOPO_DE_ROTA)


async def test_so_o_sha256_vai_ao_banco(db, novo_token):
    token = novo_token("pc-casa", "pc")
    with db.connection() as conn:
        linha = conn.execute("SELECT hash, prefixo, escopos FROM dispositivos").fetchone()
        tudo = conn.execute("SELECT row_to_json(d)::text FROM dispositivos d").fetchone()[0]
    assert linha[0] == hash_token(token) and token not in tudo and token[12:] not in tudo
    assert linha[1] == prefixo_token(token)
    assert tuple(linha[2]) == ESCOPOS_PADRAO["pc"]


_CABECALHOS = [None, "Bearer ayn_pc_" + "A" * 43, "Bearer xyz", "Basic abc", "Bearer "]


@pytest.mark.parametrize("cabecalho", _CABECALHOS)
async def test_401_sem_token_valido(app, cliente, cabecalho):
    headers = {"Authorization": cabecalho} if cabecalho else {}
    async with cliente(app) as c:
        r = await c.get("/v1/feed", headers=headers)
    assert r.status_code == 401
    assert r.json()["erro"] == "nao_autorizado"


_COM_TOKEN = sorted((k, v) for k, v in ESCOPO_DE_ROTA.items() if v is not None and v != Exigencia())


@pytest.fixture
def app_403(fazer_app, db, novo_token):
    return fazer_app(db), novo_token("sem-escopo", "mcp", []), novo_token("celular-todo", "celular",
        ["conversa", "casa", "tarefas", "feed", "backup", "noticias", "custos", "ler"])


@pytest.mark.parametrize(("rota", "exig"), _COM_TOKEN, ids=[f"{m} {c}" for (m, c), _ in _COM_TOKEN])
async def test_403_em_cada_linha_da_tabela(app_403, cliente, rota, exig):
    app, sem_escopo, celular = app_403
    async with cliente(app, sem_escopo) as c:
        r = await _pedir(c, *rota)
    assert r.status_code == 403, r.text
    assert r.json()["erro"] in ("escopo_faltando", "tipo_proibido")
    if exig.tipos:  # celular com todos os escopos ainda é o tipo errado
        async with cliente(app, celular) as c:
            assert (await _pedir(c, *rota)).status_code == 403


@pytest.mark.parametrize(("rota", "exig"), _COM_TOKEN, ids=[f"{m} {c}" for (m, c), _ in _COM_TOKEN])
async def test_escopo_certo_passa_da_autenticacao(fazer_app, db, novo_token, cliente, rota, exig):
    tipo = exig.tipos[0] if exig.tipos else "pc"
    escopos = list(exig.escopos[:1])
    app = fazer_app(db)
    async with cliente(app, novo_token("certo", tipo, escopos)) as c:
        r = await _pedir(c, *rota)
    assert r.status_code not in (401, 403), r.text


async def test_revogar_pelo_proprio_token_vale_na_hora(app, cliente, novo_token):
    revogados = []
    app.state.ctx.auth.ao_revogar.append(revogados.append)
    token = novo_token("celular-pedro", "celular")
    async with cliente(app, token) as c:
        assert (await c.get("/v1/feed")).status_code == 501
        assert (await c.delete("/v1/dispositivo")).status_code == 204
        assert (await c.get("/v1/feed")).status_code == 401
    assert [d.nome for d in revogados] == ["celular-pedro"]
    with app.state.ctx.db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM auditoria WHERE tipo = 'dispositivo'").fetchone()[0] == 1


async def test_revogar_fora_da_api_vale_em_5s(app, cliente, novo_token, relogio, base):
    token = novo_token("pc", "pc")
    async with cliente(app, token) as c:
        assert (await c.get("/v1/feed")).status_code == 501
        saida = io.StringIO()
        assert cli_dispositivo(["--dsn", base, "revogar", "pc"], saida=saida) == 0
        relogio.avancar(4.9)
        assert (await c.get("/v1/feed")).status_code == 501  # ainda no cache
        relogio.avancar(0.2)
        assert (await c.get("/v1/feed")).status_code == 401


def test_revogar_pela_api_avisa_o_gancho_e_limpa_cache(app, novo_token):
    auth = app.state.ctx.auth
    token = novo_token("casa", "casa")
    d = auth.verificar(token)
    assert d is not None and d.escopos == {"casa-executar"}
    vistos = []
    auth.ao_revogar.append(lambda disp: (_ for _ in ()).throw(RuntimeError("gancho quebrado")))
    auth.ao_revogar.append(vistos.append)
    assert auth.revogar("casa").id == d.id
    assert auth.verificar(token) is None and [v.id for v in vistos] == [d.id]
    assert auth.revogar("nao-existe") is None


def test_cli_criar_listar_revogar(base):
    saida = io.StringIO()
    assert cli_dispositivo(["--dsn", base, "criar", "pc-casa", "--tipo", "pc"], saida=saida) == 0
    token = saida.getvalue().split(": ")[-1].strip()
    assert TOKEN_RE.match(token)
    assert cli_dispositivo(["--dsn", base, "criar", "pc-casa", "--tipo", "pc"]) == 1  # nome em uso
    assert cli_dispositivo(["--dsn", base, "criar", "mcp", "--tipo", "mcp", "--escopos", "ler"]) == 0
    lista = io.StringIO()
    assert cli_dispositivo(["--dsn", base, "listar"], saida=lista) == 0
    assert "pc-casa" in lista.getvalue() and token not in lista.getvalue() and "ativo" in lista.getvalue()
    assert cli_dispositivo(["--dsn", base, "revogar", "pc-casa"], saida=io.StringIO()) == 0
    assert cli_dispositivo(["--dsn", base, "revogar", "nao-existe"]) == 1
    with psycopg.connect(base) as conn:
        q = "SELECT revogado IS NOT NULL FROM dispositivos WHERE nome = 'pc-casa'"
        assert conn.execute(q).fetchone()[0]
        assert conn.execute("SELECT escopos FROM dispositivos WHERE nome = 'mcp'").fetchone()[0] == ["ler"]


def test_cli_recusa_magi_pg():
    assert cli_dispositivo(["--dsn", "postgresql://x@127.0.0.1:54329/ayanami", "listar"]) == 1
