"""Atividade do Pedro: "evento real", último uso e primeiro do dia (spec §5). Dono: R1.4.

Evento real = clique no HUD, faixa nova, Claude Code passou a rodar, Magui ouvindo, jogo abriu.
Estado em ``~/.local/state/magi/condessa-atividade.json``:

- ``ultimo``: relógio de parede (epoch) do último evento real;
- ``dia``: data local (``AAAA-MM-DD``) do último "primeiro evento do dia" (o que dispara o 57);
- ``primeiro_do_dia``: o último evento foi o primeiro do dia depois das 05h.

O caminho é injetável; com ``caminho=None`` vale o ``ESTADO_FILE`` do módulo, lido na hora (os
testes o trocam). Arquivo ausente ou ruim = estado vazio; falha ao gravar não derruba o HUD.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ESTADO_FILE = Path.home() / ".local/state/magi/condessa-atividade.json"
DIA_COMECA_H = 5  # antes das 05h ainda é "ontem" para o bom-dia


def dia_local(agora: float) -> str:
    """Data local ``AAAA-MM-DD`` do relógio de parede ``agora``."""
    return time.strftime("%Y-%m-%d", time.localtime(agora))


class Atividade:
    """Guarda o último evento real do Pedro e se o de hoje já foi o primeiro do dia."""

    def __init__(self, caminho: Path | None = None) -> None:
        self._caminho = caminho
        self._lido = False
        self.ultimo: float | None = None
        self.dia: str | None = None
        self.primeiro_do_dia: bool = False
        self.motivo: str | None = None

    @property
    def caminho(self) -> Path:
        return self._caminho if self._caminho is not None else ESTADO_FILE

    def _ler(self) -> None:
        if self._lido:
            return
        self._lido = True
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(dados, dict):
            return
        ultimo = dados.get("ultimo")
        self.ultimo = float(ultimo) if isinstance(ultimo, (int, float)) else None
        dia = dados.get("dia")
        self.dia = dia if isinstance(dia, str) else None
        self.primeiro_do_dia = bool(dados.get("primeiro_do_dia", False))

    def _gravar(self) -> None:
        dados = {"ultimo": self.ultimo, "dia": self.dia, "primeiro_do_dia": self.primeiro_do_dia}
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.caminho.with_suffix(".tmp")
            tmp.write_text(json.dumps(dados), encoding="utf-8")
            os.replace(tmp, self.caminho)
        except OSError:
            pass

    def evento(self, agora: float, motivo: str) -> bool:
        """Registra um evento real em ``agora`` (epoch). Devolve se foi o primeiro do dia (≥ 05h)."""
        self._ler()
        primeiro = time.localtime(agora).tm_hour >= DIA_COMECA_H and self.dia != dia_local(agora)
        if primeiro:
            self.dia = dia_local(agora)
        self.primeiro_do_dia = primeiro
        self.ultimo = agora
        self.motivo = motivo
        self._gravar()
        return primeiro

    def parado_s(self, agora: float) -> float | None:
        """Segundos desde o último evento real (None = nenhum ainda)."""
        self._ler()
        if self.ultimo is None:
            return None
        return max(0.0, agora - self.ultimo)
