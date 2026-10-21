"""P2.1 — Web Push no servidor (CA-Y59, parte do servidor): ``webpush`` falso, relógio injetado,
fila falsa; banco só no ``ayanami-pg-teste``. Chaves VAPID só geradas aqui, nunca gravadas."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest
from pywebpush import WebPushException

from ayanami import push
from ayanami.api.auth import criar_dispositivo
from ayanami.config import Segredos, de_dict
from ayanami.deps import Deps
from ayanami.eventos import gravar
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers.push import enviar
from magi.elo.mensagens import Evento, EventoTipo

SP = ZoneInfo("America/Sao_Paulo")
CFG = de_dict({"geral": {"url_base": "https://ayanami.exemplo.ts.net"}})


# --------------------------------------------------------------------------- funções puras


def test_tipo_do_evento():
    assert push.tipo_push(EventoTipo.CONFIRMACAO) == "confirma"
    assert push.tipo_push(EventoTipo.TAREFA_FALHOU) == "tarefa"
    assert push.tipo_push(EventoTipo.NOTICIA_BOMBA) == "noticia"
    assert push.tipo_push(EventoTipo.BACKUP_FALHOU) == "operacao"
    assert push.tipo_push(EventoTipo.DISPOSITIVO) is None
    assert push.POLITICAS["confirma"] == push.Politica("high", 120, "passa")
    assert push.POLITICAS["noticia"].urgencia == "low"


def test_payload_cortado_e_pequeno():
    ev = Evento(seq=7, tipo=EventoTipo.TAREFA_PRONTA, titulo="T" * 80, resumo="r " * 100,
                ref="tarefa:0b8c1c2e-1111-2222-3333-444455556666")
    p = push.montar_payload(ev, datetime(2026, 3, 1, 12, tzinfo=UTC))
    assert len(p["titulo"]) <= 40 and len(p["resumo"]) <= 120
    assert p["url"] == "/app/#/tarefas/0b8c1c2e-1111-2222-3333-444455556666"
    assert p["tag"] == "tarefa-0b8c1c2e-1111-2222-3333-444455556666"
    assert p["id"] == "7" and p["ts"] == "2026-03-01T12:00:00Z" and p["v"] == 1
    assert len(push.serializar(p).encode()) <= 3 * 1024
    c = push.montar_payload(Evento(seq=8, tipo=EventoTipo.CONFIRMACAO, titulo="Confirmar?",
                                   ref="confirma:01J0000000000000000000ABCD"), datetime.now(UTC))
    assert c["url"] == "/app/#/confirma/01J0000000000000000000ABCD" and c["tipo"] == "confirma"
    estranho = push.montar_payload(Evento(seq=9, tipo=EventoTipo.MONITOR, titulo="x", ref="tarefa:../a b"),
                                   datetime.now(UTC))
    assert estranho["url"] == "/app/#/feed" and estranho["tag"] == "monitor-9"
    gigante = {**p, "resumo": "x" * 10_000}
    assert len(push.serializar(gigante).encode()) <= 3 * 1024
    assert len(push.topic(p["tag"])) <= 32


def test_retry_after_e_silencio():
    agora = datetime(2026, 3, 1, 12, tzinfo=UTC)
    assert push.retry_after("17", agora) == 17
    assert push.retry_after("Sun, 01 Mar 2026 12:01:00 GMT", agora) == 60
    assert push.retry_after("lixo", agora) is None and push.retry_after(None, agora) is None
    j = push.ler_janela("23:00-07:30")
    assert j == (time(23), time(7, 30))
    assert push.ler_janela("") is None
    assert push.em_silencio(datetime(2026, 3, 2, 2, 30, tzinfo=UTC), j, SP)  # 23:30 em SP
    assert not push.em_silencio(datetime(2026, 3, 2, 11, tzinfo=UTC), j, SP)  # 08:00 em SP
    assert push.fim_do_silencio(datetime(2026, 3, 2, 2, 30, tzinfo=UTC), j, SP) == \
        datetime(2026, 3, 2, 10, 30, tzinfo=UTC)
    assert push.janela_do("23:00-07:30", {"silencio": ""}) is None
    assert push.janela_do("23:00-07:30", {"silencio": "22:00-06:00"}) == (time(22), time(6))


def test_decidir():
    base = dict(agora=datetime(2026, 3, 1, 15, tzinfo=UTC), fuso=SP, silencio_padrao="23:00-07:30",
                max_hora=10, noticias_dia=3, pc_online=False, enviados_hora=0, noticias_hoje=0)
    assert push.decidir("tarefa", {}, **base).acao == "enviar"
    assert push.decidir("tarefa", {"push": False}, **base).acao == "pular"
    com_pc = {**base, "pc_online": True}
    assert push.decidir("tarefa", {"push_com_pc": False}, **com_pc).acao == "pular"
    assert push.decidir("confirma", {"push_com_pc": False}, **com_pc).acao == "enviar"
    assert push.decidir("tarefa", {}, **com_pc).acao == "enviar"
    cheio = {**base, "enviados_hora": 10}
    d = push.decidir("monitor", {}, **cheio)
    assert d.acao == "acumular" and d.liberar_em == datetime(2026, 3, 1, 16, tzinfo=UTC)
    assert push.decidir("confirma", {}, **cheio).acao == "enviar"
    assert push.decidir("noticia", {}, **{**base, "noticias_hoje": 3}).acao == "descartar"


def test_cli_chaves_gera_par_valido():
    from py_vapid import Vapid

    saida, erro = io.StringIO(), io.StringIO()
    assert push.cli(["chaves", "--sub", "mailto:teste@exemplo.com"], saida=saida, erro=erro) == 0
    linhas = dict(linha.split("=", 1) for linha in saida.getvalue().splitlines())
    assert set(linhas) == {"VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUB"}
    assert linhas["VAPID_SUB"] == "mailto:teste@exemplo.com"
    pub = base64.urlsafe_b64decode(linhas["VAPID_PUBLIC_KEY"] + "==")
    assert len(pub) == 65 and pub[0] == 4
    Vapid.from_string(linhas["VAPID_PRIVATE_KEY"])  # o pywebpush aceita o formato
    assert push.cli(["chaves", "--sub", "teste"], saida=io.StringIO(), erro=io.StringIO()) == 2


# --------------------------------------------------------------------------- job (pg)


class DbTeste:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


class Resp:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}


class WebpushFalso:
    """Responde com a fila de ``status`` (padrão 201) e guarda cada chamada."""

    def __init__(self) -> None:
        self.status: list[tuple[int, dict[str, str]]] = []
        self.chamadas: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> Resp:
        self.chamadas.append(kw)
        st, cab = self.status.pop(0) if self.status else (201, {})
        if st > 202:
            raise WebPushException("falso", response=Resp(st, cab))
        return Resp(st, cab)

    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(c["data"]) for c in self.chamadas]


class FilaFalsa:
    def __init__(self) -> None:
        self.deferidos: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def configure_task(self, nome: str, **op: Any) -> Any:
        fila = self

        class Tarefa:
            async def defer_async(self, **kw: Any) -> int:
                fila.deferidos.append((nome, op, kw))
                return len(fila.deferidos)

        return Tarefa()


@pytest.fixture
def amb(pg_nova_base):
    dsn = pg_nova_base("ayanami_push")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
        _, cel = criar_dispositivo(conn, "celular-pedro", "celular", None)
        conn.execute("INSERT INTO push_assinaturas (dispositivo, endpoint, p256dh, auth)"
                     " VALUES (%s, 'https://fcm.exemplo/abc', 'chave-falsa-p256dh', 'auth-falso')", (cel.id,))
    relogio = RelogioFalso(datetime(2026, 3, 2, 15, 0, tzinfo=UTC))  # 12:00 em SP
    web, fila = WebpushFalso(), FilaFalsa()
    segredos = Segredos({"VAPID_PRIVATE_KEY": "privada-falsa", "VAPID_SUB": "mailto:teste@exemplo.com"})
    deps = Deps(db=DbTeste(dsn), cfg=CFG, relogio=relogio,
                extras={"webpush": web, "fila": fila, "segredos": segredos})
    return SimpleNamespace(dsn=dsn, cel=cel, relogio=relogio, web=web, fila=fila, deps=deps)


def _evento(amb, tipo: EventoTipo, titulo: str = "Pesquisa pronta", resumo: str = "Monitores OLED 27",
            ref: str | None = None, para: tuple[str, ...] = ("pc", "celular")) -> int:
    with psycopg.connect(amb.dsn) as conn:
        return gravar(conn, tipo, titulo, resumo, ref, para=para, agora=amb.relogio.agora(),
                      notificar=False).seq


async def _job(amb, evento_id: int, **kw: Any) -> Any:
    return await enviar(amb.deps, SimpleNamespace(app=None), evento_id=evento_id, **kw)


def _um(amb, sql: str, *args: Any) -> Any:
    with psycopg.connect(amb.dsn) as conn:
        return conn.execute(sql, args).fetchone()


@pytest.mark.pg
async def test_envia_payload_e_e_idempotente(amb):
    eid = _evento(amb, EventoTipo.TAREFA_PRONTA, "T" * 80, "R" * 200, ref="tarefa:abc-123")
    r = await _job(amb, eid)
    assert r["dados"]["enviados"] == 1
    (c,) = amb.web.chamadas
    assert c["ttl"] == 24 * 3600 and c["headers"]["Urgency"] == "normal" and c["timeout"] == 10
    assert c["vapid_claims"] == {"sub": "mailto:teste@exemplo.com"}
    assert c["subscription_info"]["endpoint"] == "https://fcm.exemplo/abc"
    assert len(c["data"].encode()) <= 3 * 1024
    p = json.loads(c["data"])
    assert len(p["titulo"]) <= 40 and len(p["resumo"]) <= 120 and p["tag"] == "tarefa-abc-123"
    assert _um(amb, "SELECT push_enviado IS NOT NULL FROM eventos WHERE id = %s", eid)[0]
    aud = _um(amb, "SELECT resumo, ok FROM auditoria WHERE tipo = 'push' AND alvo = %s", f"evento:{eid}")
    assert aud == ("enviado tipo=tarefa status=201", True)  # sem texto do evento
    await _job(amb, eid)
    assert len(amb.web.chamadas) == 1


@pytest.mark.pg
async def test_sem_celular_ou_dispositivo_nao_envia(amb):
    await _job(amb, _evento(amb, EventoTipo.TAREFA_PRONTA, para=("pc",)))
    await _job(amb, _evento(amb, EventoTipo.DISPOSITIVO))
    await _job(amb, 99999)
    assert amb.web.chamadas == []


@pytest.mark.pg
async def test_410_apaga_assinatura(amb):
    amb.web.status = [(410, {})]
    await _job(amb, _evento(amb, EventoTipo.MONITOR))
    assert _um(amb, "SELECT count(*) FROM push_assinaturas")[0] == 0


@pytest.mark.pg
async def test_413_corta_resumo_e_reenvia(amb):
    amb.web.status = [(413, {})]
    await _job(amb, _evento(amb, EventoTipo.TAREFA_PRONTA))
    a, b = amb.web.payloads()
    assert a["resumo"] and b["resumo"] == ""


@pytest.mark.pg
async def test_429_respeita_retry_after_e_repete(amb):
    amb.web.status = [(429, {"Retry-After": "60"})]
    eid = _evento(amb, EventoTipo.TAREFA_PRONTA)
    await _job(amb, eid)
    ((nome, op, kw),) = amb.fila.deferidos
    assert nome == "push.enviar" and op["schedule_at"] == amb.relogio.agora() + timedelta(seconds=60)
    assert kw["tentativa"] == 1 and kw["assinatura"] and kw["evento_id"] == eid
    amb.relogio.avancar(60)
    await _job(amb, **kw)
    assert len(amb.web.chamadas) == 2 and amb.web.payloads()[0] == amb.web.payloads()[1]
    # sem Retry-After: espera da tabela (5 s); 500 três vezes → desiste
    amb.fila.deferidos.clear()
    amb.web.status = [(500, {})] * 4
    eid2 = _evento(amb, EventoTipo.MONITOR)
    await _job(amb, eid2)
    for esperado in (5, 30, 120):
        (_, op, kw), = amb.fila.deferidos[-1:]
        assert op["schedule_at"] == amb.relogio.agora() + timedelta(seconds=esperado)
        amb.relogio.avancar(esperado)
        n = len(amb.fila.deferidos)
        await _job(amb, **kw)
    assert len(amb.fila.deferidos) == n  # a 4ª falha não reagenda
    assert _um(amb, "SELECT falhas FROM push_assinaturas")[0] == 1
    assert _um(amb, "SELECT count(*) FROM auditoria WHERE resumo LIKE 'falhou %%'")[0] == 1


@pytest.mark.pg
async def test_silencio_agrupa_as_0730(amb):
    amb.relogio = amb.deps.relogio = RelogioFalso(datetime(2026, 3, 3, 2, 30, tzinfo=UTC))  # 23:30 SP
    tipos = (EventoTipo.CONFIRMACAO, EventoTipo.LEMBRETE, EventoTipo.TAREFA_PRONTA, EventoTipo.MONITOR,
             EventoTipo.BACKUP_FALHOU, EventoTipo.NOTICIA_BOMBA)
    ids = {t: _evento(amb, t) for t in tipos}
    for eid in ids.values():
        await _job(amb, eid)
    assert [p["tipo"] for p in amb.web.payloads()] == ["confirma", "lembrete"]
    assert amb.web.chamadas[0]["headers"]["Urgency"] == "high" and amb.web.chamadas[0]["ttl"] == 120
    manha = datetime(2026, 3, 3, 10, 30, tzinfo=UTC)
    assert [op["schedule_at"] for _, op, _ in amb.fila.deferidos] == [manha] * 3  # notícia descartada
    amb.relogio.avancar((manha - amb.relogio.agora()).total_seconds())
    for _, _, kw in amb.fila.deferidos[:]:
        await _job(amb, **kw)
    assert len(amb.web.chamadas) == 3
    p = amb.web.payloads()[-1]
    assert p["titulo"] == "3 avisos" and p["tag"] == "resumo-manha"


@pytest.mark.pg
async def test_decimo_primeiro_na_hora_agrupa(amb):
    ids = [_evento(amb, EventoTipo.TAREFA_PRONTA, ref=f"tarefa:t{i}") for i in range(12)]
    for eid in ids:
        await _job(amb, eid)
    assert len(amb.web.chamadas) == 10
    proxima = datetime(2026, 3, 2, 16, 0, tzinfo=UTC)
    assert [op["schedule_at"] for _, op, _ in amb.fila.deferidos] == [proxima, proxima]
    amb.relogio.avancar(3600)
    for _, _, kw in amb.fila.deferidos[:]:
        await _job(amb, **kw)
    assert len(amb.web.chamadas) == 11
    assert amb.web.payloads()[-1]["titulo"] == "2 avisos"


@pytest.mark.pg
async def test_push_com_pc_false_com_pc_online(amb):
    with psycopg.connect(amb.dsn) as conn:
        conn.execute("UPDATE dispositivos SET preferencias = %s WHERE id = %s",
                     (json.dumps({"push": True, "push_com_pc": False, "silencio": "23:00-07:30"}),
                      amb.cel.id))
        _, pc = criar_dispositivo(conn, "pc-pedro", "pc", None)
        conn.execute("UPDATE dispositivos SET visto = %s WHERE id = %s", (amb.relogio.agora(), pc.id))
    for t in (EventoTipo.TAREFA_PRONTA, EventoTipo.LEMBRETE, EventoTipo.CONFIRMACAO):
        await _job(amb, _evento(amb, t))
    assert [p["tipo"] for p in amb.web.payloads()] == ["confirma"]
    amb.relogio.avancar(120)  # PC sumiu (offline_apos_s = 30)
    await _job(amb, _evento(amb, EventoTipo.TAREFA_PRONTA))
    assert [p["tipo"] for p in amb.web.payloads()] == ["confirma", "tarefa"]
