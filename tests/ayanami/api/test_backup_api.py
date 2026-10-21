"""``PUT /v1/backup/pc`` (Y4.2; CA-Y10 parte backup, spec §2.2/§2.3)."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from procrastinate import testing

from ayanami import fila
from ayanami.api import limites

pytestmark = pytest.mark.pg

MANIFESTO = {
    "data": "2026-10-20",
    "pg_versao": "pg_dump (PostgreSQL) 16.4",
    "tabelas": {"turns": 3, "memories": 2, "costs": None},
}


def _cab(corpo: bytes, data: str = "2026-10-20", sha: str | None = None) -> dict[str, str]:
    return {
        "X-Sha256": sha or hashlib.sha256(corpo).hexdigest(),
        "X-Data": data,
        "X-Manifesto": base64.b64encode(json.dumps(MANIFESTO).encode()).decode(),
        "Content-Type": "application/octet-stream",
    }


@pytest.fixture
def montar(fazer_app, db, tmp_path):
    def fazer():
        app = fazer_app(db)
        app.state.ctx.extras["dados"] = str(tmp_path)
        app.state.ctx.extras["fila"] = fila.montar(None, testing.InMemoryConnector(), periodicas=False)
        return app

    return fazer


def _arquivos(tmp_path):
    return sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())


async def test_recebe_grava_audita_e_defere(montar, cliente, novo_token, db, tmp_path):
    app = montar()
    corpo = b"zstd falso " * 1000
    async with cliente(app, novo_token("pc1", "pc")) as c:
        r = await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))
        assert r.status_code == 201, r.text
        assert r.json() == {"recebido": len(corpo)}
        r2 = await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))
        assert r2.status_code == 409
    assert _arquivos(tmp_path) == [
        "entrada/pc/2026-10-20/magi-2026-10-20.tar.zst",
        "entrada/pc/2026-10-20/manifesto.json",
    ]
    pasta = tmp_path / "entrada/pc/2026-10-20"
    assert (pasta / "magi-2026-10-20.tar.zst").read_bytes() == corpo
    assert json.loads((pasta / "manifesto.json").read_text()) == MANIFESTO
    with db.connection() as conn:
        linha = conn.execute(
            "SELECT origem, data::text, bytes, sha256, manifesto, snapshot FROM backups"
        ).fetchall()
        aud = conn.execute("SELECT tipo, ok FROM auditoria ORDER BY id").fetchall()
    assert linha == [("pc", "2026-10-20", len(corpo), hashlib.sha256(corpo).hexdigest(), MANIFESTO, None)]
    assert aud == [("backup", True), ("backup", False)]
    jobs = list(app.state.ctx.extras["fila"].connector.jobs.values())
    assert [(j["task_name"], j["args"]) for j in jobs] == [("backup.restic", {"data": "2026-10-20"})]


async def test_sha_errado_400_e_nada_em_disco(montar, cliente, novo_token, db, tmp_path):
    app = montar()
    corpo = b"conteudo"
    async with cliente(app, novo_token("pc1", "pc")) as c:
        r = await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo, sha="0" * 64))
    assert r.status_code == 400 and r.json()["erro"] == "sha256_diferente"
    assert _arquivos(tmp_path) == []
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM backups").fetchone()[0] == 0
    assert app.state.ctx.extras["fila"].connector.jobs == {}


async def test_arquivo_sumido_aceita_de_novo(montar, cliente, novo_token, tmp_path):
    app = montar()
    corpo = b"abc"
    async with cliente(app, novo_token("pc1", "pc")) as c:
        assert (await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))).status_code == 201
        (tmp_path / "entrada/pc/2026-10-20/magi-2026-10-20.tar.zst").unlink()
        assert (await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))).status_code == 201


@pytest.mark.parametrize(
    "cab",
    [
        {"X-Sha256": "xyz"},
        {"X-Data": "20/10/2026"},
        {"X-Data": "../../etc"},
        {"X-Manifesto": "nao base64!"},
        {"X-Manifesto": base64.b64encode(b"[1]").decode()},
    ],
)
async def test_cabecalho_invalido_400(montar, cliente, novo_token, tmp_path, cab):
    corpo = b"abc"
    h = _cab(corpo) | cab
    async with cliente(montar(), novo_token("pc1", "pc")) as c:
        r = await c.put("/v1/backup/pc", content=corpo, headers=h)
    assert r.status_code == 400
    assert _arquivos(tmp_path) == []


async def test_escopo_e_token(montar, cliente, novo_token):
    corpo = b"abc"
    app = montar()
    async with cliente(app) as c:
        assert (await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))).status_code == 401
    async with cliente(app, novo_token("cel", "celular")) as c:
        assert (await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))).status_code == 403


async def test_maior_que_2gib_413_sem_arquivo(montar, cliente, novo_token, tmp_path, monkeypatch):
    # limite de 2 GiB encolhido para 1 KiB (mesmo caminho de código: middleware + contagem da rota)
    monkeypatch.setitem(limites.CORPO_POR_ROTA, "/v1/backup/pc", 1024)
    monkeypatch.setattr("ayanami.api.backup.MAX_BYTES", 1024)
    corpo = b"x" * 5000
    app = montar()

    async def pedacos():
        for i in range(0, len(corpo), 500):
            yield corpo[i : i + 500]

    async with cliente(app, novo_token("pc1", "pc")) as c:
        r = await c.put("/v1/backup/pc", content=corpo, headers=_cab(corpo))  # Content-Length
        assert r.status_code == 413
        r = await c.put("/v1/backup/pc", content=pedacos(), headers=_cab(corpo))  # sem Content-Length
        assert r.status_code == 413
    assert _arquivos(tmp_path) == []
    assert app.state.ctx.extras["fila"].connector.jobs == {}


def test_limite_real_da_rota_e_2gib():
    assert limites.CORPO_POR_ROTA["/v1/backup/pc"] == 2 * limites.GIB
    from ayanami.api import backup

    assert backup.MAX_BYTES == 2 * limites.GIB
