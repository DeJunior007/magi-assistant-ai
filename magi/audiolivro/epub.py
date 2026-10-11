"""Leitor de EPUB (tarefa A1.1; spec §1, requirements A1–A2).

OPF → spine → XHTML, só ``zipfile`` + ``xml.etree`` + ``html.parser``. Pula ``nav``/``toc`` e notas
(``epub:type="footnote|endnote"``, e a chamada ``noteref``); ``<h*>`` vira parágrafo título
(``MARCA_TITULO`` no começo); itálico (``<i>``/``<em>``) fica entre ``MARCA_ITALICO`` para a A1.2
(ver ``frases``). Cada item de leitura do spine com texto é um capítulo.
Metadados: título, autor, idioma (``dc:language``; sem ele, palavras-função).
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Livro, Paragrafo, livro_id
from magi.audiolivro.frases import (
    MARCA_ITALICO,
    MARCA_TITULO,
    detectar_idioma,
    dividir,
    limpo,
    normalizar,
)

CHARS_POR_PAGINA = ConfigAudiolivro().chars_por_pagina

_BLOCOS = frozenset(
    "p div li blockquote dd dt pre section article header footer figcaption td th tr table "
    "ul ol dl h1 h2 h3 h4 h5 h6 hr".split()
)
_VAZIOS = frozenset("br img hr meta link input col area base wbr source".split())
_PULA_TAGS = frozenset("head script style nav sup svg math".split())
_NOTAS = re.compile(r"\b(footnotes?|endnotes?|rearnotes?|notes?|noteref|toc|landmarks|page-list)\b")
_TITULOS = frozenset("h1 h2 h3 h4 h5 h6".split())


class EpubInvalido(ValueError):
    """Arquivo que não é EPUB legível (zip/OPF quebrado)."""


class _Xhtml(HTMLParser):
    """Coleta parágrafos (texto com marcas) de um XHTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragrafos: list[str] = []
        self._buf: list[str] = []
        self._titulo = 0
        self._pilha: list[tuple[str, bool]] = []  # (tag, pulando a partir dela)

    @property
    def _pulando(self) -> bool:
        return any(p for _, p in self._pilha)

    def _flush(self) -> None:
        texto = _arrumar_italico(normalizar("".join(self._buf)))
        self._buf = []
        if limpo(texto).strip():
            if self._titulo:
                texto = MARCA_TITULO + limpo(texto)
            self.paragrafos.append(texto)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VAZIOS:
            if tag == "br" and not self._pulando:
                self._buf.append(" ")
            return
        d = dict(attrs)
        tipo = (d.get("epub:type") or "") + " " + (d.get("role") or "").replace("doc-", "")
        pula = tag in _PULA_TAGS or bool(_NOTAS.search(tipo))
        if tag == "a" and "noteref" in tipo:
            pula = True
        if not self._pulando and (tag in _BLOCOS):
            self._flush()
        self._pilha.append((tag, pula))
        if self._pulando:
            return
        if tag in _TITULOS:
            self._titulo += 1
        elif tag in ("i", "em"):
            self._buf.append(MARCA_ITALICO)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and not self._pulando:
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VAZIOS or not any(t == tag for t, _ in self._pilha):
            return
        while self._pilha:
            t, _ = self._pilha[-1]
            pulando = self._pulando
            self._pilha.pop()
            if not pulando:
                if t in ("i", "em"):
                    self._buf.append(MARCA_ITALICO)
                if t in _BLOCOS:
                    self._flush()
                if t in _TITULOS:
                    self._titulo -= 1
            if t == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self._pulando:
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def _arrumar_italico(texto: str) -> str:
    """Marcas aos pares, sem espaço por dentro e sem par vazio."""
    if texto.count(MARCA_ITALICO) % 2:
        texto = texto.replace(MARCA_ITALICO, "")

    def dentro(m: re.Match[str]) -> str:
        a, corpo, b = m.group(1), m.group(2), m.group(3)
        return f"{a}{MARCA_ITALICO}{corpo}{MARCA_ITALICO}{b}" if corpo else a + b

    texto = re.sub(r"\x1e( ?)(.*?)( ?)\x1e", dentro, texto)
    return normalizar(texto)


@dataclass(frozen=True)
class _Livro:
    titulo: str | None
    autor: str | None
    idioma: str | None
    capitulos: tuple[tuple[str, ...], ...]  # parágrafos (com marcas) por capítulo


def _texto(el: ET.Element | None) -> str | None:
    if el is None or not (el.text or "").strip():
        return None
    return normalizar(el.text or "")


def _ler_opf(z: zipfile.ZipFile) -> tuple[str, ET.Element]:
    cont = ET.fromstring(z.read("META-INF/container.xml"))
    root = cont.find(".//{*}rootfile")
    if root is None or not root.get("full-path"):
        raise EpubInvalido("container.xml sem rootfile")
    caminho = root.get("full-path") or ""
    return caminho, ET.fromstring(z.read(caminho))


def _parse(caminho: Path) -> _Livro:
    try:
        with zipfile.ZipFile(caminho) as z:
            opf_caminho, opf = _ler_opf(z)
            base = posixpath.dirname(opf_caminho)
            meta = opf.find("{*}metadata")
            titulo = _texto(meta.find("{*}title")) if meta is not None else None
            autor = _texto(meta.find("{*}creator")) if meta is not None else None
            idioma = _texto(meta.find("{*}language")) if meta is not None else None
            manifest = {it.get("id"): it for it in opf.iterfind("{*}manifest/{*}item") if it.get("id")}
            spine = opf.find("{*}spine")
            toc_id = spine.get("toc") if spine is not None else None
            caps: list[tuple[str, ...]] = []
            for ref in opf.iterfind("{*}spine/{*}itemref"):
                item = manifest.get(ref.get("idref"))
                if item is None or ref.get("linear") == "no" or ref.get("idref") == toc_id:
                    continue
                props = (item.get("properties") or "").split()
                href = item.get("href") or ""
                tipo = item.get("media-type") or ""
                nome = posixpath.basename(href).lower()
                if "nav" in props or "ncx" in tipo or re.match(r"(nav|toc)\b", nome):
                    continue
                parser = _Xhtml()
                dados = z.read(posixpath.normpath(posixpath.join(base, href)))
                parser.feed(dados.decode("utf-8", errors="replace"))
                parser.close()
                if parser.paragrafos:
                    caps.append(tuple(parser.paragrafos))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as e:
        raise EpubInvalido(f"{caminho.name}: {e}") from e
    return _Livro(titulo, autor, idioma.lower() if idioma else None, tuple(caps))


@lru_cache(maxsize=2)
def _parse_cache(caminho: str, mtime_ns: int, tamanho: int) -> _Livro:
    return _parse(Path(caminho))


def _livro(caminho: Path) -> _Livro:
    st = caminho.stat()
    return _parse_cache(str(caminho), st.st_mtime_ns, st.st_size)


def metadados(caminho: Path) -> Livro:
    """``Livro`` sem extrair o texto todo (título, autor, idioma, nº de capítulos, caracteres)."""
    lv = _livro(caminho)
    idioma = lv.idioma or detectar_idioma(" ".join(limpo(p) for c in lv.capitulos[:3] for p in c[:40]))
    return Livro(
        id=livro_id(caminho, caminho.stat().st_size),
        caminho=caminho,
        titulo=lv.titulo or caminho.stem,
        autor=lv.autor,
        idioma=idioma,
        formato="epub",
        capitulos=len(lv.capitulos),
        caracteres=sum(len(limpo(p)) for c in lv.capitulos for p in c),
    )


def capitulo(caminho: Path, n: int) -> Capitulo:
    """Capítulo ``n`` (0 = primeiro item de leitura do spine) com parágrafos e frases."""
    caps = _livro(caminho).capitulos
    if not 0 <= n < len(caps):
        raise IndexError(f"capítulo {n} fora de 0..{len(caps) - 1}")
    paragrafos = tuple(Paragrafo(i, dividir(p)) for i, p in enumerate(caps[n]))
    titulo = next((limpo(p) for p in caps[n] if p.startswith(MARCA_TITULO)), f"Capítulo {n + 1}")
    cap = Capitulo(n, titulo, paragrafos, 0.0)
    return Capitulo(n, titulo, paragrafos, round(cap.caracteres / CHARS_POR_PAGINA, 2))
