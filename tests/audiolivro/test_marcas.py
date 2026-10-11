"""A1.2 — marcação por regras (CA-A2)."""

from __future__ import annotations

import random

import pytest

from magi.audiolivro.contratos import Emocao, Paragrafo, Tipo
from magi.audiolivro.frases import MARCA_ITALICO as I
from magi.audiolivro.frases import MARCA_TITULO as T
from magi.audiolivro.frases import dividir, limpo
from magi.audiolivro.marcas import marcar, marcar_capitulo

N, F, P, TI = Tipo.NARRACAO, Tipo.FALA, Tipo.PENSAMENTO, Tipo.TITULO
E = Emocao


def _par(texto: str, n: int = 0) -> Paragrafo:
    return Paragrafo(n, dividir(texto))


# (texto, idioma, [(tipo, emoção)] por trecho, atributos da primeira fala ou None)
CASOS = [
    (
        "— Vem — disse ela. — Agora.",
        "pt-br",
        [(F, E.NEUTRA), (N, E.NEUTRA), (F, E.NEUTRA)],
        (None, "f", None),
    ),
    ("— Não sei — gritou o velho.", "pt-br", [(F, E.GRITO), (N, E.NEUTRA)], (None, "m", "idoso")),
    ("— Silêncio — sussurrou a menina.", "pt-br", [(F, E.SUSSURRO), (N, E.NEUTRA)], (None, "f", "crianca")),
    ("— Saia daqui! — rosnou Paul.", "pt-br", [(F, E.RAIVA), (N, E.NEUTRA)], ("Paul", None, None)),
    ("— E-eu não… — gaguejou o menino.", "pt-br", [(F, E.MEDO), (N, E.NEUTRA)], (None, "m", "crianca")),
    ("— Ele se foi — soluçou a mulher.", "pt-br", [(F, E.TRISTE), (N, E.NEUTRA)], (None, "f", None)),
    ("— Que piada — riu o rapaz.", "pt-br", [(F, E.ALEGRE), (N, E.NEUTRA)], (None, "m", "jovem")),
    ("— Que gênio — zombou Ana.", "pt-br", [(F, E.IRONIA), (N, E.NEUTRA)], ("Ana", None, None)),
    (
        "Ela acariciou o rosto dele. — Dorme, meu amor.",
        "pt-br",
        [(N, E.NEUTRA), (F, E.CARINHO)],
        (None, "f", None),
    ),
    ("— SOCORRO! — disse Maria.", "pt-br", [(F, E.GRITO), (N, E.NEUTRA)], ("Maria", None, None)),
    (
        "— Eu? — perguntou Maria Clara, irritada.",
        "pt-br",
        [(F, E.RAIVA), (N, E.NEUTRA)],
        ("Maria Clara", None, None),
    ),
    ("Ele abriu a porta e olhou o corredor vazio por um longo tempo.", "pt-br", [(N, E.NEUTRA)], None),
    ("Ele correu. Caiu. Levantou.", "pt-br", [(N, E.TENSA)] * 3, None),
    ("A casa estava em chamas!", "pt-br", [(N, E.TENSA)], None),
    (
        "Ela disse “volte logo” e saiu.",
        "pt-br",
        [(N, E.NEUTRA), (F, E.NEUTRA), (N, E.NEUTRA)],
        (None, "f", None),
    ),
    ("O guarda gritou «parem» para todos.", "pt-br", [(N, E.NEUTRA), (F, E.GRITO), (N, E.NEUTRA)], None),
    (
        f"Ela pensou: {I}isso não vai dar certo{I}. E saiu de casa sem olhar para trás.",
        "pt-br",
        [(N, E.NEUTRA), (P, E.NEUTRA), (N, E.NEUTRA)],
        None,
    ),
    (f"Era um {I}absurdo{I} completo, pensou ele enquanto a chuva caía.", "pt-br", [(N, E.NEUTRA)], None),
    (f"{T}Capítulo 1", "pt-br", [(TI, E.NEUTRA)], None),
    ("“Come here,” she said. “Now!”", "en", [(F, E.NEUTRA), (N, E.NEUTRA), (F, E.NEUTRA)], (None, "f", None)),
    ("“Run!” shouted the old man.", "en", [(F, E.GRITO), (N, E.NEUTRA)], (None, "m", "idoso")),
    ("“Don't move,” whispered the girl.", "en", [(F, E.SUSSURRO), (N, E.NEUTRA)], (None, "f", "crianca")),
    ("“Get out,” he snapped.", "en", [(F, E.RAIVA), (N, E.NEUTRA)], (None, "m", None)),
    ("“I-I can't,” stammered Tom.", "en", [(F, E.MEDO), (N, E.NEUTRA)], ("Tom", None, None)),
    ("“She's gone,” she sobbed.", "en", [(F, E.TRISTE), (N, E.NEUTRA)], (None, "f", None)),
    ("“Nice one,” laughed the young man.", "en", [(F, E.ALEGRE), (N, E.NEUTRA)], (None, "m", "jovem")),
    ("Paul said, “I am here.”", "en", [(N, E.NEUTRA), (F, E.NEUTRA)], ("Paul", None, None)),
    ("'Go away,' she snapped.", "en", [(F, E.RAIVA), (N, E.NEUTRA)], (None, "f", None)),
    ("He didn't know what to do, so he waited by the window.", "en", [(N, E.NEUTRA)], None),
    ("He ran. He fell. Silence.", "en", [(N, E.TENSA)] * 3, None),
    (f"{T}Chapter One", "en", [(TI, E.NEUTRA)], None),
]


@pytest.mark.parametrize(("texto", "idioma", "esperado", "attr"), CASOS)
def test_tabela(texto: str, idioma: str, esperado: list, attr: tuple | None) -> None:
    trechos = marcar(_par(texto, 3), idioma)
    assert [(t.tipo, t.emocao) for t in trechos] == esperado
    assert " ".join(t.texto for t in trechos) == limpo(texto)
    assert all(t.par == 3 for t in trechos)
    if attr is not None:
        fala = next(t for t in trechos if t.tipo is F)
        assert (fala.falante, fala.genero, fala.idade) == attr


def test_ao_menos_30_casos() -> None:
    assert len(CASOS) >= 30


def test_frase_do_trecho() -> None:
    trechos = marcar(_par("— Vem. Agora — sussurrou Paul. Ele saiu."), "pt-br")
    assert [t.frase for t in trechos] == [0, 1, 1, 2]
    assert [t.tipo for t in trechos] == [F, F, N, N]
    assert {t.falante for t in trechos if t.tipo is F} == {"Paul"}
    assert {t.emocao for t in trechos if t.tipo is F} == {E.SUSSURRO}


def test_aspas_simples_sem_verbo_nao_e_fala() -> None:
    trechos = marcar(_par("He thought of the word 'home' all night long."), "en")
    assert [t.tipo for t in trechos] == [N]


def test_vazio() -> None:
    assert marcar(Paragrafo(0, ()), "pt-br") == []


def test_capitulo_lembra_genero_do_falante() -> None:
    caps = marcar_capitulo(
        [_par("— Oi — disse Ana, a moça da loja."), _par("— Tchau — respondeu Ana.", 1)], "pt-br"
    )
    assert (caps[0][0].falante, caps[0][0].genero, caps[0][0].idade) == ("Ana", "f", "jovem")
    assert (caps[1][0].falante, caps[1][0].genero, caps[1][0].idade) == ("Ana", "f", "jovem")


# --- propriedade A9: concatenação == parágrafo (200 casos) ------------------------------------

_PECAS = [
    "— Vem",
    "— disse ela.",
    "“Olá,”",
    "«parem»",
    '"Go!"',
    "'hi,'",
    "she said.",
    "Ele correu.",
    "Caiu!",
    "E-eu…",
    "Sr. Silva chegou.",
    "— Agora.",
    f"{I}isso não vai dar certo{I}",
    f"{I}nunca{I}",
    "gritou o velho.",
    "O SOCORRO!",
    "Paul disse:",
    "x",
    "—",
    "“aberta",
    "«",
    "a  b",
    "fim.",
    "Mr. Smith laughed.",
    "",
    "a\x1e",
    "?",
    "‘quoted’ word",
]


@pytest.mark.parametrize("semente", range(200))
def test_concatenacao_igual_ao_paragrafo(semente: int) -> None:
    rnd = random.Random(semente)
    texto = " ".join(rnd.choice(_PECAS) for _ in range(rnd.randint(1, 12))).strip()
    if rnd.random() < 0.1:
        texto = T + texto
    frases = dividir(texto) or (texto,)
    idioma = rnd.choice(["pt-br", "en"])
    trechos = marcar(Paragrafo(0, frases), idioma)
    juntos = " ".join(frases)
    assert " ".join(t.texto for t in trechos) == limpo(juntos)
    assert all(t.texto and t.texto == t.texto.strip(" ") for t in trechos)
    assert all(0 <= t.frase < len(frases) for t in trechos)
