"""Y2.2: confirmações — criar, responder uma vez, expirar em 120 s (relógio falso), 404/409/410 e
resposta do PC pela WS (hub com canal falso)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import psycopg
import pytest

from ayanami import confirmacoes as cf
from ayanami.db import ConexaoUnica
from ayanami.hub import Hub
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from magi.elo.mensagens import Confirma, Envelope, Tipo, decode, encode, responder

pytestmark = pytest.mark.pg


@pytest.fixture
def db(pg_nova_base):
    dsn = pg_nova_base("ayanami_conf")
    with psycopg.connect(dsn, autocommit=True) as conn:
        migrar(conn)
        yield ConexaoUnica(conn)


@pytest.fixture
def relogio():
    return RelogioFalso()


def _criar(db, relogio, **kw):
    return cf.criar(db, relogio, descricao="desligar a TV da sala",
                    pedido={"tipo": "teste", "origem": "mcp", **kw})


def test_criar_expira_em_120s(db, relogio):
    c = _criar(db, relogio)
    assert c.expira == relogio.agora() + timedelta(seconds=120)
    assert c.resposta is None and cf.obter(db, c.id) == c
    assert c.id in {p.id for p in cf.pendentes(db, relogio)}
    e = c.para_elo()
    assert isinstance(e, Confirma) and e.pedido == c.id and e.origem == "mcp" and e.expira_em == c.expira


def test_responder_uma_vez(db, relogio):
    c = _criar(db, relogio)
    r = cf.responder(db, relogio, c.id, True)
    assert r.resposta is True and r.respondida == relogio.agora()
    with pytest.raises(cf.JaRespondida) as e:
        cf.responder(db, relogio, c.id, False)
    assert e.value.status == 409
    assert cf.obter(db, c.id).resposta is True


def test_expirada_410(db, relogio):
    c = _criar(db, relogio)
    relogio.avancar(119)
    assert c.id in {p.id for p in cf.pendentes(db, relogio)}
    relogio.avancar(1)
    with pytest.raises(cf.Expirada) as e:
        cf.responder(db, relogio, c.id, True)
    assert e.value.status == 410
    assert c.id in {x.id for x in cf.expiradas(db, relogio)}
    assert c.id not in {p.id for p in cf.pendentes(db, relogio)}


def test_inexistente_404(db, relogio):
    with pytest.raises(cf.NaoEncontrada) as e:
        cf.responder(db, relogio, "01JA2Z7Q8M4V0K3N5R6S7T8W9X", True)
    assert e.value.status == 404


async def test_servico_executa_so_no_sim(db, relogio):
    svc = cf.Confirmacoes(db, relogio)
    rodou: list[str] = []
    svc.ao_confirmar("teste", lambda c: rodou.append(c.id) or {"ok": True})
    nao = await svc.criar(descricao="x", pedido={"tipo": "teste"})
    sim = await svc.criar(descricao="y", pedido={"tipo": "teste"})
    assert (await svc.responder(nao.id, False))[1] is None
    c, res = await svc.responder(sim.id, True)
    assert res == {"ok": True} and rodou == [sim.id] and c.resposta is True


class PcFalso:
    """Responde a pergunta ``confirma`` com ``resposta=True``."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.no = None
        self.perguntas: list[Envelope] = []

    async def enviar(self, texto: str) -> None:
        env = decode(texto)
        if env.t is Tipo.CONFIRMA:
            self.perguntas.append(env)
            corpo = Confirma(pedido=env.corpo.pedido, resposta=True)
            r = responder(env, Tipo.CONFIRMA, corpo, "pc-pedro")
            asyncio.get_running_loop().create_task(self.hub.receber(self.no, encode(r)))

    async def fechar(self, codigo: int) -> None:
        pass


async def test_pc_responde_pela_ws(db, relogio):
    from ayanami.api.auth import criar_dispositivo
    from magi.elo.mensagens import Ola, TipoDispositivo

    with db.connection() as conn:
        _, disp = criar_dispositivo(conn, f"pc-{uuid.uuid4().hex[:8]}", "pc")
    hub = Hub(db, relogio)
    pc = PcFalso(hub)
    pc.no = await hub.registrar(disp, pc)
    await hub.receber(pc.no, encode(Envelope(t=Tipo.OLA, corpo=Ola(tipo=TipoDispositivo.PC, versao="t"),
                                             de=disp.nome, para="ayanami")))
    svc = cf.Confirmacoes(db, relogio, hub)
    feito = asyncio.Event()
    svc.ao_confirmar("teste", lambda c: feito.set())
    c = await svc.criar(descricao="desligar a TV", pedido={"tipo": "teste"})
    await asyncio.wait_for(feito.wait(), 2)
    assert pc.perguntas and pc.perguntas[0].corpo.pedido == c.id
    assert cf.obter(db, c.id).resposta is True
    await hub.fechar_dispositivo(disp.id)


# --- Y2.2b: confirmação vira evento, SSE e push ------------------------------------------------


class PcQueGuarda:
    """Canal do PC que só guarda o que chega (não responde)."""

    def __init__(self) -> None:
        self.recebidos: list[Envelope] = []

    async def enviar(self, texto: str) -> None:
        self.recebidos.append(decode(texto))

    async def fechar(self, codigo: int) -> None:
        pass


async def test_criar_grava_evento_publica_sse_e_defere_push(db, relogio):
    from ayanami import push as pushmod
    from ayanami.eventos import Eventos, listar_desde

    publicados: list[tuple] = []
    pushes: list[int] = []

    async def push(seq: int) -> None:
        pushes.append(seq)

    def publicar(alvo, nome, corpo, *, id=None):  # noqa: A002
        publicados.append((alvo, nome, corpo))
        return 1

    ev = Eventos(db, relogio, publicar=publicar, push=push)
    svc = cf.Confirmacoes(db, relogio, eventos=ev, publicar=publicar)
    c = await svc.criar(descricao="desligar a TV da sala", pedido={"tipo": "teste", "origem": "mcp"})
    await asyncio.sleep(0)
    evs = [e for e in listar_desde(db, 0, "celular") if e.ref == f"confirma:{c.id}"]
    assert len(evs) == 1 and evs[0].resumo == "desligar a TV da sala"
    assert listar_desde(db, 0, "pc") == []  # o PC recebe a pergunta pelo hub, não um evento
    assert pushes == [evs[0].seq]
    assert ("celular", "evento", evs[0]) in publicados
    conf = [p for p in publicados if p[1] == "confirma"]
    assert conf == [("celular", "confirma", c.para_elo())] and conf[0][2].expira_em == c.expira
    # o push monta `?d=&expira=` a partir do evento (P2.1/P2.3)
    pl = pushmod.montar_payload(evs[0], relogio.agora())
    assert pl["tipo"] == "confirma" and pl["d"] == "desligar a TV da sala"
    assert pl["expira"] == c.expira.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert pl["url"].startswith(f"/app/#/confirma/{c.id}?d=")

    publicados.clear()
    await svc.responder(c.id, False)
    assert [(a, n, x.pedido, x.resposta) for a, n, x in publicados] == [("celular", "confirma", c.id, False)]


async def test_responder_fecha_no_pc_salvo_quando_o_pc_respondeu(db, relogio):
    from ayanami.api.auth import criar_dispositivo
    from magi.elo.mensagens import Ola, TipoDispositivo

    with db.connection() as conn:
        _, disp = criar_dispositivo(conn, f"pc-{uuid.uuid4().hex[:8]}", "pc")
    hub = Hub(db, relogio)
    pc = PcQueGuarda()
    no = await hub.registrar(disp, pc)
    await hub.receber(no, encode(Envelope(t=Tipo.OLA, corpo=Ola(tipo=TipoDispositivo.PC, versao="t"),
                                          de=disp.nome, para="ayanami")))
    pc.recebidos.clear()
    svc = cf.Confirmacoes(db, relogio, hub)
    a = await svc.criar(descricao="a", pedido={"tipo": "teste"}, perguntar=False)
    b = await svc.criar(descricao="b", pedido={"tipo": "teste"}, perguntar=False)
    await svc.responder(a.id, True)  # respondida no celular: o PC descarta a pergunta
    assert [(e.t, e.corpo.pedido, e.corpo.resposta) for e in pc.recebidos] == [(Tipo.CONFIRMA, a.id, True)]
    await svc.responder(b.id, False, de_pc=True)
    assert len(pc.recebidos) == 1
    await hub.fechar_dispositivo(disp.id)
