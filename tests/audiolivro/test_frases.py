"""Frases (A1.1): abreviações, reticências, aspas, travessão; A9 (join reconstrói o texto)."""

from __future__ import annotations

import pytest

from magi.audiolivro.frases import (
    MARCA_ITALICO,
    MARCA_TITULO,
    detectar_idioma,
    dividir,
    limpo,
    normalizar,
)

CASOS: list[tuple[str, tuple[str, ...]]] = [
    ("Ela saiu. Ele ficou.", ("Ela saiu.", "Ele ficou.")),
    ("Ela saiu! Ele ficou?", ("Ela saiu!", "Ele ficou?")),
    ("O quê?! Não pode.", ("O quê?!", "Não pode.")),
    ("O Sr. Silva chegou. Sentou.", ("O Sr. Silva chegou.", "Sentou.")),
    ("A Sra. Lima e a Dra. Ana vieram.", ("A Sra. Lima e a Dra. Ana vieram.",)),
    ("O Dr. Paulo riu. Depois chorou.", ("O Dr. Paulo riu.", "Depois chorou.")),
    ("Mr. Smith met Mrs. Jones. They talked.", ("Mr. Smith met Mrs. Jones.", "They talked.")),
    ("Dr. Who arrived. Ms. Pond waved.", ("Dr. Who arrived.", "Ms. Pond waved.")),
    ("Maçãs, peras etc. e uvas.", ("Maçãs, peras etc. e uvas.",)),
    ("Maçãs, peras etc. Depois, uvas.", ("Maçãs, peras etc.", "Depois, uvas.")),
    ("Ela esperou... E nada.", ("Ela esperou...", "E nada.")),
    ("Ela esperou… E nada.", ("Ela esperou…", "E nada.")),
    ("Ela esperou... e esperou.", ("Ela esperou... e esperou.",)),
    ("“Vem. Agora.” Ela foi.", ("“Vem. Agora.”", "Ela foi.")),
    ("“Vem. Agora”, disse ela. Foi.", ("“Vem. Agora”, disse ela.", "Foi.")),
    ('"Come. Now." She went.', ('"Come. Now."', "She went.")),
    ("«Fica. Por favor.» Ele ficou.", ("«Fica. Por favor.»", "Ele ficou.")),
    ("— Vem? — perguntou ela. — Agora.", ("— Vem? — perguntou ela.", "— Agora.")),
    ("— Vem — disse ela. Saiu.", ("— Vem — disse ela.", "Saiu.")),
    ("J. R. R. Tolkien escreveu. Muito.", ("J. R. R. Tolkien escreveu.", "Muito.")),
    ("Assim é. Depois veio.", ("Assim é.", "Depois veio.")),
    ("Ano 1999. Em 2000 mudou.", ("Ano 1999.", "Em 2000 mudou.")),
    ("Custa 3.5 reais. Barato.", ("Custa 3.5 reais.", "Barato.")),
    ("Sem ponto final", ("Sem ponto final",)),
    ("  Muitos   espaços.\n Aqui.  ", ("Muitos espaços.", "Aqui.")),
    ("Leia p.ex. este. Pronto.", ("Leia p.ex. este.", "Pronto.")),
    ("Ele (bravo.) Saiu.", ("Ele (bravo.)", "Saiu.")),
    (
        f"Ela pensou: {MARCA_ITALICO}agora não.{MARCA_ITALICO} Foi.",
        (f"Ela pensou: {MARCA_ITALICO}agora não.{MARCA_ITALICO}", "Foi."),
    ),
    (f"{MARCA_TITULO}Capítulo 1. O começo. Fim", (f"{MARCA_TITULO}Capítulo 1. O começo. Fim",)),
    ("", ()),
]


@pytest.mark.parametrize(("texto", "esperado"), CASOS)
def test_dividir(texto: str, esperado: tuple[str, ...]) -> None:
    frases = dividir(texto)
    assert frases == esperado
    assert " ".join(frases) == normalizar(texto)  # A9


def test_casos_suficientes() -> None:
    assert len(CASOS) >= 25


def test_limpo_tira_marcas() -> None:
    assert limpo(f"{MARCA_TITULO}A {MARCA_ITALICO}b{MARCA_ITALICO}") == "A b"


def test_idioma() -> None:
    assert detectar_idioma("Ela disse que não ia com ele para a casa da mãe.") == "pt-br"
    assert detectar_idioma("She said that he was not going to the house with her.") == "en"
    assert detectar_idioma("") == "pt-br"
