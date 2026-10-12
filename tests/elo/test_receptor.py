"""Receptor do elo: CA-Y5 (idempotência por id e 1008 após 10 inválidos em 60 s)."""

from __future__ import annotations

import json

from magi.elo.mensagens import (
    Acao,
    AcaoOk,
    AcaoPedido,
    AcaoResultado,
    Bate,
    Envelope,
    Tipo,
    decode,
    encode,
    responder,
)
from magi.elo.receptor import FECHA_POLITICA, Receptor


class Relogio:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _acao() -> Envelope:
    return Envelope(
        t=Tipo.ACAO, corpo=Acao(pedido=AcaoPedido(intent="tv.mute"), origem="pwa"), de="ayanami", para="casa"
    )


async def test_ca_y5_acao_repetida_executa_uma_vez() -> None:
    chamadas: list[str] = []

    def handler(env: Envelope) -> Envelope:
        chamadas.append(env.id)
        return responder(env, Tipo.ACAO_OK, AcaoOk(resultado=AcaoResultado(ok=True, fala="Mudo.")), de="casa")

    rec = Receptor("casa", handler, Relogio())
    raw = encode(_acao())
    saidas = [await rec.receber(raw) for _ in range(3)]
    assert len(chamadas) == 1
    assert saidas[0].resposta is not None
    assert {s.resposta for s in saidas} == {saidas[0].resposta}
    assert [s.repetido for s in saidas] == [False, True, True]
    r = decode(saidas[0].resposta)
    assert r.t is Tipo.ACAO_OK and r.resp == json.loads(raw)["id"]


async def test_handler_async_e_sem_resposta() -> None:
    vistos: list[Tipo] = []

    async def handler(env: Envelope) -> None:
        vistos.append(env.t)

    rec = Receptor("ayanami", handler, Relogio())
    s = await rec.receber(encode(Envelope(t=Tipo.BATE, corpo=Bate(seq=1), de="pc", para="ayanami")))
    assert s.resposta is None and s.fechar is None and vistos == [Tipo.BATE]


async def test_erro_do_handler_vira_interno_e_nao_reexecuta() -> None:
    n = 0

    def handler(env: Envelope) -> Envelope:
        nonlocal n
        n += 1
        raise RuntimeError("segredo sk-falso")

    rec = Receptor("casa", handler, Relogio())
    raw = encode(_acao())
    a = await rec.receber(raw)
    b = await rec.receber(raw)
    assert n == 1 and a.resposta == b.resposta
    erro = decode(a.resposta or "")
    assert erro.t is Tipo.ERRO and erro.corpo.codigo == "interno"  # type: ignore[union-attr]
    assert "sk-falso" not in (a.resposta or "")


async def test_cache_guarda_so_os_ultimos() -> None:
    n = 0

    def handler(env: Envelope) -> None:
        nonlocal n
        n += 1

    rec = Receptor("casa", handler, Relogio(), cache=2)
    envs = [_acao() for _ in range(3)]
    for e in envs:
        await rec.receber(encode(e))
    assert envs[0].id not in rec and envs[2].id in rec
    await rec.receber(encode(envs[0]))
    assert n == 4


async def test_ca_y5_dez_invalidos_em_60s_fecham_1008() -> None:
    rel = Relogio()
    rec = Receptor("ayanami", lambda env: None, rel)
    ruim = json.dumps({"v": 1, "t": "xyz", "de": "celular-pedro", "id": "x"})
    for i in range(9):
        s = await rec.receber(ruim)
        assert s.fechar is None
        erro = decode(s.resposta or "")
        assert erro.t is Tipo.ERRO and erro.corpo.codigo == "invalido" and erro.para == "celular-pedro"  # type: ignore[union-attr]
        rel.t += 5 if i else 0
    s = await rec.receber("{lixo")
    assert s.fechar == FECHA_POLITICA
    assert decode(s.resposta or "").para == "desconhecido"


async def test_invalidos_espalhados_nao_fecham() -> None:
    rel = Relogio()
    rec = Receptor("ayanami", lambda env: None, rel)
    for _ in range(30):
        s = await rec.receber("{lixo")
        assert s.fechar is None
        rel.t += 7  # 9 por janela de 60 s
