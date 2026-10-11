"""Marcador por livro e registro de sessões (tarefa A1.4; spec §1, requirements A5, A10).

Posição em ``estado_dir/audiolivro.json`` (atômico, com ``.bak``; ≤ 1 escrita a cada 2 s em
leitura contínua + no fim); sessões em ``audiolivro.jsonl`` com giro de 5 MB. Relógio injetado.

Gravação: escreve ``.tmp``, move o principal para ``.bak`` e o ``.tmp`` para o principal. Se o
principal estiver ilegível (truncado), vale o ``.bak`` e a leitura recomeça do **início do
capítulo** salvo ali (CA-A5).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Posicao

#: Intervalo mínimo entre gravações em leitura contínua (CA-A5).
INTERVALO_S = 2.0
#: Tamanho em que o ``audiolivro.jsonl`` gira.
GIRO_BYTES = 5 * 1024 * 1024


def _ler(p: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _posicao(d: Any) -> Posicao | None:
    try:
        return Posicao(int(d["cap"]), int(d["par"]), int(d["frase"]), float(d.get("velocidade", 1.0)))
    except (TypeError, KeyError, ValueError):
        return None


class Marcador:
    def __init__(self, cfg: ConfigAudiolivro, *, relogio: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.relogio = relogio
        self._pendentes: dict[str, Posicao] = {}
        self._ultima: float | None = None

    @property
    def caminho(self) -> Path:
        return self.cfg.marcador_path

    @property
    def bak(self) -> Path:
        return self.caminho.with_name(self.caminho.name + ".bak")

    def _disco(self) -> tuple[dict[str, Any], bool]:
        """Conteúdo gravado e se veio do ``.bak``."""
        d = _ler(self.caminho)
        if d is not None:
            return d, False
        return (_ler(self.bak) or {}), True

    def posicao(self, livro_id: str) -> Posicao | None:
        """Última posição gravada do livro (do ``.bak`` se o principal estiver truncado)."""
        if livro_id in self._pendentes:
            return self._pendentes[livro_id]
        d, do_bak = self._disco()
        pos = _posicao(d.get(livro_id))
        if pos is not None and do_bak:
            return Posicao(pos.cap, 0, 0, pos.velocidade)
        return pos

    def avancar(self, livro_id: str, posicao: Posicao, *, forcar: bool = False) -> None:
        """Nova posição; grava no máximo 1×/``INTERVALO_S`` (``forcar`` = agora)."""
        self._pendentes[livro_id] = posicao
        agora = self.relogio()
        if forcar or self._ultima is None or agora - self._ultima >= INTERVALO_S:
            self.gravar()

    def gravar(self) -> None:
        """Grava as posições pendentes agora (fim da leitura, pausa)."""
        if not self._pendentes:
            return
        d, _ = self._disco()
        for lid, p in self._pendentes.items():
            d[lid] = {"cap": p.cap, "par": p.par, "frase": p.frase, "velocidade": p.velocidade}
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_name(self.caminho.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if _ler(self.caminho) is not None:
            os.replace(self.caminho, self.bak)
        os.replace(tmp, self.caminho)
        self._pendentes.clear()
        self._ultima = self.relogio()

    def registrar_sessao(self, registro: dict[str, Any]) -> None:
        """Uma linha no ``audiolivro.jsonl`` (A10)."""
        p = self.cfg.registro_path
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.stat().st_size >= GIRO_BYTES:
                os.replace(p, p.with_name(p.name + ".1"))
        except FileNotFoundError:
            pass
        linha = json.dumps({"ts": time.time(), **registro}, ensure_ascii=False)
        with p.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
