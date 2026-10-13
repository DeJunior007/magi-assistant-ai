"""Y6.1: ``BudgetNuvem`` (CA-Y21 parte budget), gancho do ``bate`` → ``custos_pc`` e ``/v1/custos``.

Nenhuma chamada paga: os ``Usage`` são registrados à mão. Banco: base nova no ``ayanami-pg-teste``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import psycopg
import pytest

from ayanami.api.app import criar_app
from ayanami.api.auth import Dispositivo, criar_dispositivo
from ayanami.config import de_dict
from ayanami.custos import BudgetNuvem, ao_bate, mes_de
from ayanami.deps import Deps
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from magi.common.contracts import BudgetExceeded, ProviderTask, Usage
from magi.elo.mensagens import Bate, Envelope, Tipo

pytestmark = pytest.mark.pg

AGORA = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
PC = Dispositivo(id=1, nome="pc", tipo="pc", escopos=frozenset({"custos"}))
CASA = Dispositivo(id=2, nome="casa", tipo="casa", escopos=frozenset())


class DbPorConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


@pytest.fixture
def db(pg_nova_base: Callable[[str], str]) -> DbPorConexao:
    dsn = pg_nova_base("ayanami_custos")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbPorConexao(dsn)


@pytest.fixture
def relogio() -> RelogioFalso:
    return RelogioFalso(AGORA)


@pytest.fixture
def budget(db, relogio) -> BudgetNuvem:
    return BudgetNuvem.de_config(db, de_dict({"geral": {"url_base": "https://a.exemplo.ts.net"}}), relogio)


def _uso(usd: float, task: ProviderTask = ProviderTask.AGENT) -> Usage:
    return Usage(provider="openai", task=task, model="gpt-falso", input_units=10, output_units=5, usd=usd)


def _bate(usd: float | None) -> Envelope:
    return Envelope(t=Tipo.BATE, corpo=Bate(seq=1, custos_mes_usd=usd), de="pc", para="ayanami")


def _custos_pc(db) -> list[tuple]:
    with db.connection() as conn:
        return conn.execute("SELECT mes, usd FROM custos_pc ORDER BY mes").fetchall()


@pytest.mark.parametrize(
    ("nuvem", "pc", "bloqueia"),
    [(1.99, 2.00, False), (2.00, None, True), (1.00, 4.00, True), (1.00, 3.99, False)],
)
async def test_ca_y21_sub_teto_e_teto_geral(budget, db, relogio, nuvem, pc, bloqueia):
    await budget.record(_uso(nuvem))
    if pc is not None:
        await ao_bate(db, relogio)(PC, _bate(pc))
    if bloqueia:
        with pytest.raises(BudgetExceeded):
            await budget.ensure_allowed(ProviderTask.AGENT)
    else:
        await budget.ensure_allowed(ProviderTask.AGENT)
    st = await budget.status()
    assert st.spent_usd == pytest.approx(nuvem)
    assert (st.spent_usd >= st.cap_usd) is bloqueia
    # STT/TTS seguem com o teto batido (TV sem LLM no modo nuvem)
    await budget.ensure_allowed(ProviderTask.STT)
    await budget.ensure_allowed(ProviderTask.TTS)


async def test_record_grava_source_nuvem_com_preco_injetado(db, relogio):
    b = BudgetNuvem(db, relogio, preco=lambda u: u.input_units * 0.01)
    await b.record(_uso(0.0))
    await b.record(_uso(0.25))  # usd > 0 do provedor é mantido
    with db.connection() as conn:
        linhas = conn.execute("SELECT source, task, usd, at FROM costs ORDER BY id").fetchall()
    assert [(s, t, u) for s, t, u, _ in linhas] == [
        ("nuvem", "agent", Decimal("0.100000")), ("nuvem", "agent", Decimal("0.250000"))]
    assert linhas[0][3] == AGORA


async def test_mes_civil_de_sao_paulo(budget, db, relogio):
    # 01/10 02:00 UTC = 30/09 23:00 em São Paulo: conta em setembro
    with db.connection() as conn:
        conn.execute("INSERT INTO costs (at, provider, task, usd) VALUES (%s, 'openai', 'agent', 3)",
                     (datetime(2026, 10, 1, 2, 0, tzinfo=UTC),))
        conn.execute("INSERT INTO custos_pc (mes, usd, visto) VALUES ('2026-09-01', 4.5, now())")
    assert (await budget.status()).spent_usd == 0.0
    await budget.ensure_allowed(ProviderTask.AGENT)
    assert mes_de(datetime(2026, 12, 31, 12, tzinfo=UTC)) == (
        datetime(2026, 12, 1).date(), datetime(2027, 1, 1).date())


async def test_ao_bate_so_do_pc_e_valor_valido(db, relogio):
    g = ao_bate(db, relogio)
    assert await g(CASA, _bate(9.0)) is None
    for ruim in (None, -1.0, float("nan"), float("inf")):
        await g(PC, _bate(ruim))
    assert _custos_pc(db) == []
    await g(PC, _bate(1.5))
    await g(PC, _bate(2.25))  # o mesmo mês é atualizado, não duplicado
    assert _custos_pc(db) == [(datetime(2026, 10, 1).date(), Decimal("2.250000"))]


def test_deps_nasce_com_budget_dos_tetos_da_config():
    cfg = de_dict({"geral": {"url_base": "https://a.exemplo.ts.net"},
                   "budget": {"teto_nuvem_usd": 1.0, "teto_geral_usd": 3.0}})
    d = Deps(db=object(), cfg=cfg)  # type: ignore[arg-type]
    assert isinstance(d.budget, BudgetNuvem)
    assert (d.budget.teto_nuvem, d.budget.teto_geral) == (Decimal("1.000000"), Decimal("3.000000"))


# --------------------------------------------------------------------------- /v1/custos


@pytest.fixture
def app(db, relogio):
    return criar_app(de_dict({"geral": {"url_base": "https://a.exemplo.ts.net"}}), db, relogio)


def _token(db, nome: str, tipo: str) -> str:
    with db.connection() as conn:
        token, _ = criar_dispositivo(conn, nome, tipo, None)
    return token


def _cliente(app, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("100.64.0.1", 40000)),
                             base_url="http://ayanami.test", headers={"Authorization": f"Bearer {token}"})


async def test_v1_custos_pagina_por_uid(app, db, budget):
    for i in range(5):
        await budget.record(_uso(0.1 * (i + 1)))
    with db.connection() as conn:  # linha de outra origem não sai
        conn.execute("INSERT INTO costs (provider, task, usd, source) VALUES ('x', 'agent', 1, 'pc')")
    token = _token(db, "pc", "pc")
    async with _cliente(app, token) as c:
        r = await c.get("/v1/custos", params={"n": 2})
        assert r.status_code == 200
        p1 = r.json()["linhas"]
        assert [x["usd"] for x in p1] == [0.1, 0.2]
        assert set(p1[0]) == {"uid", "at", "provider", "task", "model", "input_units", "output_units", "usd"}
        assert p1[0]["at"] == "2026-10-13T15:00:00Z"
        p2 = (await c.get("/v1/custos", params={"desde": p1[-1]["uid"], "n": 2})).json()["linhas"]
        p3 = (await c.get("/v1/custos", params={"desde": p2[-1]["uid"]})).json()["linhas"]
        assert [x["usd"] for x in p2 + p3] == [0.3, 0.4, 0.5]
        fim = (await c.get("/v1/custos", params={"desde": p3[-1]["uid"]})).json()["linhas"]
        assert fim == []
        # uid desconhecido recomeça do início (o PC não duplica por origem_uid)
        assert len((await c.get("/v1/custos", params={"desde": str(uuid4())})).json()["linhas"]) == 5
        assert (await c.get("/v1/custos", params={"desde": "nao-e-uid"})).status_code == 422
    async with _cliente(app, _token(db, "casa", "casa")) as c:
        assert (await c.get("/v1/custos")).status_code == 403


async def test_lifespan_liga_o_gancho_do_bate_uma_vez(app):
    async with app.router.lifespan_context(app):
        hub = app.state.ctx.extras["hub"]
        assert len(hub._ganchos_receber[Tipo.BATE]) == 1
    from ayanami.api.custos import ligar_ctx

    ligar_ctx(app.state.ctx)
    assert len(app.state.ctx.extras["hub"]._ganchos_receber[Tipo.BATE]) == 1
