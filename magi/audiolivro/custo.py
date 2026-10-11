"""Estimativa de tempo de leitura (tarefa A1.4; spec §4, requirements A7.1).

Custo de API é sempre 0 (D1/D2: Kokoro + Qwen local): nada de ``Budget`` aqui.
``minutos = caracteres / (chars_por_minuto × velocidade)``. Páginas: PDF usa as reais do
capítulo; EPUB, ``caracteres / chars_por_pagina``.
"""

from __future__ import annotations

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Estimativa, Livro, Posicao


def minutos(caracteres: int, cfg: ConfigAudiolivro, velocidade: float = 1.0) -> float:
    return caracteres / (cfg.chars_por_minuto * max(velocidade, 0.1))


def _resto_capitulo(cap: Capitulo, posicao: Posicao) -> int:
    total = 0
    for i, p in enumerate(cap.paragrafos):
        if i < posicao.par:
            continue
        frases = p.frases[posicao.frase :] if i == posicao.par else p.frases
        total += len(" ".join(frases))
    return total


def estimar(livro: Livro, cap: Capitulo, posicao: Posicao, cfg: ConfigAudiolivro) -> Estimativa:
    """Páginas e minutos do capítulo e minutos do resto do livro a partir de ``posicao``."""
    v = posicao.velocidade
    if livro.formato == "pdf":
        paginas = cap.paginas
    else:
        paginas = cap.caracteres / cfg.chars_por_pagina
    resto = _resto_capitulo(cap, posicao) + sum(
        livro.capitulo(n).caracteres for n in range(cap.n + 1, livro.capitulos)
    )
    return Estimativa(
        paginas_capitulo=round(paginas, 2),
        minutos_capitulo=minutos(cap.caracteres, cfg, v),
        minutos_livro_restante=minutos(resto, cfg, v),
    )
