"""condessa-celular M1.1: CA-M27 (escopos), CA-M28 (``/v1/app/*``) e ``/saude`` com ``app``/``retrato``
(CA-Y9 estendido). ASGI em memória; banco só no ``ayanami-pg-teste``."""

from __future__ import annotations

import hashlib
import json

import pytest

from ayanami.api.app_android import faixa
from ayanami.api.auth import ESCOPO_DE_ROTA, ESCOPOS_PADRAO, Exigencia
from ayanami.config import ConfigError, de_dict
from tests.ayanami.api.conftest import URL_BASE
from tests.ayanami.api.test_saude import PROIBIDAS, _chaves

pytestmark = pytest.mark.pg

APK = bytes(range(256)) * 4  # 1024 bytes sintéticos
SHA = hashlib.sha256(APK).hexdigest()
ETAG = f'"{SHA}"'


@pytest.fixture
def pasta_app(tmp_path):
    p = tmp_path / "app"
    p.mkdir()
    return p


@pytest.fixture
def cfg(pasta_app):
    return de_dict({"geral": {"url_base": URL_BASE}, "app": {"dir": str(pasta_app)}})


def _publicar(pasta, vc=7, **troca):
    (pasta / f"condessa-{vc}.apk").write_bytes(APK)
    v = {"versionCode": vc, "versionName": "0.1.0", "sha256": SHA, "bytes": len(APK), "minimo": 1,
         "notas": "primeira", "publicado": "2026-10-28T12:00:00Z", "cert_sha256": "ab" * 32}
    v.update(troca)
    (pasta / "versao.json").write_text(json.dumps(v), encoding="utf-8")
    return v


# ------------------------------------------------------------------------------------- config


def test_config_app_dir():
    assert de_dict({"geral": {"url_base": URL_BASE}}).app.dir == "/dados/app"
    with pytest.raises(ConfigError, match="app.dir"):
        de_dict({"geral": {"url_base": URL_BASE}, "app": {"dir": "relativo"}})


# ------------------------------------------------------------------------------------- CA-M27


def test_escopos_novos_na_tabela():
    assert "retrato" in ESCOPOS_PADRAO["celular"] and "retrato-enviar" in ESCOPOS_PADRAO["pc"]
    assert ESCOPO_DE_ROTA[("GET", "/v1/app/versao")] == Exigencia(escopos=("conversa",))
    assert ESCOPO_DE_ROTA[("GET", "/v1/app/apk")] == Exigencia(escopos=("conversa",))
    for r in ("versao", "pacote", "modelos"):
        assert ESCOPO_DE_ROTA[("GET", f"/v1/retrato/{r}")] == Exigencia(escopos=("retrato", "conversa"))
    assert ESCOPO_DE_ROTA[("PUT", "/v1/retrato")] == Exigencia(escopos=("retrato-enviar", "backup"),
                                                               tipos=("pc",))


async def test_celular_antigo_le_retrato_e_put_so_do_pc(app, cliente, novo_token):
    antigo = novo_token("cel-antigo", "celular", ["conversa"])
    cel = novo_token("cel-novo", "celular")
    pc_backup = novo_token("pc-velho", "pc", ["backup"])
    async with cliente(app, antigo) as c:  # passa da autenticação (stub da M1.3 → 501)
        assert (await c.get("/v1/retrato/versao")).status_code not in (401, 403)
    async with cliente(app, cel) as c:
        r = await c.put("/v1/retrato", content=b"x")
        assert r.status_code == 403 and r.json()["erro"] == "tipo_proibido"
    async with cliente(app, pc_backup) as c:
        assert (await c.put("/v1/retrato", content=b"x")).status_code not in (401, 403)


# ------------------------------------------------------------------------------------- CA-M28


async def test_versao_404_200_e_500(app, cliente, novo_token, pasta_app):
    token = novo_token("cel", "celular")
    async with cliente(app, token) as c:
        r = await c.get("/v1/app/versao")
        assert r.status_code == 404 and r.json()["erro"] == "sem_versao"
        v = _publicar(pasta_app)
        r = await c.get("/v1/app/versao")
        assert r.status_code == 200 and r.json() == v
        assert r.headers["cache-control"] == "no-cache"
        _publicar(pasta_app, sha256="0" * 64 + "z")
        r = await c.get("/v1/app/versao")
        assert r.status_code == 500 and r.json()["erro"] == "versao_invalida"
        _publicar(pasta_app, bytes=len(APK) + 1)
        assert (await c.get("/v1/app/versao")).status_code == 500
        _publicar(pasta_app, minimo="1")
        assert (await c.get("/v1/app/versao")).status_code == 500


async def test_apk_inteiro_faixa_416_e_if_range(app, cliente, novo_token, pasta_app, db):
    token = novo_token("cel", "celular")
    async with cliente(app, token) as c:
        assert (await c.get("/v1/app/apk")).json()["erro"] == "sem_versao"
        _publicar(pasta_app)
        r = await c.get("/v1/app/apk")
        assert r.status_code == 200 and r.content == APK
        assert r.headers["content-type"] == "application/vnd.android.package-archive"
        assert r.headers["etag"] == ETAG and r.headers["accept-ranges"] == "bytes"
        assert r.headers["content-disposition"] == 'attachment; filename="condessa-7.apk"'
        r = await c.get("/v1/app/apk", headers={"Range": "bytes=10-19", "If-Range": ETAG})
        assert r.status_code == 206 and r.content == APK[10:20]
        assert r.headers["content-range"] == f"bytes 10-19/{len(APK)}"
        r = await c.get("/v1/app/apk", headers={"Range": "bytes=1000-"})
        assert r.status_code == 206 and r.content == APK[1000:]
        r = await c.get("/v1/app/apk", headers={"Range": "bytes=5000-"})
        assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{len(APK)}"
        r = await c.get("/v1/app/apk", headers={"Range": "bytes=10-19", "If-Range": '"velho"'})
        assert r.status_code == 200 and r.content == APK
    with db.connection() as conn:
        linhas = conn.execute("SELECT resumo FROM auditoria WHERE tipo = 'app'").fetchall()
    assert ("apk baixado: 10 bytes",) in linhas and all("100." not in x for (x,) in linhas)


def test_faixa():
    assert faixa(None, 100) is None
    assert faixa("bytes=0-", 100) == (0, 99)
    assert faixa("bytes=90-200", 100) == (90, 99)
    assert faixa("bytes=-10", 100) == (90, 99)
    for ruim in ("bytes=100-", "bytes=5-4", "bytes=-0", "bytes=-", "bytes=0-1,3-4", "itens=0-1"):
        with pytest.raises(ValueError):
            faixa(ruim, 100)


async def test_limite_de_downloads_por_hora(app, cliente, novo_token, pasta_app, relogio):
    _publicar(pasta_app)
    token = novo_token("cel", "celular")
    async with cliente(app, token) as c:
        for _ in range(6):
            assert (await c.get("/v1/app/apk")).status_code == 200
            # continuação com Range do mesmo download não conta
            r = await c.get("/v1/app/apk", headers={"Range": "bytes=10-", "If-Range": ETAG})
            assert r.status_code == 206
        r = await c.get("/v1/app/apk")
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 60
        # downloads não contam no 60/min: ainda há 60 pedidos gerais livres
        for _ in range(60):
            assert (await c.get("/v1/app/versao")).status_code == 200
        assert (await c.get("/v1/app/versao")).status_code == 429
        relogio.avancar(3600)
        assert (await c.get("/v1/app/apk")).status_code == 200


# ------------------------------------------------------------------------------------- /saude


async def test_saude_com_app_e_retrato(app, cliente, pasta_app, tmp_path):
    app.state.ctx.extras["dados"] = str(tmp_path)
    async with cliente(app) as c:
        j = (await c.get("/saude")).json()
        assert j["app"] == {"versao": None} and j["retrato"] == {"versao": None}
        _publicar(pasta_app, vc=12)
        (tmp_path / "retrato").mkdir()
        (tmp_path / "retrato" / "atual").write_text("abcdef0123456789" * 4 + "\n")
        r = await c.get("/saude")
    j = r.json()
    assert j["app"] == {"versao": 12} and j["retrato"] == {"versao": "abcdef012345"}
    assert not (_chaves(j) & PROIBIDAS) and SHA not in r.text
