"""Voz por trecho e elenco de personagens (tarefa A1.2; D1/D5; spec §3, requirements A4).

Sempre Kokoro, sempre na voz/idioma dela. Narração na voz dela; cada personagem com uma voz
Kokoro do grupo gênero × idade, ≠ voz dela, a mesma no livro todo (``Elenco`` persistido em
``elenco_dir/<livro_id>.json``); velocidade e pausa pela emoção. Grupos padrão em ``vozes.toml``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Genero, Idade, OpcoesVoz, Trecho

#: Velocidade final limitada a esta faixa (spec §3).
VELOCIDADE_MIN, VELOCIDADE_MAX = 0.7, 1.3
#: Trechos seguidos com as mesmas opções são juntados até este tamanho.
JUNTAR_ATE = 400


class Elenco:
    """Personagem (nome normalizado) → voz Kokoro, por livro; gravação atômica."""

    def __init__(
        self,
        livro_id: str,
        voz_dela: str,
        idioma: str,
        cfg: ConfigAudiolivro,
        caminho: Path | None = None,
    ) -> None:
        self.livro_id = livro_id
        self.voz_dela = voz_dela
        self.idioma = idioma
        self.cfg = cfg
        self.caminho = caminho or cfg.elenco_dir / f"{livro_id}.json"

    def voz(self, falante: str | None, genero: Genero | None, idade: Idade | None) -> str:
        """Voz do personagem (nova → primeira livre do grupo; gravada)."""
        raise NotImplementedError("A1.2")


def opcoes(trecho: Trecho, elenco: Elenco, velocidade: float) -> OpcoesVoz:
    """``OpcoesVoz`` Kokoro do trecho (``lang`` = idioma dela)."""
    raise NotImplementedError("A1.2")


def juntar(partes: Iterable[tuple[str, OpcoesVoz]]) -> list[tuple[str, OpcoesVoz]]:
    """Junta partes seguidas com opções iguais até ``JUNTAR_ATE`` caracteres."""
    raise NotImplementedError("A1.2")
