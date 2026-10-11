"""Marcação por regras locais (tarefa A1.2; spec §2, requirements A3).

Parágrafo → ``Trecho``s (narração/fala/pensamento/título, emoção, falante, gênero, idade) por
travessão, aspas, itálico, verbos de elocução (``verbos.toml``) e pontuação. Roda sempre (D2); o
Qwen (A1.3) só refina. Nada do texto muda (A9):

- os cortes são feitos **só em espaços** e os trechos não começam nem terminam com espaço, logo
  ``" ".join(t.texto for t in trechos) == frases.limpo(paragrafo.texto)``;
- as marcas da A1.1 (``MARCA_ITALICO``/``MARCA_TITULO``) são consumidas aqui (viram pensamento e
  título) e saem do ``texto`` (``frases.limpo``); o leitor não precisa conhecê-las;
- um trecho nunca atravessa duas frases (``Trecho.frase`` = índice da frase no parágrafo); a
  ``vozes.juntar`` junta de novo os vizinhos de mesma voz.

Regras de atribuição (falante, gênero, idade, emoção) olham a narração colada à fala: a que vem
logo depois (até o fim da frase) e, sem verbo nela, a que vem logo antes. Uma fala sem tag herda a
atribuição de outra fala do mesmo parágrafo. ``marcar_capitulo`` lembra o gênero/idade de cada
falante entre parágrafos. Itálico só vira pensamento com ≥ 3 palavras (ênfase de 1–2 palavras e
títulos de obra continuam narração).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

from magi.audiolivro.contratos import Emocao, Genero, Idade, Paragrafo, Tipo, Trecho
from magi.audiolivro.frases import MARCA_ITALICO, MARCA_TITULO, limpo

VERBOS_PATH = Path(__file__).parent / "verbos.toml"
#: Ordem de prioridade das emoções por verbo (spec §2; CARINHO exige vocativo e vem antes de
#: ALEGRE porque "sorriu para" contém "sorriu").
ORDEM_EMOCOES = (
    Emocao.GRITO,
    Emocao.SUSSURRO,
    Emocao.RAIVA,
    Emocao.MEDO,
    Emocao.TRISTE,
    Emocao.CARINHO,
    Emocao.ALEGRE,
    Emocao.IRONIA,
)
ITALICO_MIN_PALAVRAS = 3
FRASE_CURTA = 6  # palavras (TENSA: ≥ 2 frases curtas seguidas na narração)
JANELA = 80  # caracteres da narração colada olhados antes da fala

_TRAVESSAO_INICIO = re.compile(r"^[—–-] ")
_TRAVESSAO_FRASE = re.compile(r"(?<=[.!?:…] )[—–] ")
_TRAVESSAO_INTERNO = re.compile(r"(?<= )[—–](?= )|(?<= )-(?= )")
_ASPAS = re.compile(r"“[^”]*”?|«[^»]*»?|\"[^\"]*\"?")
_ASPAS_SIMPLES = re.compile(r"(?:(?<=^)|(?<=[\s—–(]))[‘'][^‘’']+[’'](?=$|[\s.,;:!?—–)])")
_PALAVRA = re.compile(r"[\wÀ-ÿ’'-]+")
_NOME = re.compile(r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'-]*")


@dataclass(frozen=True)
class _Lex:
    elocucao: tuple[str, ...]
    emocoes: dict[Emocao, tuple[str, ...]]
    vocativo: tuple[str, ...]
    genero: dict[str, tuple[str, ...]]  # "f"/"m" → termos
    idade: dict[str, tuple[str, ...]]  # "crianca"/"jovem"/"idoso" → termos
    nao_nome: frozenset[str]

    @property
    def verbos(self) -> tuple[str, ...]:
        extra = (v for e in ORDEM_EMOCOES for v in self.emocoes.get(e, ()))
        return (*self.elocucao, *extra)


def _lingua(idioma: str) -> str:
    return "en" if idioma.lower().startswith("en") else "pt"


@cache
def _lexico(lingua: str, caminho: Path = VERBOS_PATH) -> _Lex:
    with caminho.open("rb") as f:
        sec: dict[str, Any] = tomllib.load(f).get(lingua, {})

    def lista(k: str) -> tuple[str, ...]:
        return tuple(str(x).lower() for x in sec.get(k, ()))

    return _Lex(
        elocucao=lista("elocucao"),
        emocoes={e: lista(e.value) for e in ORDEM_EMOCOES},
        vocativo=lista("vocativo"),
        genero={"f": lista("feminino"), "m": lista("masculino")},
        idade={k: lista(k) for k in ("crianca", "jovem", "idoso")},
        nao_nome=frozenset(str(x) for x in sec.get("nao_nome", ())),
    )


@cache
def _padrao(termo: str) -> re.Pattern[str]:
    """Termo da lista como regex de palavra inteira (``*`` no fim = prefixo)."""
    if termo.endswith("*"):
        corpo = re.escape(termo[:-1]) + r"[\wÀ-ÿ]*"
    else:
        corpo = re.escape(termo)
    corpo = corpo.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![\wÀ-ÿ]){corpo}(?![\wÀ-ÿ])", re.IGNORECASE)


def _acha(termos: Iterable[str], texto: str) -> re.Match[str] | None:
    """Primeira ocorrência (mais à esquerda; empate → termo mais longo)."""
    melhor: re.Match[str] | None = None
    for t in termos:
        m = _padrao(t).search(texto)
        if m and (
            melhor is None
            or m.start() < melhor.start()
            or (m.start() == melhor.start() and m.end() > melhor.end())
        ):
            melhor = m
    return melhor


# --- rótulos por caractere -------------------------------------------------------------------

_N, _F, _P = 0, 1, 2  # narração, fala, pensamento


def _rotulos(texto: str, lingua: str, lex: _Lex) -> list[int]:
    rot = [_N] * len(texto)
    sem_marca = texto.lstrip(MARCA_ITALICO + MARCA_TITULO)
    abertura = len(texto) - len(sem_marca) if _TRAVESSAO_INICIO.match(sem_marca) else None
    if abertura is None:  # "Ela sorriu. — Oi." (travessão logo depois do fim de frase)
        m = _TRAVESSAO_FRASE.search(texto)
        abertura = m.start() if m else None
    if abertura is not None:
        atual, ini = _F, abertura
        for m in _TRAVESSAO_INTERNO.finditer(texto, abertura + 1):
            rot[ini : m.start()] = [atual] * (m.start() - ini)
            atual, ini = (_N if atual == _F else _F), m.start()
        rot[ini:] = [atual] * (len(texto) - ini)
    else:
        spans = [m.span() for m in _ASPAS.finditer(texto)]
        if lingua == "en" and _acha(lex.verbos, texto):
            spans += [m.span() for m in _ASPAS_SIMPLES.finditer(texto)]
        for a, b in spans:
            rot[a:b] = [_F] * (b - a)
        # itálico (pensamento) só fora das falas e longe de travessão
        for m in re.finditer(f"{MARCA_ITALICO}([^{MARCA_ITALICO}]*){MARCA_ITALICO}?", texto):
            dentro = m.group(1)
            if (
                len(_PALAVRA.findall(dentro)) >= ITALICO_MIN_PALAVRAS
                and not re.search("[—–]", dentro)
                and all(r == _N for r in rot[m.start() : m.end()])
            ):
                rot[m.start() : m.end()] = [_P] * (m.end() - m.start())
    return rot


def _cortes(texto: str, rot: list[int], fronteiras: Iterable[int]) -> list[int]:
    """Posições de espaço onde cortar: frases e trocas de rótulo (ajustadas ao espaço mais perto)."""
    cortes = {c for c in fronteiras if 0 < c < len(texto) - 1 and texto[c] == " "}
    for b in range(1, len(texto)):
        if rot[b] == rot[b - 1]:
            continue
        for d in range(len(texto)):
            esq, dir_ = b - 1 - d, b + d
            if esq >= 0 and texto[esq] == " ":
                cortes.add(esq)
                break
            if dir_ < len(texto) and texto[dir_] == " ":
                cortes.add(dir_)
                break
    return sorted(c for c in cortes if 0 < c < len(texto) - 1 and texto[c - 1] != " " and texto[c + 1] != " ")


# --- atribuição --------------------------------------------------------------------------------


@dataclass
class _Attr:
    falante: str | None = None
    genero: Genero | None = None
    idade: Idade | None = None
    emocao: Emocao = Emocao.NEUTRA
    tem_verbo: bool = False


def _genero_idade(a: _Attr, janela: str, lex: _Lex) -> re.Match[str] | None:
    """Gênero/idade do termo no começo da ``janela`` ("a moça", "o velho", "she")."""
    for g, termos in lex.genero.items():
        m = _acha(termos, janela)
        if m and m.start() == 0:
            a.genero = g  # type: ignore[assignment]
            for idade in ("crianca", "idoso", "jovem"):
                if _acha(lex.idade[idade], m.group(0)):
                    a.idade = idade  # type: ignore[assignment]
                    break
            return m
    return None


def _sujeito(narr: str, lex: _Lex) -> _Attr:
    """Falante/gênero/idade/emoção a partir de um pedaço de narração colado à fala."""
    a = _Attr()
    verbo = _acha(lex.verbos, narr)
    if verbo is None:
        return a
    a.tem_verbo = True
    for e in ORDEM_EMOCOES:
        if e is not Emocao.CARINHO and _acha(lex.emocoes[e], narr):
            a.emocao = e
            break
    depois = narr[verbo.end() :].lstrip(" ,")[:40]
    antes = narr[: verbo.start()].rstrip(" ,")[-40:]
    for janela, inicio in ((depois, True), (antes, False)):
        termo = None
        for g, termos in lex.genero.items():
            m = _acha(termos, janela)
            if m and (m.start() == 0 if inicio else m.end() == len(janela)):
                termo = m
                a.genero = g  # type: ignore[assignment]
                break
        if termo is not None:
            for idade in ("crianca", "idoso", "jovem"):
                if _acha(lex.idade[idade], termo.group(0)):
                    a.idade = idade  # type: ignore[assignment]
                    break
            return a
        par = rf"(?:{_NOME.pattern})(?: (?:{_NOME.pattern}))?"
        m = re.match(par, janela) if inicio else re.search(rf"{par}$", janela.rstrip(".,;:!?"))
        if m and m.group(0).split()[0] not in lex.nao_nome:
            a.falante = m.group(0)
            if inicio:  # aposto: "disse Ana, a moça da loja"
                _genero_idade(a, janela[m.end() :].lstrip(" ,"), lex)
            return a
    return a


def _atribuir(fala: str, depois: str, antes: str, lex: _Lex) -> _Attr:
    a = _sujeito(depois[:JANELA], lex)
    if not a.tem_verbo:
        a = _sujeito(antes[-JANELA:], lex)
    letras = [c for c in fala if c.isalpha()]
    if len(letras) >= 2 and all(c.isupper() for c in letras):
        a.emocao = Emocao.GRITO
    elif (
        a.emocao in (Emocao.NEUTRA, Emocao.ALEGRE)
        and _acha(lex.emocoes[Emocao.CARINHO], depois[:JANELA] + " " + antes[-JANELA:])
        and _acha(lex.vocativo, fala)
    ):
        a.emocao = Emocao.CARINHO
    return a


# --- marcação ----------------------------------------------------------------------------------


def _pedacos(paragrafo: Paragrafo, lingua: str, lex: _Lex) -> list[tuple[str, int, int]]:
    """(texto bruto, rótulo, frase) por pedaço, com as marcas ainda dentro."""
    texto = paragrafo.texto
    rot = _rotulos(texto, lingua, lex)
    fronteiras, pos = [], 0
    for f in paragrafo.frases[:-1]:
        pos += len(f)
        fronteiras.append(pos)
        pos += 1
    cortes = _cortes(texto, rot, fronteiras)
    out, ini = [], 0
    for c in [*cortes, len(texto)]:
        pedaco = texto[ini:c]
        conta = [0, 0, 0]
        for r in rot[ini:c]:
            conta[r] += 1
        frase = sum(1 for f in fronteiras if f < ini + 1)
        out.append((pedaco, max(range(3), key=lambda k: (conta[k], -k)), frase))
        ini = c + 1
    return out


def marcar(
    paragrafo: Paragrafo, idioma: str, memoria: dict[str, tuple[Genero | None, Idade | None]] | None = None
) -> list[Trecho]:
    """Trechos do parágrafo no idioma do **texto** (``Livro.idioma``), na ordem.

    ``memoria`` (opcional, de ``marcar_capitulo``): falante → (gênero, idade) já vistos."""
    texto = paragrafo.texto
    if not limpo(texto).strip():
        return []
    lingua = _lingua(idioma)
    lex = _lexico(lingua)
    pedacos = _pedacos(paragrafo, lingua, lex)
    if texto.lstrip(MARCA_ITALICO).startswith(MARCA_TITULO):
        return [Trecho(texto=limpo(p), tipo=Tipo.TITULO, par=paragrafo.n, frase=f) for p, _, f in pedacos]
    tipos = {_N: Tipo.NARRACAO, _F: Tipo.FALA, _P: Tipo.PENSAMENTO}
    trechos = [Trecho(texto=limpo(p), tipo=tipos[r], par=paragrafo.n, frase=f) for p, r, f in pedacos]
    grupos: list[list[int]] = []  # falas contíguas (mesma fala cortada por frase)
    for i, t in enumerate(trechos):
        if t.tipo is Tipo.FALA:
            if grupos and grupos[-1][-1] == i - 1:
                grupos[-1].append(i)
            else:
                grupos.append([i])
    attrs: list[_Attr] = []
    for k, g in enumerate(grupos):
        fim = grupos[k + 1][0] if k + 1 < len(grupos) else len(trechos)
        ini = grupos[k - 1][-1] + 1 if k else 0
        seguinte = trechos[g[-1] + 1 : fim]
        depois = " ".join(t.texto for t in seguinte if t.frase == seguinte[0].frase)
        antes = " ".join(t.texto for t in trechos[ini : g[0]])
        fala = " ".join(trechos[i].texto for i in g)
        attrs.append(_atribuir(fala, depois, antes, lex))
    # fala sem tag herda a atribuição de outra fala do parágrafo (mesmo falante)
    com_tag = [a for a in attrs if a.falante or a.genero or a.idade]
    base = com_tag[0] if com_tag else _Attr()
    for g, a in zip(grupos, attrs, strict=True):
        if not (a.falante or a.genero or a.idade):
            a.falante, a.genero, a.idade = base.falante, base.genero, base.idade
        if a.falante and memoria is not None:
            gen, idade = memoria.get(a.falante, (None, None))
            a.genero, a.idade = a.genero or gen, a.idade or idade
            memoria[a.falante] = (a.genero, a.idade)
        for i in g:
            trechos[i] = replace(
                trechos[i], emocao=a.emocao, falante=a.falante, genero=a.genero, idade=a.idade
            )
    if not grupos:
        trechos = _tensa(trechos)
    return trechos


def _tensa(trechos: list[Trecho]) -> list[Trecho]:
    """Narração sem fala: ``!`` ou ≥ 2 frases curtas seguidas → TENSA (spec §2)."""
    frases: dict[int, list[str]] = {}
    for t in trechos:
        frases.setdefault(t.frase, []).append(t.texto)
    frases = {
        f: ts for f, ts in frases.items() if all(t.tipo is Tipo.NARRACAO for t in trechos if t.frase == f)
    }
    curtas = {f for f, ts in frases.items() if len(_PALAVRA.findall(" ".join(ts))) < FRASE_CURTA}
    seguidas = {f for f in curtas if f - 1 in curtas or f + 1 in curtas}
    return [
        replace(t, emocao=Emocao.TENSA)
        if t.tipo is Tipo.NARRACAO and (t.frase in seguidas or "!" in t.texto)
        else t
        for t in trechos
    ]


def marcar_capitulo(paragrafos: Iterable[Paragrafo], idioma: str) -> list[list[Trecho]]:
    """``marcar`` de cada parágrafo, lembrando gênero/idade de cada falante no capítulo.
    O formato (lista por parágrafo) é o que a ``marcas_llm.mesclar`` (A1.3) recebe."""
    memoria: dict[str, tuple[Genero | None, Idade | None]] = {}
    return [marcar(p, idioma, memoria) for p in paragrafos]
