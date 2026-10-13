"""Eventos (Y2.3): gravar + NOTIFY, distribuição ao SSE e ao PC, e o LISTEN que relê na reconexão."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import psycopg
import pytest

from ayanami.eventos import CANAL, Eventos, criar_evento, gravar, listar_desde
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.tarefas import CANAL_EVENTOS
from magi.elo.mensagens import Ack, Envelope, Evento, EventoTipo, Ola, Tipo, TipoDispositivo, responder

pytestmark = pytest.mark.pg


class Db:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def connection(self):
        return psycopg.connect(self.dsn)


@pytest.fixture
def db(pg_nova_base: Callable[[str], str]) -> Db:
    dsn = pg_nova_base("ayanami_ev")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return Db(dsn)


class Pub:
    def __init__(self) -> None:
        self.itens: list[tuple[object, str, object, int | None]] = []

    def __call__(self, alvo, nome, corpo, *, id=None):  # noqa: A002
        self.itens.append((alvo, nome, corpo, id))
        return 1

    def seqs(self, alvo: str = "celular") -> list[int]:
        return [i[3] for i in self.itens if i[0] == alvo and i[1] == "evento"]


class HubFalso:
    def __init__(self, online: bool = True, responde: bool = True) -> None:
        self.online = online
        self.responde = responde
        self.enviados: list[Envelope] = []

    def destino(self, para: str):
        return object() if self.online else None

    async def enviar_e_esperar(self, env: Envelope, prazo: float) -> Envelope:
        self.enviados.append(env)
        if not self.responde:
            raise TimeoutError
        return responder(env, Tipo.ACK, Ack(), "pc-casa")


def _entregues(db: Db) -> list[int]:
    with db.connection() as conn:
        return [r[0] for r in conn.execute(
            "SELECT id FROM eventos WHERE entregue_pc IS NOT NULL ORDER BY id").fetchall()]


async def _ate(cond: Callable[[], bool], voltas: int = 300) -> None:
    for _ in range(voltas):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condição não chegou")


def test_mesmo_canal_da_fila():
    assert CANAL == CANAL_EVENTOS


def test_gravar_corta_e_notifica(db: Db):
    with psycopg.connect(db.dsn, autocommit=True) as ouvinte:
        ouvinte.execute(f"LISTEN {CANAL}")
        ev = criar_evento(db, "tarefa_pronta", "x" * 100, "y" * 300, "tarefa:1", para=("celular",))
        notas = list(ouvinte.notifies(timeout=2, stop_after=1))
    assert ev.seq > 0 and len(ev.titulo) == 80 and len(ev.resumo) == 200
    assert [n.payload for n in notas] == [str(ev.seq)]
    assert listar_desde(db, 0, "pc") == []
    assert [e.seq for e in listar_desde(db, 0, "celular")] == [ev.seq]


def test_tipo_desconhecido_e_ignorado(db: Db):
    with db.connection() as conn:
        conn.execute("INSERT INTO eventos (tipo, titulo) VALUES ('estranho', 'a')")
        gravar(conn, EventoTipo.LEMBRETE, "b")
    assert [e.titulo for e in listar_desde(db, 0)] == ["b"]


async def test_criar_distribui_so_o_novo(db: Db):
    criar_evento(db, "monitor", "antigo")
    pub = Pub()
    svc = Eventos(db, RelogioFalso(), publicar=pub)
    ev = await svc.criar(EventoTipo.TAREFA_PRONTA, "Pesquisa pronta", "OLED", "tarefa:9")
    assert pub.seqs("celular") == [ev.seq] and pub.seqs("pc") == [ev.seq]
    assert isinstance(pub.itens[0][2], Evento)
    assert await svc.distribuir() == 0  # nada novo: não repete


async def test_pc_recebe_e_marca_entregue(db: Db):
    hub = HubFalso()
    svc = Eventos(db, RelogioFalso(), hub=hub)
    a = await svc.criar("lembrete", "Remédio")
    await svc.criar("tarefa_pronta", "só celular", para=("celular",))
    await _ate(lambda: _entregues(db) == [a.seq])
    assert [e.corpo.seq for e in hub.enviados] == [a.seq]
    assert all(e.t is Tipo.EVENTO and e.para == "pc" for e in hub.enviados)
    await svc.fechar()


async def test_pc_offline_fica_pendente_e_sai_no_ola(db: Db):
    hub = HubFalso(online=False)
    svc = Eventos(db, RelogioFalso(), hub=hub)
    e1 = await svc.criar("lembrete", "um")
    e2 = await svc.criar("lembrete", "dois")
    e3 = await svc.criar("lembrete", "tres")
    await asyncio.gather(*list(svc._tarefas))  # as entregas agendadas acham o PC offline
    assert await svc.entregar_pc() == 0 and _entregues(db) == []
    hub.online = True
    # o PC já tinha o e1 (retomar_desde): só e2 e e3 vão
    await svc.ao_ola_pc(None, Ola(tipo=TipoDispositivo.PC, versao="t", retomar_desde=str(e1.seq)))
    await _ate(lambda: _entregues(db) == [e1.seq, e2.seq, e3.seq])
    assert [e.corpo.seq for e in hub.enviados] == [e2.seq, e3.seq]
    await svc.fechar()


async def test_pc_sem_ack_para_no_primeiro(db: Db):
    hub = HubFalso(responde=False)
    svc = Eventos(db, RelogioFalso(), hub=hub)
    await svc.criar("lembrete", "um")
    await svc.criar("lembrete", "dois")
    await svc.fechar()
    assert await svc.entregar_pc() == 0
    assert _entregues(db) == []


async def test_notify_perdido_sai_na_reconexao(db: Db):
    pub = Pub()
    svc = Eventos(db, RelogioFalso(), publicar=pub)
    conexoes: list[psycopg.AsyncConnection] = []

    async def conectar():
        c = await psycopg.AsyncConnection.connect(db.dsn, autocommit=True)
        conexoes.append(c)
        return c

    tarefa = asyncio.ensure_future(svc.ouvir(conectar))
    try:
        await _ate(lambda: len(conexoes) == 1)
        await asyncio.sleep(0.05)
        e1 = criar_evento(db, "lembrete", "com notify")
        await _ate(lambda: pub.seqs() == [e1.seq])
        # a conexão do LISTEN cai e o evento entra sem NOTIFY (perdido)
        with psycopg.connect(db.dsn) as admin:
            pid = conexoes[0].info.backend_pid
            with db.connection() as conn:
                e2 = gravar(conn, "lembrete", "sem notify", notificar=False)
            admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        await _ate(lambda: pub.seqs() == [e1.seq, e2.seq])
        assert len(conexoes) >= 2
    finally:
        tarefa.cancel()
        await asyncio.gather(tarefa, return_exceptions=True)
        for c in conexoes:
            await c.close()
