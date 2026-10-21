"""PWA em ``/app`` (P1.1): monta pela ``criar_app``, ``/app/`` 200, ``no-cache`` no ``sw.js``,
manifest com o tipo certo e meta de tamanho (≤ 80 KB gzip sem sprites, ≤ 40 KB por sprite). Sem
banco (``DbFora``) e sem rede (ASGI em memória)."""

from __future__ import annotations

import gzip
import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import psycopg
import pytest

from ayanami.api.app import criar_app
from ayanami.config import de_dict
from ayanami.pwa_estatico import PWA_DIR
from ayanami.relogio import RelogioFalso

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _DbFora:
    @contextmanager
    def connection(self):
        raise psycopg.OperationalError("banco falso fora do ar")
        yield  # pragma: no cover


def _app():
    cfg = de_dict({"geral": {"url_base": "https://ayanami.exemplo.ts.net"}})
    return criar_app(cfg, _DbFora(), RelogioFalso())


def _cliente(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("100.64.0.1", 40000)),
                             base_url="http://ayanami.test")


async def test_app_serve_o_pwa():
    app = _app()
    assert app.state.pwa_montado is True
    async with _cliente(app) as c:
        r = await c.get("/app/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert 'id="faixa"' in r.text and 'src="app.js"' in r.text
        raiz = await c.get("/app")
        assert raiz.status_code in (307, 308) and raiz.headers["location"].endswith("/app/")
        sw = await c.get("/app/sw.js")
        assert sw.status_code == 200 and sw.headers["cache-control"] == "no-cache"
        assert "javascript" in sw.headers["content-type"]
        m = await c.get("/app/manifest.webmanifest")
        assert m.headers["content-type"].startswith("application/manifest+json")
        assert m.json()["start_url"] == "/app/#/conversa"
        js = await c.get("/app/app.js")
        assert "cache-control" not in js.headers or js.headers["cache-control"] != "no-cache"
        assert (await c.get("/app/telas/tv.js")).status_code == 200
        assert (await c.get("/app/nao-existe.js")).status_code == 404


def test_meta_de_tamanho():
    sprites = sorted((PWA_DIR / "rosto").glob("*.webp"))
    assert [p.stem for p in sprites] == ["dormindo", "falando", "ouvindo", "pensando"]
    assert all(p.stat().st_size <= 40 * 1024 for p in sprites)
    total = sum(len(gzip.compress(p.read_bytes(), 9)) for p in PWA_DIR.rglob("*")
                if p.is_file() and p.parent.name != "rosto")
    assert total <= 80 * 1024, total


def test_stubs_tem_dono():
    for p in [*sorted((PWA_DIR / "telas").glob("*.js")), PWA_DIR / "gravador.js"]:
        texto = p.read_text(encoding="utf-8")
        assert "dono: p1." in texto.lower() and "export function montar(el, ctx)" in texto, p.name


def test_manifest_valido():
    m = json.loads((PWA_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["display"] == "standalone" and m["scope"] == "/app/"
    for icone in m["icons"]:
        assert (Path(PWA_DIR) / icone["src"]).is_file(), icone["src"]
