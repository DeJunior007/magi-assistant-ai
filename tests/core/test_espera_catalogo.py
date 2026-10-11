"""E2.3: o ``magi/core/espera.yaml`` real passa no linter e cabe no cache de TTS (R3.1, R4, CA-03).

Moldes (ata 2026-10-11 §4.1): ``honesta`` roda no molde cru (``{jogo}`` = 1 palavra); o preenchido
com 3 jogos falsos só precisa ser cacheável (``Phrases.cacheable``), porque nome com dígito é dado
do Pedro, não fala dela."""

from __future__ import annotations

import random
import warnings
from pathlib import Path

import pytest

import magi.core.espera as espera_mod
from magi.core.espera import JOGO_MAX, Catalogo, Cota, aberturas_repetidas, demorado, escolher, honesta
from magi.core.tts import Phrases

YAML = Path(espera_mod.__file__).with_name("espera.yaml")
JOGOS_FALSOS = ("Hollow Knight", "Persona 5", "Baldur's Gate 3")


@pytest.fixture(scope="module")
def cat() -> Catalogo:
    return Catalogo.load(YAML)


@pytest.fixture(scope="module")
def phrases() -> Phrases:
    return Phrases.load()


def test_catalogo_real_carrega_chaves_do_acordo(cat: Catalogo) -> None:
    assert cat.get("geral") is not None and cat.topicos[-1].nome == "geral"
    assert "cansei" in cat.sem_espera and "hoje" in cat.sinais_so_acompanhados
    assert not demorado(cat, "como foi o seu dia hoje")  # "hoje" sozinho não basta


def test_frases_honestas_e_cacheaveis(cat: Catalogo, phrases: Phrases) -> None:
    for t in cat.topicos:
        for f in t.frases:
            assert honesta(f) == [], (t.nome, f)
            assert phrases.cacheable(f), (t.nome, f)


def test_moldes_cru_honestos_e_preenchidos_cacheaveis(cat: Catalogo, phrases: Phrases) -> None:
    moldes = [(t.nome, m) for t in cat.topicos for m in t.moldes]
    assert moldes
    for nome, m in moldes:
        assert "{jogo}" in m, (nome, m)
        assert honesta(m.replace("{jogo}", "Jogo")) == [], (nome, m)
        for jogo in JOGOS_FALSOS:
            assert len(jogo) <= JOGO_MAX
            assert phrases.cacheable(m.replace("{jogo}", jogo)), (nome, m, jogo)


def test_escolher_no_catalogo_real_sai_cacheavel(cat: Catalogo, phrases: Phrases) -> None:
    rng = random.Random(3)
    pedidos = ("pesquisa o preço da placa", "como passo desse chefe", "o que saiu de notícia")
    for texto in pedidos:
        for jogo in (None, *JOGOS_FALSOS):
            f = escolher(cat, texto, Cota(), rng, jogo=jogo)
            assert f is not None and phrases.cacheable(f), (texto, jogo, f)


def test_aberturas_repetidas_so_avisam(cat: Catalogo) -> None:
    for aviso in aberturas_repetidas(cat):  # ata §4.2: aviso, não reprovação
        warnings.warn(f"espera.yaml: {aviso}", stacklevel=1)
