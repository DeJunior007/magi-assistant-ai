"""EPUB (A1.1, CA-A1): fixture gerada com ``zipfile`` (3 capítulos, ``nav``, notas, itálico)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from magi.audiolivro import epub
from magi.audiolivro.contratos import livro_id
from magi.audiolivro.frases import MARCA_ITALICO as I
from magi.audiolivro.frases import MARCA_TITULO as T

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles></container>"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>O Livro de Teste</dc:title><dc:creator>Ana Autora</dc:creator>
{lang}</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="capa" href="capa.xhtml" media-type="application/xhtml+xml"/>
<item id="c1" href="texto/c1.xhtml" media-type="application/xhtml+xml"/>
<item id="c2" href="texto/c2.xhtml" media-type="application/xhtml+xml"/>
<item id="c3" href="texto/c3.xhtml" media-type="application/xhtml+xml"/>
<item id="notas" href="texto/notas.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine toc="ncx"><itemref idref="nav"/><itemref idref="capa"/><itemref idref="c1"/>
<itemref idref="c2"/><itemref idref="c3"/><itemref idref="notas" linear="no"/></spine>
</package>"""

XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>x</title><style>p {{ color: red }}</style></head><body>{corpo}</body></html>"""

NAV = '<nav epub:type="toc"><ol><li><a href="texto/c1.xhtml">Capítulo 1</a></li></ol></nav>'
CAPA = '<div><img src="capa.jpg" alt="Capa"/></div>'
C1 = """<h1>Capítulo 1</h1>
<p>Era uma vez uma casa. Ela tinha portas<a epub:type="noteref" href="notas.xhtml#n1">1</a>.</p>
<p>— Vem — disse ela.<br/>— Agora.</p>
<aside epub:type="footnote" id="n1"><p>Nota de rodapé que não se lê.</p></aside>"""
C2 = """<section><h2>Capítulo 2</h2>
<p>Ele pensou: <i>não vou </i>sair. O Sr. Silva &amp; a Dra. Ana riram.</p>
<div><p>Parágrafo   com
quebras de linha.</p></div></section>"""
C3 = """<h1>Capítulo <em>3</em></h1><p>Fim <em>mesmo</em>. Acabou&#8230; Sim.</p>
<section epub:type="endnotes"><p>Nota final.</p></section>"""
NOTAS = '<aside epub:type="footnote"><p>1. Nota.</p></aside>'


def _epub(pasta: Path, lang: str = "<dc:language>pt-BR</dc:language>") -> Path:
    caminho = pasta / "livro.epub"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF.format(lang=lang))
        z.writestr("OEBPS/toc.ncx", "<ncx/>")
        for nome, corpo in (
            ("nav.xhtml", NAV),
            ("capa.xhtml", CAPA),
            ("texto/c1.xhtml", C1),
            ("texto/c2.xhtml", C2),
            ("texto/c3.xhtml", C3),
            ("texto/notas.xhtml", NOTAS),
        ):
            z.writestr(f"OEBPS/{nome}", XHTML.format(corpo=corpo))
    return caminho


def test_metadados(tmp_path: Path) -> None:
    caminho = _epub(tmp_path)
    livro = epub.metadados(caminho)
    assert livro.titulo == "O Livro de Teste" and livro.autor == "Ana Autora"
    assert livro.idioma == "pt-br" and livro.formato == "epub" and livro.capitulos == 3
    assert livro.id == livro_id(caminho, caminho.stat().st_size)
    assert livro.caracteres == sum(
        len(p.texto.replace(I, "").replace(T, ""))
        for n in range(3)
        for p in epub.capitulo(caminho, n).paragrafos
    )


def test_paragrafos_exatos(tmp_path: Path) -> None:
    caminho = _epub(tmp_path)
    textos = [[p.texto for p in epub.capitulo(caminho, n).paragrafos] for n in range(3)]
    assert textos == [
        [f"{T}Capítulo 1", "Era uma vez uma casa. Ela tinha portas.", "— Vem — disse ela. — Agora."],
        [
            f"{T}Capítulo 2",
            f"Ele pensou: {I}não vou{I} sair. O Sr. Silva & a Dra. Ana riram.",
            "Parágrafo com quebras de linha.",
        ],
        [f"{T}Capítulo 3", f"Fim {I}mesmo{I}. Acabou… Sim."],
    ]


def test_capitulo_frases_e_titulo(tmp_path: Path) -> None:
    caminho = _epub(tmp_path)
    cap = epub.capitulo(caminho, 1)
    assert cap.n == 1 and cap.titulo == "Capítulo 2"
    assert cap.paragrafos[1].n == 1
    assert cap.paragrafos[1].frases == (
        f"Ele pensou: {I}não vou{I} sair.",
        "O Sr. Silva & a Dra. Ana riram.",
    )
    assert cap.paginas == round(cap.caracteres / epub.CHARS_POR_PAGINA, 2)
    assert epub.capitulo(caminho, 2).titulo == "Capítulo 3"


def test_livro_capitulo_preguicoso(tmp_path: Path) -> None:
    livro = epub.metadados(_epub(tmp_path))
    assert livro.capitulo(0).paragrafos[1].frases == ("Era uma vez uma casa.", "Ela tinha portas.")


def test_idioma_sem_dc_language(tmp_path: Path) -> None:
    assert epub.metadados(_epub(tmp_path, lang="")).idioma == "pt-br"


def test_fora_do_intervalo(tmp_path: Path) -> None:
    with pytest.raises(IndexError):
        epub.capitulo(_epub(tmp_path), 3)


def test_invalido(tmp_path: Path) -> None:
    ruim = tmp_path / "ruim.epub"
    ruim.write_bytes(b"isto nao e zip")
    with pytest.raises(epub.EpubInvalido):
        epub.metadados(ruim)
