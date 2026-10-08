"""LearningBus (tarefa LM4.1; CA-02, ENG-001): ``publish`` não bloqueia e descarta o mais antigo."""

from __future__ import annotations

import asyncio
import time

import pytest

from magi.learning.bus import BUS_MAXSIZE, LearningBus


def test_maxsize_padrao_do_design() -> None:
    assert LearningBus().maxsize == BUS_MAXSIZE == 50
    with pytest.raises(ValueError):
        LearningBus(0)


async def test_ca02_fila_cheia_nao_bloqueia_e_descarta_o_mais_antigo() -> None:
    bus: LearningBus[int] = LearningBus(3)
    assert [bus.publish(i) for i in range(3)] == [True, True, True]
    t0 = time.perf_counter()
    assert bus.publish(3) is False  # cheia: entrou descartando o mais antigo
    assert bus.publish(4) is False
    assert time.perf_counter() - t0 < 0.05  # síncrono, sem espera
    assert len(bus) == 3 and bus.dropped == 2
    assert [await bus.get() for _ in range(3)] == [2, 3, 4]
    assert len(bus) == 0


async def test_publish_e_sincrono_sem_loop_esperando() -> None:
    """``publish`` é chamado do gancho do turno (função comum, sem ``await``)."""
    bus: LearningBus[str] = LearningBus(2)
    for i in range(1000):
        bus.publish(f"m{i}")
    assert bus.dropped == 998
    assert [bus.get_nowait(), bus.get_nowait()] == ["m998", "m999"]
    with pytest.raises(asyncio.QueueEmpty):
        bus.get_nowait()


async def test_get_espera_e_clear() -> None:
    bus: LearningBus[int] = LearningBus(5)
    waiter = asyncio.create_task(bus.get())
    await asyncio.sleep(0)
    assert not waiter.done()
    bus.publish(7)
    assert await asyncio.wait_for(waiter, 1) == 7
    bus.publish(1)
    bus.publish(2)
    assert bus.clear() == 2 and len(bus) == 0
