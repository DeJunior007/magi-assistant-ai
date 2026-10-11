"""Leitor de PDF de texto com ``pymupdf`` (tarefa A1.1; D6; spec §1, requirements A1.2, A2).

Texto por blocos na ordem de leitura; junta hifenização; tira linhas que repetem em ≥ 60% das
páginas no topo/rodapé e números de página; capítulo por linha-título ou, sem achar, blocos de 10
páginas. Menos de 200 caracteres em 5 páginas → ``SemTexto`` (escaneado; A1.2). Idioma por
contagem de palavras-função PT/EN. Parágrafo título começa com ``MARCA_TITULO`` (ver ``frases``).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pymupdf

from magi.audiolivro.contratos import Capitulo, Livro, Paragrafo, livro_id
from magi.audiolivro.frases import MARCA_TITULO, detectar_idioma, dividir, limpo, normalizar

PAGINAS_POR_BLOCO = 10
MIN_CARACTERES = 200
PAGINAS_AMOSTRA = 5
REPETE = 0.6
BORDA = 0.1  # fração da altura considerada topo/rodapé

_NUM_PAGINA = re.compile(
    r"^(?:p[áa]g(?:ina)?\.?\s*|page\s+)?[-–—\s]*(\d{1,4}|[ivxlc]{1,7})[-–—\s]*"
    r"(?:(?:de|of|/)\s*\d{1,4})?$",
    re.IGNORECASE,
)
_TITULO = re.compile(
    r"^(?:(?:cap[íi]tulo|chapter|parte|part|livro|book|pr[óo]logo|prologue|ep[íi]logo|epilogue)"
    r"\b.*)$",
    re.IGNORECASE,
)
_ROMANO = re.compile(r"^[IVXLC]{1,7}\.?$")


class SemTexto(ValueError):
    """PDF sem camada de texto (escaneado): não lê e não gasta nada (A1.2)."""


@dataclass(frozen=True)
class _Cap:
    titulo: str
    paragrafos: tuple[str, ...]
    paginas: int


@dataclass(frozen=True)
class _Livro:
    titulo: str | None
    autor: str | None
    capitulos: tuple[_Cap, ...]


def _juntar_linhas(linhas: list[str]) -> str:
    """Linhas de um bloco → texto, juntando ``pala-\\nvra``."""
    out = ""
    for ln in (x.strip() for x in linhas):
        if not ln:
            continue
        if re.search(r"\w-$", out) and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out = f"{out} {ln}" if out else ln
    return normalizar(out)


def _chave(texto: str) -> str:
    return re.sub(r"\d+", "#", normalizar(texto).lower())


def _eh_titulo(texto: str) -> bool:
    t = normalizar(texto)
    if not t or len(t) > 60 or t[-1:] in ",;":
        return False
    if _ROMANO.match(t):
        return True
    return bool(_TITULO.match(t)) and len(t.split()) <= 8


def _parse(caminho: Path) -> _Livro:
    with pymupdf.open(caminho) as doc:
        meta = doc.metadata or {}
        paginas: list[list[tuple[str, bool]]] = []  # (texto, está na borda)
        for pg in doc:
            h = pg.rect.height or 1.0
            blocos = []
            for b in pg.get_text("blocks", sort=True):
                if b[6] != 0:
                    continue
                texto = _juntar_linhas(str(b[4]).split("\n"))
                if texto:
                    borda = b[1] < h * BORDA or b[3] > h * (1 - BORDA)
                    blocos.append((texto, borda))
            paginas.append(blocos)
        titulo_meta = (meta.get("title") or "").strip() or None
        autor_meta = (meta.get("author") or "").strip() or None

    amostra = sum(len(t) for p in paginas[:PAGINAS_AMOSTRA] for t, _ in p)
    if amostra < MIN_CARACTERES:
        raise SemTexto(f"{caminho.name}: sem camada de texto")

    total = len(paginas)
    repetidas: Counter[str] = Counter()
    for p in paginas:
        repetidas.update({_chave(t) for t, borda in p if borda})
    lixo = {k for k, c in repetidas.items() if total >= 3 and c >= REPETE * total}

    # (texto, página, é título)
    pars: list[tuple[str, int, bool]] = []
    for i, p in enumerate(paginas):
        for texto, borda in p:
            if borda and (_NUM_PAGINA.match(texto) or _chave(texto) in lixo):
                continue
            titulo = _eh_titulo(texto)
            if (
                pars
                and not titulo
                and not pars[-1][2]
                and pars[-1][1] == i - 1
                and texto[:1].islower()
                and pars[-1][0][-1:] not in '.!?…”"»:'
            ):  # parágrafo que continua da página anterior
                anterior = pars[-1][0]
                junto = anterior[:-1] + texto if re.search(r"\w-$", anterior) else f"{anterior} {texto}"
                pars[-1] = (junto, i, False)
                continue
            pars.append((texto, i, titulo))

    caps: list[_Cap] = []
    if any(t for _, _, t in pars):
        grupo: list[tuple[str, int, bool]] = []
        for par in pars:
            if par[2] and grupo and any(not t for _, _, t in grupo):
                caps.append(_cap(grupo))
                grupo = []
            grupo.append(par)
        if grupo:
            caps.append(_cap(grupo))
    else:
        for ini in range(0, total, PAGINAS_POR_BLOCO):
            grupo = [p for p in pars if ini <= p[1] < ini + PAGINAS_POR_BLOCO]
            if grupo:
                fim = min(ini + PAGINAS_POR_BLOCO, total)
                caps.append(_Cap(f"Páginas {ini + 1}–{fim}", tuple(t for t, _, _ in grupo), fim - ini))
    return _Livro(titulo_meta, autor_meta, tuple(caps))


def _cap(grupo: list[tuple[str, int, bool]]) -> _Cap:
    titulos = [t for t, _, ti in grupo if ti]
    nome = normalizar(titulos[0]) if titulos and grupo[0][2] else "Início"
    textos = tuple(MARCA_TITULO + t if ti else t for t, _, ti in grupo)
    return _Cap(nome, textos, grupo[-1][1] - grupo[0][1] + 1)


@lru_cache(maxsize=2)
def _parse_cache(caminho: str, mtime_ns: int, tamanho: int) -> _Livro:
    return _parse(Path(caminho))


def _livro(caminho: Path) -> _Livro:
    st = caminho.stat()
    return _parse_cache(str(caminho), st.st_mtime_ns, st.st_size)


def metadados(caminho: Path) -> Livro:
    """``Livro`` do PDF (título/autor do metadado ou do nome do arquivo, idioma, capítulos)."""
    lv = _livro(caminho)
    amostra = " ".join(p for c in lv.capitulos[:3] for p in c.paragrafos[:40])
    return Livro(
        id=livro_id(caminho, caminho.stat().st_size),
        caminho=caminho,
        titulo=lv.titulo or caminho.stem,
        autor=lv.autor,
        idioma=detectar_idioma(amostra),
        formato="pdf",
        capitulos=len(lv.capitulos),
        caracteres=sum(len(limpo(p)) for c in lv.capitulos for p in c.paragrafos),
    )


def capitulo(caminho: Path, n: int) -> Capitulo:
    """Capítulo ``n`` (0 = primeiro); ``Capitulo.paginas`` = páginas reais do trecho."""
    caps = _livro(caminho).capitulos
    if not 0 <= n < len(caps):
        raise IndexError(f"capítulo {n} fora de 0..{len(caps) - 1}")
    c = caps[n]
    paragrafos = tuple(Paragrafo(i, dividir(p)) for i, p in enumerate(c.paragrafos))
    return Capitulo(n, c.titulo, paragrafos, float(c.paginas))
