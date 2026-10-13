"""App sobe sem PWA (``pwa_ausente``), monta quando há ``pwa_estatico`` + diretório, e o lifespan
entra nos gerenciadores de ``ctx.ciclo`` (gancho da Y5.1). Sem banco."""

from __future__ import annotations

import logging
import sys
import types
from contextlib import asynccontextmanager

import pytest
from starlette.responses import PlainTextResponse

from ayanami.api.app import ROTEADORES

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


async def test_sem_pwa_estatico_sobe_sem_app(fazer_app, db_fora, cliente, caplog, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "ayanami.pwa_estatico", None)  # import falha como ausente
    (tmp_path / "pwa").mkdir()
    with caplog.at_level(logging.INFO, logger="ayanami.api"):
        app = fazer_app(db_fora, pwa_dir=tmp_path / "pwa")
    assert app.state.pwa_montado is False
    assert "pwa_ausente" in caplog.text
    async with cliente(app) as c:
        r = await c.get("/app/")
    assert r.status_code == 404
    assert r.json()["erro"] == "nao_encontrado"


def _modulo_falso(chamadas: list) -> types.ModuleType:
    mod = types.ModuleType("ayanami.pwa_estatico")

    def montar_pwa(app):
        chamadas.append(app)
        app.add_route("/app/", lambda req: PlainTextResponse("pwa"))

    mod.montar_pwa = montar_pwa
    return mod


async def test_com_modulo_e_diretorio_monta(fazer_app, db_fora, cliente, monkeypatch, tmp_path):
    chamadas: list = []
    monkeypatch.setitem(sys.modules, "ayanami.pwa_estatico", _modulo_falso(chamadas))
    (tmp_path / "pwa").mkdir()
    app = fazer_app(db_fora, pwa_dir=tmp_path / "pwa")
    assert app.state.pwa_montado is True and chamadas == [app]
    async with cliente(app) as c:
        assert (await c.get("/app/")).text == "pwa"


def test_sem_diretorio_nao_monta(fazer_app, db_fora, caplog, monkeypatch, tmp_path):
    chamadas: list = []
    monkeypatch.setitem(sys.modules, "ayanami.pwa_estatico", _modulo_falso(chamadas))
    with caplog.at_level(logging.INFO, logger="ayanami.api"):
        app = fazer_app(db_fora, pwa_dir=tmp_path / "nao-existe")
    assert app.state.pwa_montado is False and chamadas == []
    assert "pwa_ausente" in caplog.text


def test_roteadores_tem_dono_e_router():
    import importlib

    for nome in ROTEADORES:
        mod = importlib.import_module(f"ayanami.api.{nome}")
        assert hasattr(mod, "router"), nome
        assert "dono:" in (mod.__doc__ or ""), nome


async def test_lifespan_entra_no_ciclo(fazer_app, db_fora):
    eventos: list[str] = []

    @asynccontextmanager
    async def gerenciador():
        eventos.append("entrou")
        yield
        eventos.append("saiu")

    app = fazer_app(db_fora, pwa_dir=None)
    app.state.ctx.ciclo.append(gerenciador)
    async with app.router.lifespan_context(app):
        assert eventos == ["entrou"]
    assert eventos == ["entrou", "saiu"]



def test_importar_pacote_nao_le_config(monkeypatch):
    import ayanami.api as pacote
    from ayanami.api import app as appmod

    def nao(*a, **k):
        raise AssertionError("não devia criar a app de produção")

    monkeypatch.setattr(appmod, "app_de_producao", nao)
    assert pacote.__name__ == "ayanami.api"
    with pytest.raises(AttributeError):
        pacote.nao_existe  # noqa: B018
