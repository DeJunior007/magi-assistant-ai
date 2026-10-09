"""Reações da Condessa: contratos, catálogo, governador e detectores (design §3). Dono: R0.1.

``DETECTORES`` lista todos os detectores do spec §5, cada um ``(anterior, snap, ctx) -> list[Disparo]``.
Cada tarefa de detector edita só o próprio módulo.
"""

from __future__ import annotations

from . import (
    det_claude,
    det_conversa,
    det_entrada,
    det_extras,
    det_musica,
    det_notif,
    det_sistema,
    det_tempo,
    det_volume,
)

DETECTORES = (
    det_tempo.detectar,
    det_musica.detectar,
    det_sistema.detectar,
    det_claude.detectar,
    det_entrada.detectar,
    det_conversa.detectar,
    det_volume.detectar,
    det_notif.detectar,
    det_extras.detectar,
)
