"""Fila por TV (spec §10.4; C1.1b): série por TV, paralelo entre TVs, limite 8, coalescência.

CA-Y36. Sem ``sleep`` real: a ordem é controlada por ``asyncio.Event``.
"""

from __future__ import annotations

import asyncio

from magi.casa.driver import Motivo, ResTv
from magi.casa.falso import RelogioFalso
from magi.casa.fila import FilaTv, Vez


async def _ceder(n: int = 5) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def test_mesma_tv_em_serie_tvs_diferentes_em_paralelo(relogio):
    fila = FilaTv(relogio=relogio)
    solta = asyncio.Event()
    log: list[str] = []

    def tarefa(nome: str):
        async def fn(_v: Vez) -> ResTv:
            log.append(f"+{nome}")
            await solta.wait()
            log.append(f"-{nome}")
            return ResTv(True)

        return fn

    t1 = asyncio.create_task(fila.rodar("sala", tarefa("s1")))
    t2 = asyncio.create_task(fila.rodar("sala", tarefa("s2")))
    t3 = asyncio.create_task(fila.rodar("quarto", tarefa("q1")))
    await _ceder()
    assert log == ["+s1", "+q1"]  # s2 espera; o quarto não
    assert fila.pendentes("sala") == 2
    solta.set()
    assert all(r.ok for r in await asyncio.gather(t1, t2, t3))
    assert log.index("-s1") < log.index("+s2")
    assert fila.pendentes("sala") == 0


async def test_nono_na_fila_cheia_e_ocupada(relogio):
    fila = FilaTv(relogio=relogio)
    solta = asyncio.Event()
    chamados = 0

    async def fn(_v: Vez) -> ResTv:
        nonlocal chamados
        chamados += 1
        await solta.wait()
        return ResTv(True)

    tarefas = [asyncio.create_task(fila.rodar("sala", fn)) for _ in range(8)]
    await _ceder()
    res = await fila.rodar("sala", fn)
    assert not res.ok and res.motivo is Motivo.OCUPADA
    assert (await asyncio.wait_for(asyncio.shield(_outra(fila)), 1)).ok  # outra TV segue livre
    solta.set()
    assert all(r.ok for r in await asyncio.gather(*tarefas))
    assert chamados == 8


async def _outra(fila: FilaTv) -> ResTv:
    async def fn(_v: Vez) -> ResTv:
        return ResTv(True)

    return await fila.rodar("quarto", fn)


async def test_repeticao_coalescida_a_uma_por_80ms():
    relogio = RelogioFalso(10.0)
    fila = FilaTv(relogio=relogio)
    enviadas: list[float] = []

    async def tecla(_v: Vez) -> ResTv:
        enviadas.append(relogio())
        return ResTv(True)

    for _ in range(10):  # segurar vol+: uma acao a cada 20 ms durante 200 ms
        res = await fila.rodar("sala", tecla, repeticao=("tv.volume", "+1"))
        assert res.ok
        relogio.avancar(0.02)
    assert len(enviadas) == 3  # t = 0, 80 ms, 160 ms
    assert all(round(b - a, 3) >= 0.08 for a, b in zip(enviadas, enviadas[1:], strict=False))
    # outra tecla ou outra TV não são coalescidas
    assert (await fila.rodar("sala", tecla, repeticao=("tv.volume", "-1"))).detalhe == ""
    assert (await fila.rodar("quarto", tecla, repeticao=("tv.volume", "-1"))).detalhe == ""
    assert len(enviadas) == 5


async def test_comando_novo_aborta_a_vez_anterior(relogio):
    fila = FilaTv(relogio=relogio)
    vistas: list[Vez] = []
    solta = asyncio.Event()

    async def longa(v: Vez) -> ResTv:
        vistas.append(v)
        await solta.wait()
        return ResTv(not v.abortada)

    t = asyncio.create_task(fila.rodar("sala", longa))
    await _ceder()
    assert not vistas[0].abortada
    t2 = asyncio.create_task(fila.rodar("sala", longa))
    await _ceder()
    assert vistas[0].abortada
    solta.set()
    r1, r2 = await asyncio.gather(t, t2)
    assert not r1.ok and r2.ok
