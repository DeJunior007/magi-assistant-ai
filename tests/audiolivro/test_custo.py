"""A1.4: estimativa de tempo (CA-A4: só tempo, custo de API = 0)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import magi.audiolivro as pacote
from magi.audiolivro import custo
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Livro, Paragrafo, Posicao


def _cap(n: int, paginas: float = 0.0) -> Capitulo:
    pars = tuple(Paragrafo(i, ("a" * 99 + ".", "b" * 199 + ".")) for i in range(10))
    return Capitulo(n, f"Cap {n}", pars, paginas)


class _Livro(Livro):
    def capitulo(self, n: int) -> Capitulo:  # sem arquivo: capítulos sintéticos
        return _cap(n, 7.0)


def _livro(formato: str = "epub") -> Livro:
    return _Livro(
        id="x",
        caminho=Path("x"),
        titulo="X",
        autor=None,
        idioma="pt-br",
        formato=formato,
        capitulos=4,
        caracteres=4 * 3010,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("velocidade", [0.8, 1.0, 1.25, 1.5])
def test_bate_com_formula(velocidade: float) -> None:
    cfg = ConfigAudiolivro()
    cap = _cap(1)
    est = custo.estimar(_livro(), cap, Posicao(1, 0, 0, velocidade), cfg)
    esperado = cap.caracteres / cfg.chars_por_minuto / velocidade
    assert est.minutos_capitulo == pytest.approx(esperado, rel=0.01)
    resto = cap.caracteres * 3  # cap 1 inteiro + caps 2 e 3
    assert est.minutos_livro_restante == pytest.approx(resto / cfg.chars_por_minuto / velocidade, rel=0.01)


def test_resto_a_partir_da_posicao() -> None:
    cfg = ConfigAudiolivro(chars_por_minuto=100)
    cap = _cap(3)  # último capítulo
    est = custo.estimar(_livro(), cap, Posicao(3, 9, 1), cfg)
    assert est.minutos_livro_restante == pytest.approx(200 / 100)
    est0 = custo.estimar(_livro(), cap, Posicao(3, 0, 0), cfg)
    assert est0.minutos_livro_restante == pytest.approx(cap.caracteres / 100)


def test_paginas_epub_e_pdf() -> None:
    cfg = ConfigAudiolivro(chars_por_pagina=1000)
    cap = _cap(0, paginas=7.0)
    assert custo.estimar(_livro("epub"), cap, Posicao(0, 0, 0), cfg).paginas_capitulo == 3.01
    assert custo.estimar(_livro("pdf"), cap, Posicao(0, 0, 0), cfg).paginas_capitulo == 7.0


def test_nenhum_caminho_pago() -> None:
    """Nada do pacote importa Budget/custos nem provedores pagos (A7, CA-A4)."""
    proibidos = ("budget", "costs", "openai", "anthropic", "elevenlabs")
    for arq in Path(pacote.__file__).parent.glob("*.py"):
        for no in ast.walk(ast.parse(arq.read_text(encoding="utf-8"))):
            if isinstance(no, ast.ImportFrom | ast.Import):
                nomes = [no.module or ""] if isinstance(no, ast.ImportFrom) else []
                nomes += [a.name for a in no.names]
                for nome in nomes:
                    assert not any(p in nome.lower() for p in proibidos), (arq.name, nome)
