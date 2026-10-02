"""KeyPool: rodízio, espera progressiva, chaves do keyring (3.1, R21.2-R21.4)."""

from __future__ import annotations

import pytest

from magi.common.contracts import ApiKey, KeyPool, NoKeyAvailable
from magi.providers.keypool import RotatingKeyPool, is_model_quota


def _pool(clock, n: int = 3) -> RotatingKeyPool:
    keys = [ApiKey("openai", f"k{i}", f"s{i}") for i in range(1, n + 1)]
    return RotatingKeyPool("openai", keys, clock=clock)


def test_satisfaz_o_protocolo(clock):
    assert isinstance(_pool(clock), KeyPool)


def test_rodizio(clock):
    pool = _pool(clock)
    assert [pool.acquire().name for _ in range(5)] == ["k1", "k2", "k3", "k1", "k2"]


def test_429_poe_em_espera_e_pula_a_chave(clock):
    pool = _pool(clock)
    k1 = pool.acquire()
    pool.mark_failed(k1, 429)
    assert pool.available() == 2
    assert [pool.acquire().name for _ in range(4)] == ["k2", "k3", "k2", "k3"]
    clock.advance(60)
    assert pool.available() == 3


def test_espera_por_modelo_nao_tira_a_chave_dos_outros_modelos(clock):
    pool = _pool(clock, 2)
    k1 = pool.acquire("m-a")
    pool.mark_failed(k1, 429, "m-a")
    assert pool.available() == 2 and pool.available("m-a") == 1 and pool.available("m-b") == 2
    assert [pool.acquire("m-a").name for _ in range(2)] == ["k2", "k2"]
    assert pool.acquire("m-b").name == "k1" and pool.acquire().name in {"k1", "k2"}
    pool.mark_failed(pool.acquire("m-a"), 429, "m-a")
    with pytest.raises(NoKeyAvailable, match="para m-a"):
        pool.acquire("m-a")
    pool.mark_ok(k1, "m-a")
    assert pool.acquire("m-a").name == "k1"
    clock.advance(60)
    assert pool.available("m-a") == 2


def test_detecta_cota_zerada_do_modelo():
    assert is_model_quota(429, "Quota exceeded for metric: x_free_tier_requests, limit: 0, model: g-3")
    assert is_model_quota(429, "{'quotaValue': '0'}")
    assert not is_model_quota(429, "Quota exceeded, limit: 10, model: g-3")
    assert not is_model_quota(429, "Rate limit reached for requests")
    assert not is_model_quota(403, "limit: 0")


@pytest.mark.parametrize("status", [401, 403, 429])
def test_status_de_espera(clock, status):
    pool = _pool(clock, 1)
    pool.mark_failed(pool.acquire(), status)
    assert pool.available() == 0


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_outros_status_nao_tiram_a_chave(clock, status):
    pool = _pool(clock, 1)
    pool.mark_failed(pool.acquire(), status)
    assert pool.available() == 1


def test_espera_progressiva_dobra_ate_uma_hora(clock):
    pool = _pool(clock, 1)
    key = pool.acquire()
    waits = []
    for _ in range(9):
        pool.mark_failed(key, 429)
        start = clock.now
        while pool.available() == 0:
            clock.advance(1)
        waits.append(clock.now - start)
    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600, 3600]


def test_sucesso_zera_a_espera(clock):
    pool = _pool(clock, 1)
    key = pool.acquire()
    pool.mark_failed(key, 429)
    clock.advance(60)
    pool.mark_failed(key, 429)  # segunda falha seguida: 120 s
    clock.advance(119)
    assert pool.available() == 0
    clock.advance(1)
    pool.mark_ok(pool.acquire())
    pool.mark_failed(key, 429)  # depois de um sucesso volta a 60 s
    clock.advance(60)
    assert pool.available() == 1


def test_todas_indisponiveis(clock):
    pool = _pool(clock, 2)
    for _ in range(2):
        pool.mark_failed(pool.acquire(), 401)
    with pytest.raises(NoKeyAvailable, match="em espera"):
        pool.acquire()


def test_sem_chaves(clock):
    with pytest.raises(NoKeyAvailable, match="nenhuma chave"):
        RotatingKeyPool("x", [], clock=clock).acquire()


def test_le_do_keyring_pelos_nomes_e_ignora_ausentes(clock):
    vault = {"a": "segredo-a", "c": "segredo-c"}

    def getter(name):
        if name == "quebrada":
            raise RuntimeError("keyring travado")
        return vault.get(name)

    pool = RotatingKeyPool.from_keyring("openai", ["a", "b", "quebrada", "c"], get_secret=getter, clock=clock)
    assert pool.names() == ("a", "c")
    key = pool.acquire()
    assert key.secret == "segredo-a"
    assert "segredo" not in repr(key)
