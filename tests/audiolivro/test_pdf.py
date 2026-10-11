"""PDF (A1.1, CA-A1, A1.2): fixtures geradas com ``pymupdf`` em ``tmp_path``."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from magi.audiolivro import pdf
from magi.audiolivro.frases import MARCA_TITULO as T

P1 = "Era uma vez uma casa muito antiga no alto do morro, onde ninguém mais morava."
P2 = "Ela abriu a porta. O vento entrou com força e levou as folhas."


def _pagina(doc: pymupdf.Document, n: int, blocos: list[str], cabecalho: bool = True) -> None:
    pg = doc.new_page(width=420, height=600)
    if cabecalho:
        pg.insert_text((40, 30), "O Livro de Teste", fontsize=9)
        pg.insert_text((200, 585), str(n), fontsize=9)
    y = 90.0
    for bloco in blocos:
        pg.insert_text((40, y), bloco, fontsize=11)
        y += 16 * (bloco.count("\n") + 1) + 40


def _pdf_capitulos(pasta: Path) -> Path:
    doc = pymupdf.open()
    _pagina(
        doc,
        1,
        [
            "Capítulo 1",
            "Era uma vez uma casa muito an-\ntiga no alto do morro, onde\nninguém mais morava.",
            P2,
        ],
    )
    _pagina(
        doc,
        2,
        [
            "Que fizeram eles depois de tudo\nisso? Nada.",
            "Ele ficou ali parado, olhando a\nestrada que levava",
        ],
    )
    _pagina(doc, 3, ["para longe. Era tarde.", "Capítulo 2", "Ela voltou. The end? Não."])
    doc.set_metadata({"title": "O Livro de Teste", "author": "Ana Autora"})
    caminho = pasta / "livro.pdf"
    doc.save(caminho)
    doc.close()
    return caminho


def test_capitulos_e_paragrafos_exatos(tmp_path: Path) -> None:
    caminho = _pdf_capitulos(tmp_path)
    livro = pdf.metadados(caminho)
    assert (livro.titulo, livro.autor, livro.formato) == ("O Livro de Teste", "Ana Autora", "pdf")
    assert livro.idioma == "pt-br" and livro.capitulos == 2
    c1, c2 = pdf.capitulo(caminho, 0), pdf.capitulo(caminho, 1)
    assert [p.texto for p in c1.paragrafos] == [
        f"{T}Capítulo 1",
        P1,  # hifenização juntada
        P2,
        "Que fizeram eles depois de tudo isso? Nada.",
        "Ele ficou ali parado, olhando a estrada que levava para longe. Era tarde.",
    ]  # sem cabeçalho repetido nem número de página; parágrafo que cruza a página junto
    assert c1.titulo == "Capítulo 1" and c1.paginas == 3.0
    assert c1.paragrafos[2].frases == ("Ela abriu a porta.", "O vento entrou com força e levou as folhas.")
    assert [p.texto for p in c2.paragrafos] == [f"{T}Capítulo 2", "Ela voltou. The end? Não."]
    assert c2.titulo == "Capítulo 2" and c2.paginas == 1.0
    assert livro.caracteres == sum(len(p.texto.replace(T, "")) for c in (c1, c2) for p in c.paragrafos)
    assert livro.capitulo(1).titulo == "Capítulo 2"


def test_sem_titulo_blocos_de_10_paginas(tmp_path: Path) -> None:
    doc = pymupdf.open()
    for n in range(1, 13):
        _pagina(doc, n, [f"She walked to the door and it was open. Page text {n} is here."])
    caminho = tmp_path / "en.pdf"
    doc.save(caminho)
    doc.close()
    livro = pdf.metadados(caminho)
    assert livro.capitulos == 2 and livro.idioma == "en" and livro.titulo == "en"
    c0 = pdf.capitulo(caminho, 0)
    assert c0.titulo == "Páginas 1–10" and c0.paginas == 10.0 and len(c0.paragrafos) == 10
    assert pdf.capitulo(caminho, 1).paginas == 2.0
    assert all("O Livro de Teste" not in p.texto for p in c0.paragrafos)


def test_escaneado_sem_texto(tmp_path: Path) -> None:
    doc = pymupdf.open()
    for _ in range(6):
        pg = doc.new_page()
        pg.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0.5, 0.5, 0.5))
    pg.insert_text((40, 400), "x" * 300)  # texto só depois da 5ª página não conta
    caminho = tmp_path / "scan.pdf"
    doc.save(caminho)
    doc.close()
    with pytest.raises(pdf.SemTexto):
        pdf.metadados(caminho)


def test_fora_do_intervalo(tmp_path: Path) -> None:
    with pytest.raises(IndexError):
        pdf.capitulo(_pdf_capitulos(tmp_path), 5)
