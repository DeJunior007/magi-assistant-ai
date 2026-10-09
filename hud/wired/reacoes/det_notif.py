"""Detector `det_notif` (spec §5): cond. E: 46 (notificação chegou), 47 (popup de erro). Dono: R2.E.

Lê ``snap.notif`` (``(contador, urgência 0–2, monotônico)`` do ``data.Notificacoes``; None = sem
leitor ou nada ainda) e ``ctx["agora"]``. Contador maior que o último visto = notificação nova:
urgência 2 (crítica) → 47; senão 46, no máximo 1 a cada ``INTERVALO_46_S``. Notificação com mais de
``FRESCA_S`` s (pelo relógio monotônico do HUD) só é marcada como vista.

Chaves próprias no ``ctx``: ``_notif_visto`` (último contador visto), ``_notif_46_em`` (agora do
último 46).
"""

from __future__ import annotations

from typing import Any

from .contratos import Disparo

INTERVALO_46_S = 600.0  # 46 ≤ 1/10 min
FRESCA_S = 10.0
CRITICA = 2


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    notif = getattr(snap, "notif", None)
    if not notif:
        return []
    n, urg, quando = notif
    visto = ctx.get("_notif_visto", 0)
    if n <= visto:
        if n < visto:  # leitor reiniciado
            ctx["_notif_visto"] = n
        return []
    ctx["_notif_visto"] = n
    agora = float(ctx.get("agora", 0.0))
    if quando is not None and agora - float(quando) > FRESCA_S:
        return []
    if urg >= CRITICA:
        return [Disparo("popup_erro", "notificação crítica", fmt={"urgencia": urg})]
    ultimo = ctx.get("_notif_46_em")
    if ultimo is not None and agora - ultimo < INTERVALO_46_S:
        return []
    ctx["_notif_46_em"] = agora
    return [Disparo("notificacao", "notificação nova", fmt={"urgencia": urg})]
