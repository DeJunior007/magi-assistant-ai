"""A1.4: biblioteca (varredura, cache por mtime, achar, ambíguo, D3)."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from magi.audiolivro.biblioteca import SEM_TEXTO, Biblioteca, normalizar, nota
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Livro, livro_id

TITULOS = [
    "Dom Casmurro",
    "Memórias Póstumas de Brás Cubas",
    "O Cortiço",
    "A Hora da Estrela",
    "The Hobbit: or There and Back Again",
    "1984",
    "Harry Potter e a Pedra Filosofal",
    "Harry Potter e a Câmara Secreta",
    "Duna II",
    "Ensaio sobre a Cegueira",
]
FALAS = {
    "dom casmurro": "Dom Casmurro",
    "memorias postumas de bras cubas": "Memórias Póstumas de Brás Cubas",
    "cortiço": "O Cortiço",
    "a hora da estrela": "A Hora da Estrela",
    "the hobbit": "The Hobbit: or There and Back Again",
    "1984": "1984",
    "harry potter e a pedra filosofal": "Harry Potter e a Pedra Filosofal",
    "harry potter camara secreta": "Harry Potter e a Câmara Secreta",
    "duna dois": "Duna II",
    "ensaio sobre a cegeira": "Ensaio sobre a Cegueira",  # erro de reconhecimento
}


class _Leitor:
    """Lê o título do próprio arquivo (o conteúdo é o título); conta as leituras."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self, caminho: Path) -> Livro:
        self.n += 1
        titulo = caminho.read_text(encoding="utf-8")
        return Livro(
            id=livro_id(caminho, caminho.stat().st_size),
            caminho=caminho,
            titulo=titulo,
            autor=None,
            idioma="pt-br",
            formato="epub",
            capitulos=3,
            caracteres=1000,
        )


def _cfg(tmp_path: Path) -> ConfigAudiolivro:
    return ConfigAudiolivro(pasta=tmp_path / "Livros", cache_dir=tmp_path / "cache")


def _povoar(cfg: ConfigAudiolivro) -> None:
    cfg.pasta.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(TITULOS):
        (cfg.pasta / f"livro{i}.epub").write_text(t, encoding="utf-8")
    (cfg.pasta / "notas.txt").write_text("não é livro", encoding="utf-8")


def test_pasta_ausente_criada(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert not cfg.pasta.exists()
    assert Biblioteca(cfg, ler=_Leitor()).livros() == []
    assert cfg.pasta.is_dir()


def test_padrao_e_livros_em_casa(tmp_path: Path) -> None:
    cfg = ConfigAudiolivro()
    assert cfg.pasta == Path.home() / "Livros"
    assert str(cfg.pasta).startswith(str(tmp_path))  # conftest isola o HOME


def test_normalizar() -> None:
    assert normalizar("O Cortiço — Edição II") == ["cortico", "edicao", "2"]
    assert normalizar("The_Hobbit") == ["hobbit"]


@pytest.mark.parametrize("fala,esperado", sorted(FALAS.items()))
def test_dez_titulos_achados(tmp_path: Path, fala: str, esperado: str) -> None:
    cfg = _cfg(tmp_path)
    _povoar(cfg)
    achados = Biblioteca(cfg, ler=_Leitor()).achar(fala)
    assert achados and achados[0][0].titulo == esperado
    assert not Biblioteca.ambiguo(achados)


def test_ambiguo(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _povoar(cfg)
    achados = Biblioteca(cfg, ler=_Leitor()).achar("harry potter")
    assert {lv.titulo for lv, _ in achados[:2]} == {TITULOS[6], TITULOS[7]}
    assert Biblioteca.ambiguo(achados)
    assert not Biblioteca.ambiguo(achados[:1])


def test_nada_casa(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _povoar(cfg)
    assert Biblioteca(cfg, ler=_Leitor()).achar("guerra e paz") == []
    assert nota("", "Dom Casmurro") == 0.0


def test_cache_por_mtime(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _povoar(cfg)
    ler = _Leitor()
    Biblioteca(cfg, ler=ler).livros()
    assert ler.n == len(TITULOS)
    assert (cfg.cache_dir / "indice.json").is_file()
    ler2 = _Leitor()
    assert len(Biblioteca(cfg, ler=ler2).livros()) == len(TITULOS)
    assert ler2.n == 0
    (cfg.pasta / "livro0.epub").write_text("Dom Casmurro (edição nova)", encoding="utf-8")
    livros = Biblioteca(cfg, ler=ler2).livros()
    assert ler2.n == 1
    assert "Dom Casmurro (edição nova)" in {lv.titulo for lv in livros}


def test_pdf_real_e_sem_texto(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.pasta.mkdir(parents=True)
    vazio = fitz.open()
    vazio.new_page()
    vazio.save(cfg.pasta / "escaneado.pdf")
    doc = fitz.open()
    pg = doc.new_page()
    texto = "Era uma vez um reino distante onde todos liam livros em voz alta. " * 6
    pg.insert_textbox(fitz.Rect(50, 50, 550, 800), texto)
    doc.set_metadata({"title": "O Reino Distante"})
    doc.save(cfg.pasta / "reino.pdf")
    bib = Biblioteca(cfg)
    livros = bib.livros()
    assert [lv.titulo for lv in livros] == ["O Reino Distante"]
    assert livros[0].formato == "pdf"
    assert bib.ignorados == {cfg.pasta / "escaneado.pdf": SEM_TEXTO}
    assert bib.achar("reino distante")[0][0].titulo == "O Reino Distante"
    # do cache: o ignorado continua ignorado sem reabrir
    bib2 = Biblioteca(cfg, ler=_Leitor())
    assert len(bib2.livros()) == 1 and bib2.ignorados
