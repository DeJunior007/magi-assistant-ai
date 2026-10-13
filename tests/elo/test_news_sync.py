"""``magi-news-sync`` (Y3.3, spec §5.2): CA-Y17 (``pg``) e CA-Y18.

Ayanami falsa por ``httpx.MockTransport`` (sem rede); internet por função injetada; banco só no
``ayanami-pg-teste`` (fixtures da Y0.3 em ``tests/ayanami/conftest.py``, base com as migrações do PC).
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from magi.elo import news_sync as ns
from magi.memory import migrate as pc_migrate

AGORA = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


def _conftest_ayanami() -> Any:
    caminho = Path(__file__).resolve().parents[1] / "ayanami" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_y33_conftest_ayanami", caminho)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cf = _conftest_ayanami()
pg_dsn = _cf.pg_dsn
pg_nova_base = _cf.pg_nova_base


def _config(tmp_path: Path, *, ayanami: bool = True) -> Path:
    p = tmp_path / "config.toml"
    p.write_text('[ayanami]\nurl = "http://ayanami.teste/"\n' if ayanami else "[user]\nname = 'x'\n")
    return p


def _estado(tmp_path: Path, ultimo_ok: datetime | None) -> Path:
    p = tmp_path / "state" / "news_sync.json"
    ns.gravar_estado(p, ns.Estado(cursor="c", ultimo_ok=ultimo_ok))
    return p


# --- CA-Y18: --precisa-local ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("idade", "internet", "esperado"),
    [
        (timedelta(hours=7), True, 0),
        (timedelta(hours=7), False, 1),
        (timedelta(hours=1), True, 1),
        (timedelta(hours=1), False, 1),
    ],
)
def test_precisa_local_ca_y18(tmp_path: Path, idade: timedelta, internet: bool, esperado: int) -> None:
    estado = _estado(tmp_path, AGORA - idade)
    rc = ns.main(
        ["--config", str(_config(tmp_path)), "--precisa-local"],
        internet=lambda: internet,
        agora=lambda: AGORA,
        estado_em=estado,
    )
    assert rc == esperado


def test_precisa_local_nunca_sincronizou_depende_da_internet(tmp_path: Path) -> None:
    estado = tmp_path / "nada.json"
    args = ["--config", str(_config(tmp_path)), "--precisa-local"]
    assert ns.main(args, internet=lambda: True, agora=lambda: AGORA, estado_em=estado) == 0
    assert ns.main(args, internet=lambda: False, agora=lambda: AGORA, estado_em=estado) == 1


def test_sem_ayanami_coleta_local_como_hoje(tmp_path: Path) -> None:
    estado = _estado(tmp_path, AGORA)  # sync recente, mas sem [ayanami] não importa
    nunca: Callable[[], bool] = lambda: pytest.fail("não deve testar internet")  # noqa: E731
    for cfg in (_config(tmp_path, ayanami=False), tmp_path / "nao-existe.toml"):
        rc = ns.main(["--config", str(cfg), "--precisa-local"], internet=nunca, estado_em=estado)
        assert rc == 0


def test_precisa_local_erro_inesperado_coleta_local(tmp_path: Path) -> None:
    ruim = tmp_path / "config.toml"
    ruim.write_text("[ayanami\n")  # TOML inválido
    assert ns.main(["--config", str(ruim), "--precisa-local"], estado_em=tmp_path / "e.json") == 0


def test_internet_por_socket_falso() -> None:
    chamadas: list[tuple[Any, ...]] = []

    class Sock:
        def close(self) -> None:
            pass

    def ok(*a: Any) -> Sock:
        chamadas.append(a)
        return Sock()

    def falha(*a: Any) -> Sock:
        raise OSError("sem rota")

    assert ns.tem_internet(ok) is True
    assert chamadas == [(("1.1.1.1", 443), 3)]
    assert ns.tem_internet(falha) is False


def test_estado_ida_e_volta_e_ilegivel(tmp_path: Path) -> None:
    p = tmp_path / "s" / "news_sync.json"
    ns.gravar_estado(p, ns.Estado(cursor="2026|1", ultimo_ok=AGORA))
    assert json.loads(p.read_text()) == {"cursor": "2026|1", "ultimo_ok": AGORA.isoformat()}
    assert ns.ler_estado(p) == ns.Estado(cursor="2026|1", ultimo_ok=AGORA)
    p.write_text("{lixo")
    assert ns.ler_estado(p) == ns.Estado()


def test_caminho_estado_respeita_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert ns.caminho_estado() == tmp_path / "magi" / "news_sync.json"


# --- sync sem banco: códigos de saída -------------------------------------------------------------


def test_sync_sem_ayanami_nao_faz_nada(tmp_path: Path) -> None:
    rc = ns.main(
        ["--config", str(_config(tmp_path, ayanami=False))],
        token=lambda: pytest.fail("não deve ler o keyring"),
        estado_em=tmp_path / "e.json",
    )
    assert rc == 0
    assert not (tmp_path / "e.json").exists()


def test_sync_sem_token_e_ayanami_fora(tmp_path: Path) -> None:
    rc = ns.main(["--config", str(_config(tmp_path))], token=lambda: None, estado_em=tmp_path / "e.json")
    assert rc == 2


def test_sync_banco_fora_sai_3(tmp_path: Path) -> None:
    rc = ns.main(
        ["--config", str(_config(tmp_path)), "--dsn", "postgresql://x:y@127.0.0.1:9/nada"],
        token=lambda: "ayn_falso",
        estado_em=tmp_path / "e.json",
    )
    assert rc == 3


# --- CA-Y17 (pg) ----------------------------------------------------------------------------------


class AyanamiFalsa:
    """``GET /v1/noticias`` em páginas fixas (cursor = índice) e ``PUT .../preferencias`` gravado."""

    def __init__(self, paginas: list[dict[str, Any]], status: int = 200) -> None:
        self.paginas = paginas
        self.status = status
        self.puts: list[dict[str, Any]] = []
        self.auth: set[str] = set()
        self.desde: list[str | None] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.auth.add(req.headers.get("authorization", ""))
        if self.status != 200:
            return httpx.Response(self.status)
        if req.method == "PUT" and req.url.path == "/v1/noticias/preferencias":
            self.puts.append(json.loads(req.content))
            return httpx.Response(204)
        assert req.method == "GET" and req.url.path == "/v1/noticias"
        assert req.url.params["n"] == "200"
        desde = req.url.params.get("desde")
        self.desde.append(desde)
        i = int(desde) if desde else 0
        pag = dict(self.paginas[i])
        pag["cursor"] = str(i + 1)
        pag["fim"] = i + 1 >= len(self.paginas)
        return httpx.Response(200, json=pag)

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def base(pg_nova_base: Callable[[str], str]) -> str:
    dsn = pg_nova_base("magi_pc_t")
    with psycopg.connect(dsn) as conn:
        pc_migrate.migrate(conn)
    return dsn


def _dim(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        d = ns.dimensao_embedding(conn)
    assert d
    return d


def _paginas(dim: int, uids: list[str], titulo: str = "T") -> list[dict[str, Any]]:
    fonte = {"name": "Fonte", "kind": "rss", "url": "https://fonte.teste/rss", "trust": 2}

    def bruto(n: int) -> dict[str, Any]:
        return {
            "url": f"https://fonte.teste/{n}",
            "fonte_url": fonte["url"],
            "title": f"cru {n}",
            "body": "corpo",
            "published_at": "2026-10-12T10:00:00+00:00",
            "fetched_at": "2026-10-12T11:00:00+00:00",
        }

    def item(n: int, emb: list[float] | None) -> dict[str, Any]:
        return {
            "uid": uids[n],
            "title": f"{titulo} {n}",
            "summary": "resumo",
            "embedding": emb,
            "first_seen": "2026-10-12T11:00:00+00:00",
            "sources": 1,
            "max_trust": 2,
            "franchise": "Frieren",
            "kind": "anime",
            "spoiler": {"ep": 3},
            "priority": 0.5,
            "level": "normal",
            "brutos": [f"https://fonte.teste/{n}"],
        }

    return [
        {"fontes": [fonte], "brutos": [bruto(0), bruto(1)], "itens": [item(0, [0.1] * dim), item(1, None)]},
        # dimensão errada vira NULL; o bruto 1 veio na página anterior
        {"fontes": [], "brutos": [bruto(2)], "itens": [item(2, [0.1] * (dim + 1))]},
    ]


def _rodar(tmp_path: Path, dsn: str, falsa: AyanamiFalsa, estado: Path) -> int:
    return ns.main(
        ["--config", str(_config(tmp_path)), "--dsn", dsn],
        transporte=falsa.transporte(),
        token=lambda: "ayn_falso",
        agora=lambda: AGORA,
        estado_em=estado,
    )


def _contar(dsn: str) -> tuple[int, int, int, int]:
    with psycopg.connect(dsn) as conn:
        return tuple(  # type: ignore[return-value]
            conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # type: ignore[index]
            for t in ("news_sources", "news_raw", "news_items", "news_item_sources")
        )


@pytest.mark.pg
def test_ca_y17_sync_idempotente_preserva_delivered_e_zera_dim_errada(tmp_path: Path, base: str) -> None:
    dim = _dim(base)
    uids = [str(uuid.uuid4()) for _ in range(3)]
    with psycopg.connect(base) as conn:
        conn.execute("INSERT INTO franchise_prefs (franchise, weight) VALUES ('Frieren', 0.8)")
        conn.execute("INSERT INTO progress (franchise, kind, value) VALUES ('Frieren', 'ep', '3')")
    falsa = AyanamiFalsa(_paginas(dim, uids))
    estado = tmp_path / "s1.json"

    assert _rodar(tmp_path, base, falsa, estado) == 0
    assert falsa.desde == [None, "1"]
    assert falsa.auth == {"Bearer ayn_falso"}
    assert _contar(base) == (1, 3, 3, 3)
    assert ns.ler_estado(estado) == ns.Estado(cursor="2", ultimo_ok=AGORA)
    assert falsa.puts and falsa.puts[0]["franchise_prefs"][0]["franchise"] == "Frieren"
    assert falsa.puts[0]["progress"][0]["value"] == "3"

    entregue = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    with psycopg.connect(base) as conn:
        conn.execute("UPDATE news_items SET delivered_at = %s WHERE ayanami_uid = %s", [entregue, uids[0]])

    # 2ª execução do zero (estado novo): mesmos itens, títulos novos.
    falsa2 = AyanamiFalsa(_paginas(dim, uids, titulo="Novo"))
    assert _rodar(tmp_path, base, falsa2, tmp_path / "s2.json") == 0
    assert _contar(base) == (1, 3, 3, 3)
    with psycopg.connect(base) as conn:
        rows = {
            str(u): (t, d, e)
            for u, t, d, e in conn.execute(
                "SELECT ayanami_uid, title, delivered_at, embedding IS NULL FROM news_items"
            ).fetchall()
        }
        src = conn.execute(
            "SELECT count(*) FROM news_raw WHERE source_id = (SELECT id FROM news_sources)"
        ).fetchone()
    assert rows[uids[0]] == ("Novo 0", entregue, False)
    assert rows[uids[1]] == ("Novo 1", None, True)
    assert rows[uids[2]] == ("Novo 2", None, True)  # dimensão errada → NULL
    assert src == (3,)


@pytest.mark.pg
def test_item_local_com_mesma_crua_e_adotado(tmp_path: Path, base: str) -> None:
    dim = _dim(base)
    uids = [str(uuid.uuid4()) for _ in range(3)]
    entregue = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    with psycopg.connect(base) as conn:
        raw = conn.execute(
            "INSERT INTO news_raw (url, title) VALUES ('https://fonte.teste/0', 'local') RETURNING id"
        ).fetchone()
        item = conn.execute(
            "INSERT INTO news_items (title, delivered_at) VALUES ('local', %s) RETURNING id", [entregue]
        ).fetchone()
        assert raw and item
        conn.execute("INSERT INTO news_item_sources VALUES (%s, %s)", [item[0], raw[0]])
    assert _rodar(tmp_path, base, AyanamiFalsa(_paginas(dim, uids)), tmp_path / "s.json") == 0
    assert _contar(base)[2] == 3
    with psycopg.connect(base) as conn:
        row = conn.execute(
            "SELECT id, title, delivered_at FROM news_items WHERE ayanami_uid = %s", [uids[0]]
        ).fetchone()
    assert row == (item[0], "T 0", entregue)


@pytest.mark.pg
def test_ayanami_fora_sai_2_sem_mexer_no_estado(tmp_path: Path, base: str) -> None:
    estado = _estado(tmp_path, AGORA - timedelta(hours=8))
    assert _rodar(tmp_path, base, AyanamiFalsa([], status=503), estado) == 2
    assert ns.ler_estado(estado).ultimo_ok == AGORA - timedelta(hours=8)


# --- credenciais (helper único do PC) -------------------------------------------------------------


def test_token_pc_keyring_primeiro_e_arquivo_de_recaida(tmp_path: Path) -> None:
    from magi.elo import credenciais as cr

    arq = tmp_path / "ayanami.token"
    arq.write_text("ayn_do_arquivo\n")
    arq.chmod(0o600)
    assert cr.token_pc(tmp_path, keyring_get=lambda s, n: "ayn_do_keyring") == "ayn_do_keyring"
    assert cr.token_pc(tmp_path, keyring_get=lambda s, n: None) == "ayn_do_arquivo"

    def quebra(s: str, n: str) -> str:
        raise RuntimeError("sem backend")

    assert cr.token_pc(tmp_path, keyring_get=quebra) == "ayn_do_arquivo"
    arq.unlink()
    assert cr.token_pc(tmp_path, keyring_get=lambda s, n: None) is None


def test_url_ayanami_de_dict_e_config() -> None:
    from magi.elo.credenciais import url_ayanami

    class Cfg:
        raw = {"ayanami": {"url": " https://a.teste/ "}}

    assert url_ayanami({"ayanami": {"url": "https://a.teste/"}}) == "https://a.teste"
    assert url_ayanami(Cfg()) == "https://a.teste"
    assert url_ayanami({}) is None
    assert url_ayanami({"ayanami": {"url": ""}}) is None


def test_sync_token_padrao_le_arquivo_ao_lado_do_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from magi.elo import credenciais as cr

    monkeypatch.setattr(cr, "_keyring_get", lambda s, n: None)
    # sem arquivo: Ayanami fora (2) antes de tocar no banco
    assert ns.main(["--config", str(_config(tmp_path))], estado_em=tmp_path / "e.json") == 2
