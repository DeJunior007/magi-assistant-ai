"""Detector `det_volume` (spec §5): cond. D: 31 (volume alto demais). Dono: R2.D.

Lê ``snap.volume`` (``(pct 0–150, mudo)`` do ``wpctl``, ``data.Volume``; None sem ``wpctl`` → nada)
e ``ctx["agora"]``. 31 = o volume subiu ≥ ``SALTO_PP`` pontos em ≤ ``JANELA_S`` s, sem mudo; depois
de disparar a janela zera (um disparo por salto). Mudo ou volume ausente também zeram a janela
(desmutar não é salto). A variante de pico do 26 (RMS da saída) ficou de fora: o ``wpctl`` não dá
nível de sinal (ver *Sobras* em ``tasks.md``).

Chave própria no ``ctx``: ``_volume_hist`` (lista de ``(agora, pct)`` dos últimos ``JANELA_S`` s).
"""

from __future__ import annotations

from typing import Any

from .contratos import Disparo

SALTO_PP = 20.0  # pontos percentuais
JANELA_S = 2.0


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    vol = getattr(snap, "volume", None)
    if not vol or vol[1]:
        ctx["_volume_hist"] = []
        return []
    pct = float(vol[0])
    agora = float(ctx.get("agora", 0.0))
    hist = [(t, p) for t, p in ctx.get("_volume_hist", ()) if agora - t <= JANELA_S]
    base = min((p for _, p in hist), default=pct)
    if pct - base >= SALTO_PP:
        ctx["_volume_hist"] = [(agora, pct)]
        return [Disparo("volume_alto", f"volume {base:.0f}% → {pct:.0f}%", fmt={"de": base, "para": pct})]
    hist.append((agora, pct))
    ctx["_volume_hist"] = hist
    return []
