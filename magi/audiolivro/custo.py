"""Estimativa de tempo de leitura (tarefa A1.4; spec §4, requirements A7.1).

Custo de API é sempre 0 (D1/D2: Kokoro + Qwen local): nada de ``Budget`` aqui.
``minutos = caracteres / (chars_por_minuto × velocidade)``.
"""

from __future__ import annotations

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Estimativa, Livro, Posicao


def estimar(livro: Livro, cap: Capitulo, posicao: Posicao, cfg: ConfigAudiolivro) -> Estimativa:
    """Páginas e minutos do capítulo e minutos do resto do livro a partir de ``posicao``."""
    raise NotImplementedError("A1.4")
