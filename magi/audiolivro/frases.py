"""Parágrafo → frases (tarefa A1.1): abreviações PT/EN (Sr., Dra., etc., Mr., Dr.), reticências,
travessão; não quebra dentro de aspas abertas. Nunca muda o texto (A9): ``" ".join`` das frases
reconstrói o parágrafo normalizado (espaços colapsados).

Marcas de formatação que os leitores (``epub``/``pdf``) deixam no texto para a marcação (A1.2):

- ``MARCA_ITALICO`` (``\\x1e``) abre e fecha cada trecho em itálico (``<i>``/``<em>`` do EPUB):
  ``"Ela pensou: \\x1eagora não\\x1e."``. Sempre aos pares, nunca em volta de espaço.
- ``MARCA_TITULO`` (``\\x1d``) é o primeiro caractere de um parágrafo título (``<h*>`` do EPUB,
  linha-título do PDF); o parágrafo título tem uma frase só.

Quem fala o texto tira as marcas com ``limpo``; elas não são texto do livro.
"""

from __future__ import annotations

import re

MARCA_ITALICO = "\x1e"
MARCA_TITULO = "\x1d"

# Abreviações que nunca terminam frase (comparadas sem o ponto, em minúsculas).
ABREVIACOES = frozenset(
    """sr sra srta srs sras dr dra drs dras prof profa profs mr mrs ms mme mlle st sto sta
    jr sn av pe fr gen cel cap ten sgt col lt gov pres rev exmo exma vs nº n no pág pag p pp
    vol cf ex fig cia ltda sr.ª dr.ª""".split()
)

_FECHA = "\"”»’')]" + MARCA_ITALICO
_ABRE = {"“": "”", "«": "»"}
_INICIO = re.compile(r"[\"“«‘'(\[¿¡\x1e]*[—–-]? ?[\"“«\x1e]*([A-ZÀ-ÖØ-Þ0-9])")
_ESPACO = re.compile(r"[^\S\x1c-\x1f]+")  # \s sem as marcas (\x1c–\x1f)


def normalizar(texto: str) -> str:
    """Espaços colapsados e pontas aparadas (única mudança permitida no texto)."""
    return _ESPACO.sub(" ", texto).strip(" ")


def limpo(texto: str) -> str:
    """Texto sem as marcas de formatação (para falar ou comparar)."""
    return texto.replace(MARCA_ITALICO, "").replace(MARCA_TITULO, "")


def _abreviacao(antes: str) -> bool:
    """``antes`` termina no ponto; a palavra antes dele é abreviação ou inicial?"""
    original = re.split(r"[\s\"“«(\[—–\x1e]", antes[:-1])[-1]
    palavra = original.lower()
    if not palavra:
        return False
    if palavra in ABREVIACOES:
        return True
    if len(original) == 1 and original.isupper():  # inicial: "J. R. R. Tolkien"
        return True
    return bool(re.fullmatch(r"(?:\w\.)+\w", palavra))  # "p.ex", "i.e", "a.C"


def dividir(texto: str) -> tuple[str, ...]:
    """Frases do parágrafo, na ordem."""
    t = normalizar(texto)
    if not t:
        return ()
    if t.startswith(MARCA_TITULO):
        return (t,)
    frases: list[str] = []
    inicio = 0
    abertas: list[str] = []  # aspas tipográficas abertas
    reta = False  # aspas retas (") abertas
    i, n = 0, len(t)
    while i < n:
        c = t[i]
        if c in _ABRE:
            abertas.append(_ABRE[c])
        elif abertas and c == abertas[-1]:
            abertas.pop()
        elif c == '"':
            reta = not reta
        if c in ".!?…":
            j = i
            while j + 1 < n and t[j + 1] in ".!?…":
                j += 1
            k = j
            while k + 1 < n and t[k + 1] in _FECHA:
                k += 1
                if t[k] == '"':
                    reta = False
                elif abertas and t[k] == abertas[-1]:
                    abertas.pop()
            fim_pontuacao = t[i : j + 1]
            if (
                not abertas
                and not reta
                and k + 1 < n
                and t[k + 1] == " "
                and _INICIO.match(t, k + 2)
                and not (fim_pontuacao == "." and _abreviacao(t[inicio : i + 1]))
            ):
                frases.append(t[inicio : k + 1])
                inicio = k + 2
            i = k + 1
            continue
        i += 1
    if inicio < n:
        frases.append(t[inicio:])
    return tuple(frases)


_PT = frozenset(
    "de que não um uma é com para em do da os as se no na mais mas ele ela por como foi seu sua "
    "você eu isso então também quando".split()
)
_EN = frozenset(
    "the and of to is in that it was he she you with for not but his her they this be at have "
    "had are from".split()
)


def detectar_idioma(texto: str) -> str:
    """``"pt-br"`` ou ``"en"`` pela contagem de palavras-função (empate → ``"pt-br"``)."""
    palavras = re.findall(r"[a-zà-ÿ]+", texto.lower())
    pt = sum(p in _PT for p in palavras)
    en = sum(p in _EN for p in palavras)
    return "en" if en > pt else "pt-br"
