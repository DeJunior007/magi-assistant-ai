"""SSE ``GET /v1/eventos`` (Y2.3): retomada pelo ``Last-Event-ID`` sem perder nem repetir, 4 SSE por
celular, revogação (mesmo processo e outro processo, ≤ 5 s no relógio falso), confirmações e estado."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ayanami import confirmacoes
from ayanami.api.auth import marcar_revogado
from ayanami.api.eventos import PING_S, fluxo, sse_de
from ayanami.eventos import criar_evento, eventos_de
from magi.elo.mensagens import Envelope, Estado, EstadoTv, Tipo

pytestmark = pytest.mark.pg


def _ler(bloco: str) -> dict[str, Any]:
    campos: dict[str, Any] = {}
    for linha in bloco.strip("\n").split("\n"):
        chave, _, valor = linha.partition(": ")
        campos[chave] = valor
    if "data" in campos:
        campos["data"] = json.loads(campos["data"])
    return campos


def _blocos(texto: str) -> list[dict[str, Any]]:
    return [_ler(b) for b in texto.split("\n\n") if b.strip() and not b.startswith("retry:")]


async def _proximo(gen, nome: str = "evento") -> dict[str, Any]:
    for _ in range(5000):  # sem laço infinito: o relógio falso só gera ping
        b = await anext(gen)
        if not b.startswith("retry:") and _ler(b).get("event") == nome:
            return _ler(b)
    raise AssertionError(f"{nome} não chegou")


@pytest.fixture
def ctx(app):
    return app.state.ctx


@pytest.fixture
def celular(ctx, novo_token):
    token = novo_token("celular-pedro", "celular")
    return token, ctx.auth.verificar(token)


async def test_retoma_do_last_event_id_sem_perder_nem_repetir(ctx, celular):
    _, disp = celular
    pub, svc = sse_de(ctx), eventos_de(ctx)
    a = pub.abrir(disp)
    gen_a = fluxo(ctx, pub, a, None)
    await anext(gen_a)  # retry: assinado
    seqs = [(await svc.criar("lembrete", f"e{i}")).seq for i in range(100)]
    vistos = []
    while len(vistos) < 37:
        vistos.append(int((await _proximo(gen_a))["id"]))
    assert vistos == seqs[:37]
    await gen_a.aclose()
    assert pub.contar(disp.id) == 0

    b = pub.abrir(disp)
    gen_b = fluxo(ctx, pub, b, vistos[-1])
    await anext(gen_b)  # assinou; a releitura ainda não rodou
    novos = [(await svc.criar("lembrete", f"n{i}")).seq for i in range(3)]  # vão ao vivo E ao banco
    recebidos = []
    while len(recebidos) < 66:
        ev = await _proximo(gen_b)
        recebidos.append(int(ev["id"]))
        assert ev["data"]["tipo"] == "lembrete"
    assert recebidos == seqs[37:] + novos
    # nada repetido depois: só ping/varredura até o próximo evento
    ultimo = (await svc.criar("lembrete", "fim")).seq
    assert int((await _proximo(gen_b))["id"]) == ultimo
    await gen_b.aclose()


async def test_quinto_sse_do_mesmo_celular_429(app, ctx, celular, cliente):
    token, disp = celular
    pub = sse_de(ctx)
    abertos = [pub.abrir(disp) for _ in range(4)]
    async with cliente(app, token) as c:
        r = await c.get("/v1/eventos")
    assert r.status_code == 429 and r.json()["erro"] == "muitas_conexoes"
    pub.fechar(abertos[0])
    assert pub.contar(disp.id) == 3


async def test_revogar_de_outro_processo_fecha_em_5s(ctx, celular, relogio, db):
    _, disp = celular
    pub = sse_de(ctx)
    a = pub.abrir(disp)
    gen = fluxo(ctx, pub, a, None)
    await anext(gen)
    await _proximo(gen, "ping")  # já passou uma varredura
    with db.connection() as conn:
        marcar_revogado(conn, disp.id, relogio.agora())
    t0 = relogio.monotonico()
    resto = [b async for b in gen]
    assert relogio.monotonico() - t0 <= 5.0
    assert all(_ler(b)["event"] == "ping" for b in resto)
    assert pub.contar(disp.id) == 0


async def test_revogar_no_mesmo_processo_fecha_na_hora(ctx, celular, relogio):
    _, disp = celular
    pub = sse_de(ctx)
    a = pub.abrir(disp)
    gen = fluxo(ctx, pub, a, None)
    await anext(gen)
    t0 = relogio.monotonico()
    await __import__("asyncio").to_thread(ctx.auth.revogar, disp.id)
    assert [b async for b in gen if "ping" not in b] == []
    assert relogio.monotonico() - t0 <= 2.5


async def test_ping_a_cada_15s(ctx, celular, relogio):
    _, disp = celular
    pub = sse_de(ctx)
    gen = fluxo(ctx, pub, pub.abrir(disp), None)
    await _proximo(gen, "ping")
    t0 = relogio.monotonico()
    assert (await _proximo(gen, "ping"))["data"] == {}
    assert relogio.monotonico() - t0 == pytest.approx(PING_S)
    await gen.aclose()


async def test_confirma_estado_e_publicar_por_nome(ctx, celular, novo_token, db, relogio):
    _, disp = celular
    pub = sse_de(ctx)
    await eventos_de(ctx).preparar()
    gen = fluxo(ctx, pub, pub.abrir(disp), None)
    await anext(gen)
    c = await __import__("asyncio").to_thread(
        confirmacoes.criar, db, relogio, descricao="desligar a TV da sala",
        pedido={"tipo": "casa.acao", "origem": "mcp"})
    conf = await _proximo(gen, "confirma")
    assert conf["data"]["pedido"] == c.id and conf["data"]["descricao"] == "desligar a TV da sala"
    # o estado que a casa manda ao hub vai ao SSE do celular
    hub = ctx.extras["hub"]
    tv = EstadoTv(id="tv-sala", nome="TV da sala", driver="roku", online=True)
    env = Envelope(t=Tipo.ESTADO, corpo=Estado(tvs=(tv,)), de="casa-sala", para="ayanami")
    for fn in hub._ganchos_receber[Tipo.ESTADO]:
        fn(None, env)
    est = await _proximo(gen, "estado")
    assert est["data"]["tvs"][0]["id"] == "tv-sala"
    assert pub.publicar("celular-pedro", "turno.texto", {"turno": "t1", "texto": "Oi"}) == 1
    assert pub.publicar("outro", "turno.texto", {"turno": "t1", "texto": "Oi"}) == 0
    assert (await _proximo(gen, "turno.texto"))["data"] == {"turno": "t1", "texto": "Oi"}
    # a mesma confirmação não volta na próxima varredura
    relogio.avancar(3)
    criar_evento(db, "lembrete", "x")
    await eventos_de(ctx).distribuir()
    assert (await _proximo(gen, "evento"))["data"]["titulo"] == "x"
    await gen.aclose()


async def test_rota_sse_relê_e_fecha_na_revogacao(app, ctx, celular, cliente, db, relogio):
    token, disp = celular
    seqs = [criar_evento(db, "lembrete", f"e{i}").seq for i in range(3)]
    async with cliente(app, token) as c:
        assert (await c.get("/v1/feed")).status_code == 200  # token no cache (TTL 5 s)
        with db.connection() as conn:
            marcar_revogado(conn, disp.id, relogio.agora())
        r = await c.get("/v1/eventos", headers={"Last-Event-ID": str(seqs[0])})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.startswith("retry: 3000")
    evs = [b for b in _blocos(r.text) if b["event"] == "evento"]
    assert [int(b["id"]) for b in evs] == seqs[1:]
    assert sse_de(ctx).contar(disp.id) == 0


async def test_sem_escopo_conversa_403(app, cliente, novo_token):
    token = novo_token("casa-sala", "casa")
    async with cliente(app, token) as c:
        assert (await c.get("/v1/eventos")).status_code == 403
