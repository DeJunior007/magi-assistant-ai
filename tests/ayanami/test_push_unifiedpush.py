"""M1.5 — push ``unifiedpush`` no servidor (condessa-celular spec §9.6, CA-M34): ``[push] ntfy_hosts``,
``Assinar.tipo`` (``422 endpoint_proibido``), migração ``003_push_tipo`` e TTL mínimo de 60 s no envio.
``webpush`` falso, relógio injetado; banco só no ``ayanami-pg-teste``."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from pywebpush import WebPushException

from ayanami import push
from ayanami.api.app import criar_app
from ayanami.api.auth import criar_dispositivo
from ayanami.api.push import _host_permitido
from ayanami.config import ConfigError, Segredos, de_dict
from ayanami.deps import Deps
from ayanami.eventos import gravar
from ayanami.migrar import DIRETORIO, migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers.push import enviar
from magi.elo.mensagens import EventoTipo

URL_BASE = "https://ayanami.exemplo.ts.net"
NTFY = "ayanami.exemplo.ts.net:8443"
CFG = de_dict({"geral": {"url_base": URL_BASE}, "push": {"ntfy_hosts": [NTFY]}})
KEYS = {"p256dh": "BFalsoChavePublicaDoAparelho_123-abc", "auth": "authFalso_12"}
UP = {"endpoint": f"https://{NTFY}/upAbcFalso123?up=1", "keys": KEYS, "tipo": "unifiedpush"}


# --------------------------------------------------------------------------- funções puras


def test_config_ntfy_hosts():
    assert de_dict({"geral": {"url_base": URL_BASE}}).push.ntfy_hosts == ()
    assert CFG.push.ntfy_hosts == (NTFY,)
    for ruim in (["https://ntfy.exemplo"], ["ntfy.exemplo/up"], ["ntfy.exemplo:"], [""], "ntfy.exemplo"):
        with pytest.raises(ConfigError) as e:
            de_dict({"geral": {"url_base": URL_BASE}, "push": {"ntfy_hosts": ruim}})
        assert "push.ntfy_hosts" in str(e.value)


def test_host_permitido():
    hosts = (NTFY, "ntfy.exemplo")
    assert _host_permitido(f"https://{NTFY}/up1", hosts)
    assert _host_permitido("https://NTFY.exemplo/up1", hosts)
    assert _host_permitido("https://ntfy.exemplo:443/up1", hosts)
    assert not _host_permitido("https://ayanami.exemplo.ts.net/up1", hosts)  # porta diferente
    assert not _host_permitido("https://ntfy.exemplo:8443/up1", hosts)
    assert not _host_permitido("https://outro.exemplo/up1", hosts)
    assert not _host_permitido(f"https://x@{NTFY}/up1", hosts)
    assert not _host_permitido(f"https://{NTFY}.mal.exemplo/up1", hosts)
    assert not _host_permitido("https://ntfy.exemplo:99999/up1", hosts)
    assert not _host_permitido(f"https://{NTFY}/up1", ())


class Resp:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}


class WebpushFalso:
    """Responde com a fila de ``status`` (padrão 201) e guarda cada chamada."""

    def __init__(self) -> None:
        self.status: list[int] = []
        self.chamadas: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> Resp:
        self.chamadas.append(kw)
        st = self.status.pop(0) if self.status else 201
        if st > 202:
            raise WebPushException("falso", response=Resp(st))
        return Resp(st)


AGORA = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
VAPID = push.Vapid("privada-falsa", "mailto:teste@exemplo.com")


async def test_ttl_minimo_so_no_unifiedpush():
    web = WebpushFalso()
    up = push.Assinatura(1, UP["endpoint"], KEYS["p256dh"], KEYS["auth"], "unifiedpush")
    wp = push.Assinatura(2, "https://fcm.exemplo/abc", KEYS["p256dh"], KEYS["auth"])
    assert wp.tipo == "webpush"
    tag = "tarefa-" + "x" * 60
    for ass in (up, wp):
        for ttl in (0, 30, 3600):
            r = await push.enviar_um(web, ass, "{}", VAPID, urgencia="high", ttl=ttl, tag=tag, agora=AGORA)
            assert r.ok
    ttls = [c["ttl"] for c in web.chamadas]
    assert ttls == [60, 60, 3600, 0, 30, 3600]
    assert all(len(c["headers"]["Topic"]) <= 32 for c in web.chamadas)
    assert web.chamadas[0]["subscription_info"] == {"endpoint": UP["endpoint"], "keys": KEYS}


# --------------------------------------------------------------------------- banco (pg)


class Db:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


def _linhas(dsn: str, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, args).fetchall()


@pytest.fixture
def base(pg_nova_base) -> str:
    dsn = pg_nova_base("ayanami_up")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return dsn


def _cliente(app: Any, token: str) -> httpx.AsyncClient:
    transporte = httpx.ASGITransport(app=app, client=("100.64.0.1", 40000))
    return httpx.AsyncClient(transport=transporte, base_url="http://ayanami.test",
                             headers={"Authorization": f"Bearer {token}"})


@pytest.mark.pg
async def test_assinar_unifiedpush(base):
    app = criar_app(CFG, Db(base), RelogioFalso(AGORA), gerar_codigo=lambda: "123456")
    with psycopg.connect(base) as conn:
        token, _ = criar_dispositivo(conn, "celular-pedro", "celular", None)
    sql = "SELECT endpoint, tipo FROM push_assinaturas ORDER BY id"
    async with _cliente(app, token) as c:
        fora = {**UP, "endpoint": "https://ntfy.outro.exemplo/upAbc123"}
        r = await c.post("/v1/push/assinar", json=fora)
        assert r.status_code == 422 and r.json()["erro"] == "endpoint_proibido"
        r = await c.post("/v1/push/assinar", json={**UP, "tipo": "outro"})
        assert r.status_code == 422
        assert _linhas(base, sql) == []
        assert (await c.post("/v1/push/assinar", json=UP)).status_code == 201
        assert _linhas(base, sql) == [(UP["endpoint"], "unifiedpush")]
        # sem tipo = webpush (PWA), sem checar ntfy_hosts
        wp = {"endpoint": "https://fcm.exemplo/send/abc", "keys": KEYS}
        assert (await c.post("/v1/push/assinar", json=wp)).status_code == 201
        assert _linhas(base, sql) == [(wp["endpoint"], "webpush")]
        # o mesmo endpoint reassinado como unifiedpush troca o tipo
        assert (await c.post("/v1/push/assinar", json=UP)).status_code == 201
        assert (await c.post("/v1/push/assinar", json={**UP, "tipo": "webpush"})).status_code == 201
        assert _linhas(base, sql) == [(UP["endpoint"], "webpush")]
    resumos = [r[0] for r in _linhas(base, "SELECT resumo FROM auditoria WHERE tipo = 'push'")]
    assert not any("exemplo" in r for r in resumos)


@pytest.mark.pg
def test_migracao_mantem_webpush(pg_nova_base, tmp_path: Path):
    for nome in ("001_base.sql", "002_noticias.sql"):
        shutil.copy(DIRETORIO / nome, tmp_path / nome)
    dsn = pg_nova_base("ayanami_up_mig")
    with psycopg.connect(dsn) as conn:
        migrar(conn, diretorio=tmp_path)
        _, cel = criar_dispositivo(conn, "celular-pedro", "celular", None)
        conn.execute("INSERT INTO push_assinaturas (dispositivo, endpoint, p256dh, auth)"
                     " VALUES (%s, 'https://fcm.exemplo/abc', 'p', 'a')", (cel.id,))
        assert "003" in migrar(conn)
        assert conn.execute("SELECT tipo FROM push_assinaturas").fetchall() == [("webpush",)]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE push_assinaturas SET tipo = 'apns'")


@pytest.fixture
def amb(base):
    with psycopg.connect(base) as conn:
        _, cel = criar_dispositivo(conn, "celular-pedro", "celular", None)
        for endpoint, tipo in (("https://fcm.exemplo/abc", "webpush"), (UP["endpoint"], "unifiedpush")):
            conn.execute("INSERT INTO push_assinaturas (dispositivo, endpoint, p256dh, auth, tipo)"
                         " VALUES (%s, %s, 'chave-falsa-p256dh', 'auth-falso', %s)",
                         (cel.id, endpoint, tipo))
    relogio, web = RelogioFalso(AGORA), WebpushFalso()  # 12:00 em SP
    segredos = Segredos({"VAPID_PRIVATE_KEY": "privada-falsa", "VAPID_SUB": "mailto:teste@exemplo.com"})
    deps = Deps(db=Db(base), cfg=CFG, relogio=relogio, extras={"webpush": web, "segredos": segredos})
    return SimpleNamespace(dsn=base, relogio=relogio, web=web, deps=deps)


def _evento(amb, tipo: EventoTipo) -> int:
    with psycopg.connect(amb.dsn) as conn:
        return gravar(conn, tipo, "Pesquisa pronta", "Monitores OLED 27", "tarefa:abc-123",
                      para=("pc", "celular"), agora=amb.relogio.agora(), notificar=False).seq


@pytest.mark.pg
async def test_envio_mesmo_payload_ttl_e_410(amb):
    r = await enviar(amb.deps, SimpleNamespace(app=None), evento_id=_evento(amb, EventoTipo.TAREFA_PRONTA))
    assert r["dados"]["enviados"] == 2
    wp, up = amb.web.chamadas
    assert up["subscription_info"]["endpoint"] == UP["endpoint"]
    assert up["data"] == wp["data"] and json.loads(up["data"])["tag"] == "tarefa-abc-123"
    assert up["headers"] == wp["headers"] and len(up["headers"]["Topic"]) <= 32
    assert up["ttl"] == wp["ttl"] >= 60
    # 410 no unifiedpush apaga só ele
    amb.web.status = [201, 410]
    await enviar(amb.deps, SimpleNamespace(app=None), evento_id=_evento(amb, EventoTipo.MONITOR))
    assert _linhas(amb.dsn, "SELECT tipo FROM push_assinaturas") == [("webpush",)]
