"""Registro das reações (R10) em ``~/.local/state/magi/reacoes.jsonl``, giro de 5 MB.
Dono: R0.2."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .contratos import Def, Disparo
from .governador import furou_cota

REGISTRO_FILE = Path.home() / ".local/state/magi/reacoes.jsonl"
GIRO_BYTES = 5 * 1024 * 1024


def gravar(d: Def, disparo: Disparo, agora: float, caminho: Path = REGISTRO_FILE) -> None:
    """Acrescenta uma linha JSON com a reação tocada (gira o arquivo acima de ``GIRO_BYTES``).

    O giro move o arquivo cheio para ``<nome>.1`` (substitui o anterior). Falha de disco é
    engolida: o registro nunca derruba o HUD."""
    linha = {
        "t": agora,
        "hora": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora)),
        "chave": d.chave,
        "n": d.n,
        "variante": disparo.variante,
        "motivo": disparo.motivo,
        "furou_cota": furou_cota(d),
    }
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        if caminho.exists() and caminho.stat().st_size >= GIRO_BYTES:
            caminho.replace(caminho.with_name(caminho.name + ".1"))
        with caminho.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError:
        pass
